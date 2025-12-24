"""
Cliente Cerebras para geração de resumos com IA.
Inclui circuit breaker, rate limiting e load balancing de API keys.
"""
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Tuple, Dict

import httpx

from app.config import settings, prompts
from app.database import SessionLocal
from app.models import AppSettings

logger = logging.getLogger(__name__)

# Configurações
CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"


class ApiKeyRotator:
    """
    Rotador de API keys com round-robin e cooldown por key.
    Persiste o índice atual no banco de dados.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._key_cooldowns: Dict[str, datetime] = {}  # key -> cooldown_until
        self._current_index = 0
        self._load_state()

    def _load_state(self):
        """Carrega índice atual do banco."""
        db = SessionLocal()
        try:
            row = db.query(AppSettings).filter(AppSettings.key == 'api_key_index').first()
            if row:
                self._current_index = int(row.value)
        finally:
            db.close()

    def _save_state(self):
        """Salva índice atual no banco."""
        db = SessionLocal()
        try:
            existing = db.query(AppSettings).filter(AppSettings.key == 'api_key_index').first()
            if existing:
                existing.value = str(self._current_index)
            else:
                db.add(AppSettings(key='api_key_index', value=str(self._current_index)))
            db.commit()
        except Exception as e:
            logger.error(f"Erro ao salvar índice de API key: {e}")
            db.rollback()
        finally:
            db.close()

    def get_next_key(self) -> Tuple[Optional[str], Optional[int]]:
        """
        Retorna a próxima API key disponível (round-robin).
        Pula keys em cooldown.

        Returns:
            Tuple de (api_key, key_index) ou (None, None) se nenhuma disponível
        """
        keys = settings.cerebras_api_keys
        if not keys:
            return None, None

        now = datetime.utcnow()

        with self._lock:
            # Tentar encontrar uma key disponível
            for _ in range(len(keys)):
                key = keys[self._current_index % len(keys)]
                key_index = self._current_index % len(keys)

                # Avançar para próxima (round-robin)
                self._current_index = (self._current_index + 1) % len(keys)

                # Verificar cooldown
                cooldown_until = self._key_cooldowns.get(key)
                if cooldown_until and now < cooldown_until:
                    remaining = (cooldown_until - now).total_seconds()
                    logger.debug(f"Key {key_index + 1}/{len(keys)} em cooldown ({remaining:.0f}s)")
                    continue

                # Key disponível
                self._save_state()
                if len(keys) > 1:
                    logger.debug(f"Usando API key {key_index + 1}/{len(keys)}")
                return key, key_index

            # Todas as keys em cooldown
            return None, None

    def set_key_cooldown(self, key: str, seconds: int = 60):
        """Coloca uma key em cooldown após rate limit."""
        with self._lock:
            self._key_cooldowns[key] = datetime.utcnow() + timedelta(seconds=seconds)
            keys = settings.cerebras_api_keys
            if key in keys:
                key_index = keys.index(key) + 1
                logger.warning(f"API key {key_index}/{len(keys)} em cooldown por {seconds}s")

    def clear_cooldown(self, key: str):
        """Remove cooldown de uma key."""
        with self._lock:
            self._key_cooldowns.pop(key, None)

    def get_status(self) -> dict:
        """Retorna status de todas as keys."""
        keys = settings.cerebras_api_keys
        now = datetime.utcnow()
        status = {
            "total_keys": len(keys),
            "current_index": self._current_index % len(keys) if keys else 0,
            "keys": []
        }
        for i, key in enumerate(keys):
            cooldown_until = self._key_cooldowns.get(key)
            key_status = {
                "index": i + 1,
                "available": not (cooldown_until and now < cooldown_until),
            }
            if cooldown_until and now < cooldown_until:
                key_status["cooldown_remaining"] = int((cooldown_until - now).total_seconds())
            status["keys"].append(key_status)
        return status


# Instância global do rotador
api_key_rotator = ApiKeyRotator()


class CircuitState(Enum):
    CLOSED = "closed"  # Normal, permitindo chamadas
    OPEN = "open"      # Bloqueado após muitas falhas
    HALF = "half"      # Testando se serviço voltou


class CerebrasError(Exception):
    """Erro base do cliente Cerebras."""
    pass


class TemporaryError(CerebrasError):
    """Erro temporário (timeout, 429, 5xx)."""
    pass


class PermanentError(CerebrasError):
    """Erro permanente (payload inválido, resposta vazia após retries)."""
    pass


@dataclass
class SummaryResult:
    """Resultado da geração de resumo."""
    summary_pt: str
    one_line_summary: str
    translated_title: str = None  # Título traduzido (se não estiver no idioma-alvo)


class CircuitBreaker:
    """
    Circuit breaker para proteger contra falhas da API.

    Estados:
    - CLOSED: Normal, permitindo chamadas
    - OPEN: Bloqueado após FAILURE_THRESHOLD falhas
    - HALF: Testando após RECOVERY_TIMEOUT_SECONDS
    """

    def __init__(self):
        self._load_state()

    def _load_state(self):
        """Carrega estado do banco."""
        db = SessionLocal()
        try:
            self.state = CircuitState.CLOSED
            self.failures = 0
            self.half_successes = 0
            self.last_failure = None
            self.last_call = None
            self.rate_limited_until = None

            # Carregar do banco
            for row in db.query(AppSettings).filter(
                AppSettings.key.in_([
                    'cerebras_state', 'cerebras_failures', 'cerebras_half_successes',
                    'cerebras_last_failure', 'cerebras_last_call', 'rate_limited_until'
                ])
            ).all():
                if row.key == 'cerebras_state':
                    self.state = CircuitState(row.value)
                elif row.key == 'cerebras_failures':
                    self.failures = int(row.value)
                elif row.key == 'cerebras_half_successes':
                    self.half_successes = int(row.value)
                elif row.key == 'cerebras_last_failure':
                    self.last_failure = datetime.fromisoformat(row.value)
                elif row.key == 'cerebras_last_call':
                    self.last_call = datetime.fromisoformat(row.value)
                elif row.key == 'rate_limited_until':
                    self.rate_limited_until = datetime.fromisoformat(row.value)

        finally:
            db.close()

    def _save_state(self):
        """Salva estado no banco."""
        db = SessionLocal()
        try:
            updates = {
                'cerebras_state': self.state.value,
                'cerebras_failures': str(self.failures),
                'cerebras_half_successes': str(self.half_successes),
            }

            if self.last_failure:
                updates['cerebras_last_failure'] = self.last_failure.isoformat()
            if self.last_call:
                updates['cerebras_last_call'] = self.last_call.isoformat()
            if self.rate_limited_until:
                updates['rate_limited_until'] = self.rate_limited_until.isoformat()

            for key, value in updates.items():
                existing = db.query(AppSettings).filter(AppSettings.key == key).first()
                if existing:
                    existing.value = value
                else:
                    db.add(AppSettings(key=key, value=value))

            db.commit()

        except Exception as e:
            logger.error(f"Erro ao salvar estado do circuit breaker: {e}")
            db.rollback()
        finally:
            db.close()

    def can_call(self) -> Tuple[bool, Optional[str]]:
        """
        Verifica se pode fazer chamada.

        Returns:
            Tuple de (pode_chamar, motivo_se_não)
        """
        now = datetime.utcnow()

        # Verificar rate limit
        if self.rate_limited_until and now < self.rate_limited_until:
            return False, f"Rate limited até {self.rate_limited_until}"

        # Verificar intervalo mínimo
        min_interval = 60.0 / settings.cerebras_max_rpm
        if self.last_call:
            elapsed = (now - self.last_call).total_seconds()
            if elapsed < min_interval:
                return False, f"Aguardando intervalo mínimo ({min_interval - elapsed:.1f}s)"

        # Verificar circuit breaker
        if self.state == CircuitState.OPEN:
            # Verificar se passou recovery timeout
            if self.last_failure:
                elapsed = (now - self.last_failure).total_seconds()
                if elapsed >= settings.recovery_timeout_seconds:
                    # Transicionar para HALF
                    self.state = CircuitState.HALF
                    self.half_successes = 0
                    self._save_state()
                    logger.info("Circuit breaker: OPEN -> HALF")
                else:
                    return False, f"Circuit breaker OPEN (recovery em {settings.recovery_timeout_seconds - elapsed:.0f}s)"

        return True, None

    def record_success(self):
        """Registra sucesso de chamada."""
        now = datetime.utcnow()
        self.last_call = now

        if self.state == CircuitState.HALF:
            self.half_successes += 1
            if self.half_successes >= settings.half_open_max_requests:
                # Transicionar para CLOSED
                self.state = CircuitState.CLOSED
                self.failures = 0
                logger.info("Circuit breaker: HALF -> CLOSED")
        else:
            self.failures = 0

        self._save_state()

    def record_failure(self, is_rate_limit: bool = False):
        """
        Registra falha de chamada.

        Args:
            is_rate_limit: Se True, não conta para circuit breaker
        """
        now = datetime.utcnow()
        self.last_call = now
        self.last_failure = now

        if is_rate_limit:
            # Rate limit não conta para circuit breaker
            self.rate_limited_until = now + timedelta(seconds=60)
            logger.warning("Rate limit atingido, cooldown de 60s")
        else:
            if self.state == CircuitState.HALF:
                # Uma falha em HALF reabre o circuito
                self.state = CircuitState.OPEN
                logger.warning("Circuit breaker: HALF -> OPEN (falha)")
            else:
                self.failures += 1
                if self.failures >= settings.failure_threshold:
                    self.state = CircuitState.OPEN
                    logger.warning(f"Circuit breaker: CLOSED -> OPEN ({self.failures} falhas)")

        self._save_state()


# Instância global do circuit breaker
circuit_breaker = CircuitBreaker()


def get_system_prompt() -> str:
    """Returns the system prompt from prompts.yaml."""
    return prompts.get("system_prompt", "You are a helpful assistant that summarizes articles.")


def get_user_prompt(content: str, title: str = "") -> str:
    """Returns the user prompt with content, title, and language interpolated."""
    template = prompts.get("user_prompt", "Summarize this article in {language}:\n\n{content}")
    return template.format(
        language=settings.summary_language,
        content=content,
        title=title or "Untitled"
    )


def _parse_json_response(content: str) -> dict:
    """
    Parseia resposta JSON de forma robusta.
    Lida com markdown code blocks, escapes incorretos, etc.
    """

    # Remover markdown code blocks se presentes
    # Padrão: ```json ... ``` ou ``` ... ```
    code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if code_block_match:
        content = code_block_match.group(1)

    # Tentar parse direto primeiro
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Tentar extrair JSON de dentro do texto
    json_start = content.find('{')
    json_end = content.rfind('}') + 1

    if json_start < 0 or json_end <= json_start:
        raise ValueError("JSON não encontrado na resposta")

    json_str = content[json_start:json_end]

    # Tentar parse
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Tentar corrigir problemas comuns de escape
    # Newlines literais dentro de strings
    json_str_fixed = json_str

    # Substituir newlines reais dentro de strings por \n
    # Isso é um hack mas ajuda com alguns modelos
    def fix_string_newlines(match):
        s = match.group(0)
        # Substituir newlines reais por escape
        s = s.replace('\n', '\\n').replace('\r', '\\r')
        return s

    # Encontrar strings JSON e corrigir
    json_str_fixed = re.sub(r'"[^"]*"', fix_string_newlines, json_str)

    try:
        return json.loads(json_str_fixed)
    except json.JSONDecodeError:
        pass

    # Última tentativa: extrair campos manualmente com regex
    summary_match = re.search(r'"summary_pt"\s*:\s*"((?:[^"\\]|\\.)*)"|"summary_pt"\s*:\s*"([^"]*)"', json_str, re.DOTALL)
    one_line_match = re.search(r'"one_line_summary"\s*:\s*"((?:[^"\\]|\\.)*)"|"one_line_summary"\s*:\s*"([^"]*)"', json_str, re.DOTALL)

    if summary_match and one_line_match:
        summary = summary_match.group(1) or summary_match.group(2) or ""
        one_line = one_line_match.group(1) or one_line_match.group(2) or ""
        # Decodificar escapes básicos
        summary = summary.replace('\\n', '\n').replace('\\r', '\r').replace('\\"', '"')
        one_line = one_line.replace('\\n', '\n').replace('\\r', '\r').replace('\\"', '"')
        return {
            "summary_pt": summary,
            "one_line_summary": one_line
        }

    raise ValueError(f"Não foi possível parsear JSON: {json_str[:200]}...")


async def generate_summary(content: str, title: str = "") -> SummaryResult:
    """
    Gera resumo usando API Cerebras.

    Args:
        content: Conteúdo do artigo para resumir
        title: Título do artigo (para tradução se necessário)

    Returns:
        SummaryResult com resumos

    Raises:
        TemporaryError: Erro temporário (retry possível)
        PermanentError: Erro permanente (não tentar novamente)
    """
    # Verificar circuit breaker
    can_call, reason = circuit_breaker.can_call()
    if not can_call:
        raise TemporaryError(f"Circuit breaker: {reason}")

    # Obter próxima API key disponível (load balancing)
    api_key, key_index = api_key_rotator.get_next_key()
    if not api_key:
        raise TemporaryError("Todas as API keys estão em cooldown")

    # Truncar conteúdo se muito grande (max ~4000 tokens ≈ 16000 chars)
    max_content_len = 12000
    if len(content) > max_content_len:
        content = content[:max_content_len] + "..."

    # Preparar request
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": settings.cerebras_model,
        "messages": [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": get_user_prompt(content, title)},
        ],
        "temperature": 0.3,
        "max_tokens": 1000,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.cerebras_timeout) as client:
            response = await client.post(
                CEREBRAS_API_URL,
                headers=headers,
                json=payload,
            )

            # Tratar rate limit (cooldown específico para esta key)
            if response.status_code == 429:
                api_key_rotator.set_key_cooldown(api_key, seconds=60)
                circuit_breaker.record_failure(is_rate_limit=True)
                raise TemporaryError(f"Rate limit atingido na key {key_index + 1}")

            # Tratar erros de servidor
            if response.status_code >= 500:
                circuit_breaker.record_failure()
                raise TemporaryError(f"Erro do servidor: HTTP {response.status_code}")

            # Tratar erros de cliente
            if response.status_code >= 400:
                circuit_breaker.record_failure()
                raise PermanentError(f"Erro de requisição: HTTP {response.status_code}")

            # Parse response
            data = response.json()
            logger.debug(f"API response keys: {data.keys()}")

            if 'choices' not in data or not data['choices']:
                circuit_breaker.record_failure()
                logger.error(f"Resposta sem choices: {data}")
                raise PermanentError("Resposta vazia da API")

            choice = data['choices'][0]
            logger.debug(f"Choice keys: {choice.keys()}")

            # Verificar se resposta foi truncada
            if choice.get('finish_reason') == 'length':
                logger.warning("Resposta truncada pela API (finish_reason=length)")

            # Tentar diferentes estruturas de resposta
            message = choice.get('message', {})
            if 'content' in message:
                content_response = message['content']
            elif 'reasoning' in message:
                # Alguns modelos retornam 'reasoning' em vez de 'content'
                content_response = message['reasoning']
            elif 'text' in choice:
                content_response = choice['text']
            elif 'content' in choice:
                content_response = choice['content']
            else:
                logger.error(f"Estrutura de resposta desconhecida: {choice}")
                circuit_breaker.record_failure()
                raise PermanentError(f"Estrutura de resposta desconhecida: {list(choice.keys())}")

            # Parse JSON do response
            try:
                result = _parse_json_response(content_response)

                summary_pt = result.get('summary_pt', '').strip()
                one_line = result.get('one_line_summary', '').strip()
                translated_title = result.get('translated_title')

                # Limpar translated_title se for "null" string ou vazio
                if translated_title and isinstance(translated_title, str):
                    translated_title = translated_title.strip()
                    if translated_title.lower() in ('null', 'none', ''):
                        translated_title = None

                if not summary_pt or not one_line:
                    raise ValueError("Campos obrigatórios vazios")

                # Truncar one_line se necessário
                if len(one_line) > 150:
                    one_line = one_line[:147] + "..."

                circuit_breaker.record_success()

                return SummaryResult(
                    summary_pt=summary_pt,
                    one_line_summary=one_line,
                    translated_title=translated_title,
                )

            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Erro ao parsear resposta: {e}")
                logger.error(f"Resposta raw: {content_response[:500]}")
                circuit_breaker.record_failure()
                raise PermanentError(f"Resposta inválida: {e}")

    except httpx.TimeoutException:
        circuit_breaker.record_failure()
        raise TemporaryError(f"Timeout após {settings.cerebras_timeout}s")

    except httpx.RequestError as e:
        circuit_breaker.record_failure()
        raise TemporaryError(f"Erro de conexão: {e}")
