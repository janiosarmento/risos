# RSS Reader com IA — Especificação Final do Projeto

## Visão Geral

Aplicação web estilo Feedly para leitura de feeds RSS, com resumos automáticos em português gerados por IA (Cerebras API). O sistema é single-user, executado em servidor próprio, com foco em previsibilidade operacional, controle de custos e simplicidade arquitetural.

O projeto prioriza:
- Robustez com SQLite
- Processamento assíncrono controlado
- Segurança defensiva (especialmente XSS e SSRF)
- Crescimento controlado de dados
- Ausência de dependências externas críticas em produção


## Princípios Arquiteturais

1. Um único processo de escrita no banco por vez
2. Toda fila e estado crítico persistem no banco
3. Nenhuma lógica essencial depende apenas de memória
4. Conteúdo externo nunca é confiável
5. Retenção de dados é finita e configurável
6. Background jobs nunca competem com a API por recursos


## Arquitetura Geral

### Componentes

- Frontend: HTML estático + Alpine.js + Tailwind (assets locais)
- Backend: FastAPI (1 worker)
- Banco: SQLite em modo WAL
- Jobs: APScheduler (modo single-instance, persistente)
- IA: Cerebras API com rate limiting, fila persistente e circuit breaker
- Proxy: Nginx (WordOps)


## Estrutura de Diretórios

```
/var/www/rss.sarmento.org/
├── htdocs/                         # Servido pelo Nginx
│   ├── index.html                  # App principal
│   └── static/
│       ├── css/
│       │   └── app.css             # Tailwind compilado
│       └── js/
│           ├── app.js              # Lógica Alpine.js
│           └── alpine.min.js       # Alpine.js local
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app + lifespan
│   │   ├── config.py               # Settings via pydantic-settings
│   │   ├── database.py             # SQLite + SQLAlchemy
│   │   ├── models.py               # Modelos ORM
│   │   ├── schemas.py              # Pydantic schemas
│   │   ├── dependencies.py         # Auth, rate limiting
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── categories.py
│   │   │   ├── feeds.py
│   │   │   ├── posts.py
│   │   │   └── system.py           # Health, status
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── feed_parser.py
│   │       ├── content_extractor.py
│   │       ├── html_sanitizer.py
│   │       ├── cerebras.py         # Cliente IA + circuit breaker
│   │       └── scheduler.py        # APScheduler + jobs
│   ├── alembic/                    # Migrations
│   │   ├── versions/
│   │   └── env.py
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── data/                       # Runtime data
│   │   ├── reader.db
│   │   └── app.log
│   └── .env
└── PROJETO.md
```


## Banco de Dados (SQLite)

### Configuração Obrigatória

- journal_mode = WAL
- synchronous = NORMAL
- busy_timeout = 5000
- Uma única conexão de escrita por vez (via SQLAlchemy session scoping)
- Uvicorn/ASGI com 1 worker (evita scheduler duplicado e escrita concorrente)

### Estratégia de Concorrência

- API: leitura majoritária
- Escritas:
  - ingestão de feeds
  - marcação de leitura
  - persistência de resumos
- Background jobs nunca executam em paralelo entre si

### Verificação de Integridade no Startup

Ao iniciar a aplicação:
1. Se o DB tiver mais de 100MB: executa `PRAGMA quick_check;` (rápido)
2. Caso contrário: executa `PRAGMA integrity_check;`
3. Se falhar: log crítico, não inicia, exit code 1
4. Se passar: executa migrations pendentes via Alembic
5. Se migration falhar: log crítico, não inicia, exit code 1

Migrations:
- Versionadas com Alembic
- Executadas automaticamente no startup
- Rollback manual apenas (não automático)
- Migrations devem ser idempotentes e minimizar operações longas


## Schema SQL Completo

```sql
-- Categorias
CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    position INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_categories_parent ON categories(parent_id);

-- Feeds
CREATE TABLE feeds (
    id INTEGER PRIMARY KEY,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    site_url TEXT,
    last_fetched_at DATETIME,
    -- Tratamento de erros
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    last_error_at DATETIME,
    next_retry_at DATETIME,
    disabled_at DATETIME,
    disable_reason TEXT,
    -- Detecção de GUID instável
    guid_unreliable BOOLEAN DEFAULT 0,
    guid_collision_count INTEGER DEFAULT 0,
    -- Bypass de deduplicação por URL (para feeds problemáticos)
    allow_duplicate_urls BOOLEAN DEFAULT 0,
    -- Metadados
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_feeds_category ON feeds(category_id);
CREATE INDEX idx_feeds_next_retry ON feeds(next_retry_at) WHERE disabled_at IS NULL;

-- Posts
CREATE TABLE posts (
    id INTEGER PRIMARY KEY,
    feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    guid TEXT,
    url TEXT,
    normalized_url TEXT,
    title TEXT,
    author TEXT,
    content TEXT,                   -- Resumo até 500 chars para listagem
    full_content TEXT,              -- Conteúdo completo (sob demanda)
    content_hash TEXT,
    published_at DATETIME,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    sort_date DATETIME,             -- Ordenação: published_at ou fetched_at
    is_read BOOLEAN DEFAULT 0,
    read_at DATETIME,
    fetch_full_attempted_at DATETIME -- Cooldown para retry de full_content
    -- Sem UNIQUE constraints; deduplicação via índices parciais
);

-- Índices parciais para deduplicação (NULL não viola)
CREATE UNIQUE INDEX idx_posts_guid ON posts(feed_id, guid) WHERE guid IS NOT NULL;
CREATE UNIQUE INDEX idx_posts_url ON posts(feed_id, normalized_url)
    WHERE normalized_url IS NOT NULL;

CREATE INDEX idx_posts_feed ON posts(feed_id);
CREATE INDEX idx_posts_read ON posts(is_read);
CREATE INDEX idx_posts_sort ON posts(sort_date DESC);
CREATE INDEX idx_posts_hash ON posts(content_hash);
CREATE INDEX idx_posts_read_at ON posts(read_at) WHERE is_read = 1;

-- Índice parcial para dedupe por content_hash (fallback final)
CREATE UNIQUE INDEX idx_posts_content_hash ON posts(feed_id, content_hash)
    WHERE content_hash IS NOT NULL AND guid IS NULL AND normalized_url IS NULL;

-- Cache de resumos IA (por content_hash)
CREATE TABLE ai_summaries (
    id INTEGER PRIMARY KEY,
    content_hash TEXT UNIQUE NOT NULL,
    summary_pt TEXT NOT NULL,
    one_line_summary TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_summaries_hash ON ai_summaries(content_hash);

-- Fila de resumos pendentes (por post)
CREATE TABLE summary_queue (
    id INTEGER PRIMARY KEY,
    post_id INTEGER UNIQUE NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    priority INTEGER DEFAULT 0,     -- 0=background, 10=usuário abriu
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    error_type TEXT,                -- 'temporary' ou 'permanent'
    locked_at DATETIME,
    cooldown_until DATETIME,        -- Para erros temporários após 5 tentativas
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_queue_priority ON summary_queue(priority DESC, created_at);
CREATE INDEX idx_queue_pending ON summary_queue(locked_at, cooldown_until);

-- Falhas permanentes de resumo
CREATE TABLE summary_failures (
    id INTEGER PRIMARY KEY,
    content_hash TEXT NOT NULL,
    last_error TEXT,
    failed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_failures_hash ON summary_failures(content_hash);

-- Configurações da aplicação (key-value)
CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Blacklist de tokens JWT
CREATE TABLE token_blacklist (
    jti TEXT PRIMARY KEY,
    expires_at DATETIME NOT NULL
);

CREATE INDEX idx_blacklist_expires ON token_blacklist(expires_at);

-- Lock do scheduler
CREATE TABLE scheduler_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    locked_by TEXT NOT NULL,
    locked_at DATETIME NOT NULL,
    heartbeat_at DATETIME NOT NULL
);

-- Logs de limpeza
CREATE TABLE cleanup_logs (
    id INTEGER PRIMARY KEY,
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    posts_removed INTEGER DEFAULT 0,
    full_content_cleared INTEGER DEFAULT 0,
    summaries_cleared INTEGER DEFAULT 0,
    unread_removed INTEGER DEFAULT 0,
    bytes_freed INTEGER DEFAULT 0,
    duration_seconds REAL,
    notes TEXT
);

CREATE INDEX idx_cleanup_executed ON cleanup_logs(executed_at DESC);
```


## Modelo de Dados

### Posts — Deduplicação Robusta

A deduplicação segue a seguinte ordem:

1. (feed_id, guid) quando o GUID for estável
2. (feed_id, normalized_url) como fallback
3. (feed_id, content_hash) como último recurso

#### Normalização de URL (para dedupe)

Objetivo: remover ruído sem "colar" URLs diferentes.

Regras:
- Normalizar apenas o hostname para lowercase
- Remover fragmento (#...)
- Remover porta padrão (:80 para http, :443 para https)
- Rejeitar URLs com userinfo (user:pass@host) — log warning e ignorar post
- Remover apenas query params de tracking conhecidos:
  - utm_* (qualquer parâmetro começando com utm_)
  - fbclid
  - gclid
- Remover trailing slash apenas quando o path não for "/"
- Preservar o esquema (http/https) na chave de dedupe
- Preservar params genéricos como `ref`, `source`, `id`

Exemplo:
```
https://Site.com:443/Article?utm_source=rss&id=123#comments
→ https://site.com/Article?id=123
```

#### Detecção de GUID Instável

Campo em feeds: `guid_unreliable BOOLEAN DEFAULT 0`

Detecção no momento da inserção:
1. Ao inserir post, se já existe post com mesmo (feed_id, guid) mas URL diferente:
   - Incrementa `guid_collision_count` no feed
   - Se `guid_collision_count >= 3`: marca `guid_unreliable = 1`
   - Log de warning na primeira marcação

Heurística adicional (opcional, aplicada no primeiro fetch):
- Se GUID contém apenas dígitos e tem mais de 10 caracteres: suspeito
- Se GUID contém padrão de timestamp Unix (10 dígitos começando com 17...): suspeito
- Se suspeito: incrementa guid_collision_count em 1

Quando `guid_unreliable = 1`:
- Deduplicação ignora GUID, usa apenas normalized_url e content_hash
- UNIQUE(feed_id, guid) não é violado pois guid pode ser NULL para novos posts

#### Bypass de Deduplicação por URL

Campo em feeds: `allow_duplicate_urls BOOLEAN DEFAULT 0`

Para feeds que legitimamente reutilizam URLs (live blogs, landing pages atualizadas):
- Quando `allow_duplicate_urls = 1`: deduplicação ignora normalized_url
- Dedupe passa a depender apenas de GUID (se confiável) ou content_hash
- Toggle manual via API ou admin

**Consequência documentada**: feeds que reutilizam URL terão itens deduplicados por padrão. Isso é comportamento aceito no escopo do projeto. Para feeds problemáticos, o operador pode ativar `allow_duplicate_urls` manualmente.

### Conteúdo

- `content`: versão sanitizada e truncada (max 500 chars), usada em listagens
- `full_content`: armazenado apenas quando:
  - o usuário abre o post (fetch sob demanda), ou
  - o feed não fornece conteúdo suficiente (< 200 chars no RSS)

**Fetch sob demanda com cooldown**:
- `fetch_full_attempted_at`: registra quando foi tentado buscar full_content
- Se fetch falhar: não tentar novamente por 24 horas
- Condição para tentar: `full_content IS NULL AND content < 200 chars AND (fetch_full_attempted_at IS NULL OR fetch_full_attempted_at < now - 24h)`

### Hash de Conteúdo (cache de IA)

Objetivo: reduzir reprocessamento sem gerar colisões que causem resumo errado.

**Fonte do hash**: sempre usar a melhor versão disponível do conteúdo:
1. Se `full_content` existe: hash do full_content normalizado
2. Senão: hash do `content` do feed

**Atualização ao receber full_content**:
- Se o post ainda está na fila (sem resumo): recalcular content_hash
- Se já existe resumo para o novo hash em ai_summaries: marcar como ready
- Se não existe: atualizar summary_queue.content_hash para reprocessar

Pipeline de normalização antes do hash:
1. Extrair texto do HTML (strip tags)
2. Remover blocos de ads conhecidos (seletores CSS hardcoded)
3. Normalizar whitespace (colapsar múltiplos espaços/quebras em um)
4. Remover linhas que parecem boilerplate:
   - Timestamps isolados (regex: `^\d{4}-\d{2}-\d{2}.*$`)
   - "Leia mais", "Continua após publicidade", etc.

Lista de seletores CSS para remoção de ads:

Seletores seguros (sempre aplicados):
```python
SAFE_AD_SELECTORS = [
    '.ad', '.ads', '.advertisement', '.advertising',
    '.sponsored', '.promo', '.promotion',
    '.social-share', '.share-buttons',
    '.newsletter-signup', '.subscribe-box',
]
```

Seletores agressivos (podem remover conteúdo legítimo):
```python
AGGRESSIVE_AD_SELECTORS = [
    '[class*="ad-"]', '[class*="ads-"]',
    '[id*="ad-"]', '[id*="ads-"]',
    '.related-posts', '.recommended',
]
```

**Importante**: remoção de seletores é aplicada somente no conteúdo pós-Readability (dentro do artigo principal), não no documento inteiro.

**Fallback para evitar texto pobre**:
1. Aplicar todos os seletores (seguros + agressivos)
2. Se texto resultante < 400 caracteres:
   - Refazer apenas com seletores seguros
   - Usar a versão mais longa

Algoritmo de hash:
- Se conteúdo normalizado <= 200KB: SHA-256 do conteúdo inteiro
- Se > 200KB: SHA-256 de (primeiros 100KB + últimos 100KB)

Observação:
- Não aplicar lowercase para evitar aumentar colisões


## Retenção de Dados

### Configurações via .env

```
MAX_POSTS_PER_FEED=500
MAX_POST_AGE_DAYS=365
MAX_UNREAD_DAYS=90
MAX_DB_SIZE_MB=1024
```

### Política de Limpeza

Executada diariamente às 03:00 (configurável via CLEANUP_HOUR).

Ordem de execução:
1. Remover posts lidos há mais de MAX_POST_AGE_DAYS
2. Para cada feed, remover posts lidos excedendo MAX_POSTS_PER_FEED (mais antigos primeiro)
3. Limpar full_content de posts lidos há mais de 30 dias
4. Remover posts não lidos há mais de MAX_UNREAD_DAYS
5. Remover entradas de summary_failures com mais de 90 dias
6. Remover entradas de cleanup_logs com mais de 90 dias
7. Remover tokens expirados da blacklist

#### Comportamento ao Atingir MAX_DB_SIZE_MB

Verificado após limpeza principal:

1. Se DB > MAX_DB_SIZE_MB:
   - Executa VACUUM
   - Recalcula tamanho
2. Se ainda > limite:
   - Reduz temporariamente MAX_POST_AGE_DAYS em 30 dias
   - Executa limpeza novamente
   - Repete até caber ou atingir mínimo de 30 dias
3. Se ainda > limite com idade mínima:
   - Log de alerta crítico
   - Continua operando (não bloqueia)
   - Seta app_settings: `db_size_warning = "DB excede limite configurado"`

#### Logs de Limpeza

Cada execução registra em cleanup_logs:
- posts_removed
- full_content_cleared
- summaries_cleared (de summary_failures)
- unread_removed (posts não lidos removidos por MAX_UNREAD_DAYS)
- bytes_freed (calculado via diferença de page_count * page_size)
- duration_seconds
- notes (detalhes ou warnings)

Frontend exibe aviso discreto se unread_removed > 0 no último cleanup.


## IA — Cache e Processamento de Resumos

### Cache de Resumos

Tabela `ai_summaries` armazena resumos por content_hash (não por post).

Benefício: posts com conteúdo idêntico compartilham o mesmo resumo sem custo adicional de IA.

### Fila Persistente (por post)

Tabela `summary_queue` com uma entrada por post_id.

Campo `content_hash` armazenado para evitar recálculo durante processamento (cache local).

Fluxo do worker:
1. Busca próximo item elegível da fila (ver query abaixo)
2. Verifica se content_hash já existe em ai_summaries
   - Se sim: remove da fila, finaliza (0 chamadas à IA)
3. Chama Cerebras API
4. Se sucesso: grava em ai_summaries, remove da fila
5. Se erro: classifica e trata (ver Política de Tentativas)

Query para buscar próximo item:
```sql
SELECT * FROM summary_queue
WHERE (locked_at IS NULL OR locked_at < datetime('now', '-300 seconds'))
  AND (cooldown_until IS NULL OR cooldown_until < datetime('now'))
ORDER BY priority DESC, created_at ASC
LIMIT 1
```

#### Aquisição Atômica de Lock

Para evitar race conditions, o lock deve ser adquirido em operação única:

```sql
UPDATE summary_queue
SET locked_at = datetime('now')
WHERE id = :candidate_id
  AND (locked_at IS NULL OR locked_at < datetime('now', '-300 seconds'))
  AND (cooldown_until IS NULL OR cooldown_until < datetime('now'))
```

Verificar `rowcount == 1` para confirmar aquisição. Se `rowcount == 0`, outro worker pegou o item; buscar próximo candidato.

### Política de Tentativas

Máximo de 5 tentativas por ciclo, com tratamento diferenciado por tipo de erro.

Erros temporários (error_type = 'temporary'):
- Timeout
- Erro de conexão
- HTTP 429 (rate limit)
- HTTP 5xx

Ao falhar com erro temporário:
- attempts += 1
- Se attempts < 5: libera lock, será reprocessado no próximo ciclo
- Se attempts >= 5: entra em cooldown
  - cooldown_until = now + 24 horas
  - attempts = 0 (reset para novo ciclo após cooldown)

Erros permanentes (error_type = 'permanent'):
- Payload inválido
- Resposta vazia da IA (3x consecutivas)
- Erro de parsing do response

Ao falhar com erro permanente:
- attempts += 1
- Se attempts >= 5: remove da fila, registra em summary_failures

### Circuit Breaker Persistente (Cerebras)

Estado salvo em app_settings:
- cerebras_state: CLOSED | OPEN | HALF
- cerebras_failures: contador de falhas consecutivas
- cerebras_half_successes: contador de sucessos em modo HALF
- cerebras_last_failure: timestamp
- cerebras_last_success: timestamp

Parâmetros (.env):
```
FAILURE_THRESHOLD=5
RECOVERY_TIMEOUT_SECONDS=300
HALF_OPEN_MAX_REQUESTS=3
```

Transições:

| De | Para | Condição |
|----|------|----------|
| CLOSED | OPEN | cerebras_failures >= 5 |
| OPEN | HALF | now - cerebras_last_failure >= 300s |
| HALF | CLOSED | cerebras_half_successes >= 3 |
| HALF | OPEN | qualquer falha |

Ao transicionar:
- CLOSED → OPEN: log warning
- OPEN → HALF: reset cerebras_half_successes = 0
- HALF → CLOSED: reset cerebras_failures = 0, log info
- HALF → OPEN: log warning

Nota sobre 429:
- HTTP 429 NÃO conta para abrir circuito
- 429 ativa rate_limited_until (ver Rate Limiting)


## Rate Limiting da IA

Regras:
- Nenhuma chamada à IA ocorre dentro de requests HTTP
- Requests apenas inserem na fila
- Worker garante espaçamento entre chamadas

Implementação:
```python
MIN_INTERVAL_SECONDS = 60 / CEREBRAS_MAX_RPM  # 3s para 20 RPM
```

O worker:
1. Verifica rate_limited_until em app_settings
   - Se now < rate_limited_until: não faz chamada, aguarda próximo ciclo
2. Verifica tempo desde última chamada (cerebras_last_call em app_settings)
   - Se elapsed < MIN_INTERVAL_SECONDS: não faz chamada
3. Atualiza cerebras_last_call = now **antes** da chamada (garante pacing mesmo em falha rápida)
4. Executa chamada
5. Atualiza cerebras_last_success ou cerebras_last_failure conforme resultado

Nota: `cerebras_last_call` é atualizado **sempre que uma tentativa é feita**, independente de sucesso ou falha. Isso evita bursts em caso de erros instantâneos.

Tratamento de 429:
- Ao receber 429: rate_limited_until = now + 60s
- Não conta como falha para circuit breaker
- Worker respeita rate_limited_until no próximo ciclo


## Feeds — Tratamento de Erros

### Campos em feeds

```sql
error_count INTEGER DEFAULT 0,
last_error TEXT,
last_error_at DATETIME,
next_retry_at DATETIME,
disabled_at DATETIME,
disable_reason TEXT
```

### Backoff Progressivo

Intervalo calculado ao registrar erro:

| error_count | Intervalo até próxima tentativa |
|-------------|--------------------------------|
| 1 | 1 hora |
| 2 | 4 horas |
| 3 | 12 horas |
| 4 | 24 horas |
| 5+ | 48 horas |

Fórmula: `min(48, 2^(error_count-1))` horas

Ao registrar erro:
```python
feed.error_count += 1
feed.last_error = str(error)
feed.last_error_at = now
feed.next_retry_at = now + timedelta(hours=backoff_hours)
```

Ao sucesso:
```python
feed.error_count = 0
feed.last_error = None
feed.last_error_at = None
feed.next_retry_at = None
```

### Desativação Automática

Quando error_count >= 10:
```python
feed.disabled_at = now
feed.disable_reason = f"Falhas consecutivas: {feed.last_error}"
```

Feed desativado:
- Não é atualizado pelo job update_feeds
- Aparece destacado na UI com opção de reativar

Reativação manual (via API):
```python
feed.error_count = 0
feed.disabled_at = None
feed.disable_reason = None
feed.next_retry_at = None
# Tenta fetch imediato; se falhar, volta ao backoff normal
```

### Erros Considerados

Incrementam error_count:
- Timeout (10s)
- HTTP 4xx/5xx
- XML/RSS inválido
- SSL/TLS falhou
- DNS não resolveu
- Conexão recusada

Não incrementam:
- Feed vazio mas válido (0 posts)
- Nenhum post novo (todos duplicados)
- Erros de parsing de posts individuais (feed em si ok)


## Segurança

### HTML e XSS

Sanitização via bleach com whitelist estrita.

```python
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'b', 'i', 'u',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
    'a', 'img', 'figure', 'figcaption',
    'table', 'thead', 'tbody', 'tr', 'th', 'td'
]

ALLOWED_ATTRS = {
    'a': ['href', 'title', 'rel', 'target'],
    'img': ['src', 'alt', 'title'],
    'th': ['colspan', 'rowspan'],
    'td': ['colspan', 'rowspan'],
}
```

Processamento adicional após bleach:
- Links (`<a>`): adicionar `rel="noopener noreferrer" target="_blank"`
- Validar href: apenas http/https, bloquear javascript:, data:
- Validar img src: apenas https e data: (imagens inline)

### CSP no Nginx

```nginx
add_header Content-Security-Policy "
    default-src 'self';
    script-src 'self';
    style-src 'self';
    img-src 'self' https: data:;
    font-src 'self';
    connect-src 'self';
    frame-ancestors 'none';
    base-uri 'self';
    form-action 'self';
" always;
```

### Proxy de Conteúdo (SSRF-safe)

Objetivo: permitir fetch de conteúdo de artigos sem expor SSRF.

#### Restrição de Uso

O proxy `/api/proxy` só aceita URLs que correspondam a posts existentes:
- A URL solicitada deve bater com `posts.url` ou `posts.normalized_url` de algum post no banco
- Isso impede uso do proxy como ferramenta genérica de fetch

#### Whitelist de Hostnames (validação adicional)

Mantida dinamicamente baseada nos feeds cadastrados:
- Hostname extraído de feed.url
- Hostname extraído de feed.site_url (se preenchido)

Match exato por hostname normalizado (IDN → punycode).

#### Validações Antes do Fetch

1. Hostname da URL está na whitelist
2. Protocolo é http ou https
3. Porta é 80, 443 ou omitida
4. Host não é IP literal (regex: `^\d+\.\d+\.\d+\.\d+$` ou IPv6)
5. Resolver DNS e verificar que IP não é:
   - 127.0.0.0/8 (loopback)
   - 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 (privado)
   - 169.254.0.0/16 (link-local)
   - ::1, fe80::/10 (IPv6 loopback/link-local)

#### Comportamento do Fetch

```python
async with httpx.AsyncClient() as client:
    # Streaming real: não baixa corpo antes de iterar
    async with client.stream(
        "GET",
        url,
        timeout=10.0,
        follow_redirects=False,
        headers={'User-Agent': 'RSSReader/1.0'}
    ) as response:
        if response.status_code >= 300:
            raise HTTPException(400, "Recurso não disponível")

        # Streaming com limite real
        content = b""
        async for chunk in response.aiter_bytes():
            content += chunk
            if len(content) > 5_242_880:  # 5MB
                raise HTTPException(413, "Conteúdo muito grande")

        return content
```

### Autenticação

#### JWT

- Algoritmo: HS256
- Expiração: 24h (configurável)
- Payload: `{ "sub": "user", "exp": timestamp, "jti": uuid }`
- Secret: mínimo 32 caracteres, validado no startup

#### Validação de Senha

A senha é comparada diretamente com APP_PASSWORD do .env (comparação em tempo constante).
Não há hash armazenado — escopo single-user não justifica complexidade adicional.

#### Blacklist de Tokens

Logout adiciona jti à token_blacklist com expires_at.

Validação de token:
1. Decodifica e verifica assinatura
2. Verifica exp não expirado
3. Verifica jti não está na blacklist

Limpeza: job diário remove `WHERE expires_at < now()`.

#### Armazenamento no Frontend

- Token mantido apenas em variável JavaScript (memória)
- Enviado via header `Authorization: Bearer {token}`
- Perdido ao fechar/recarregar aba (comportamento intencional)
- Usuário faz login novamente quando necessário

### Rate Limiting HTTP

```python
from slowapi import Limiter

def get_real_ip(request: Request) -> str:
    # Confia em X-Forwarded-For apenas se request vier do Nginx local
    if request.client.host == "127.0.0.1":
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host

limiter = Limiter(key_func=get_real_ip)
```

Limites:
- Login: 5/minuto por IP
- API geral: 100/minuto por IP
- Refresh de feeds: 10/minuto por IP


## Background Jobs

### Garantia de Instância Única

Tabela scheduler_lock com id fixo = 1.

Ao iniciar:
1. Gera instance_id = uuid4()
2. Tenta adquirir lock:
   ```sql
   INSERT OR REPLACE INTO scheduler_lock (id, locked_by, locked_at, heartbeat_at)
   SELECT 1, :instance_id, :now, :now
   WHERE NOT EXISTS (
       SELECT 1 FROM scheduler_lock
       WHERE heartbeat_at > datetime('now', '-60 seconds')
   )
   ```
3. Se inseriu: scheduler ativo, inicia jobs
4. Se não inseriu: outro scheduler ativo, não inicia jobs (API continua funcionando)

Heartbeat: a cada 30s atualiza `heartbeat_at = now` onde `locked_by = instance_id`.

Shutdown limpo: tenta `DELETE FROM scheduler_lock WHERE locked_by = instance_id`.

### Jobs Definidos

| Job | Intervalo | Descrição |
|-----|-----------|-----------|
| update_feeds | 30 min | Atualiza feeds elegíveis (next_retry_at <= now, não disabled) |
| process_summaries | 1 min | Processa 1 item da fila respeitando rate limit |
| cleanup_retention | diário 03:00 | Aplica política de retenção completa |
| health_check | 5 min | Verifica integridade do sistema |

### Health Checks Internos

Verificações:
1. Banco responde: `SELECT 1`
2. Espaço em disco > 100MB no volume do DB
3. Tamanho do banco < MAX_DB_SIZE_MB
4. Fila não travada: não há itens com locked_at > 1 hora sem progresso
5. Circuit breaker não está OPEN há mais de 1 hora

Se qualquer check falhar:
- Log de warning com detalhes
- Seta app_settings: `health_warning = "descrição do problema"`

Se todos passarem:
- Remove health_warning de app_settings (se existir)

Frontend exibe health_warning quando presente.


## API Endpoints

### Autenticação

```
POST /api/auth/login
  Body: { "password": "..." }
  Response: { "token": "...", "expires_at": "..." }

POST /api/auth/logout
  Header: Authorization: Bearer {token}
  Response: { "ok": true }

GET /api/auth/me
  Header: Authorization: Bearer {token}
  Response: { "authenticated": true }
```

### Sistema

```
GET /api/health
  (sem auth)
  Response: { "status": "ok", "db": "ok" }

GET /api/status
  Header: Authorization: Bearer {token}
  Response: {
    "feeds_count": 10,
    "posts_count": 5000,
    "unread_count": 150,
    "queue_size": 5,
    "circuit_breaker": "CLOSED",
    "health_warning": null,
    "db_size_mb": 50
  }
```

### Categorias

```
GET /api/categories
  Response: [{ "id": 1, "name": "Tech", "parent_id": null, "unread_count": 50 }, ...]

POST /api/categories
  Body: { "name": "...", "parent_id": null }
  Response: { "id": 1, ... }

PUT /api/categories/:id
  Body: { "name": "...", "parent_id": null }
  Response: { "id": 1, ... }

DELETE /api/categories/:id
  Response: { "ok": true }

PATCH /api/categories/reorder
  Body: [{ "id": 1, "position": 0 }, { "id": 2, "position": 1 }]
  Response: { "ok": true }
```

### Feeds

```
GET /api/feeds
  Query: ?category_id=1&include_disabled=false
  Response: [{ "id": 1, "title": "...", "url": "...", "unread_count": 10, "error_count": 0 }, ...]

POST /api/feeds
  Body: { "url": "...", "category_id": 1 }
  Response: { "id": 1, "title": "..." }

PUT /api/feeds/:id
  Body: { "title": "...", "category_id": 2 }
  Response: { "id": 1, ... }

DELETE /api/feeds/:id
  Response: { "ok": true }

POST /api/feeds/:id/refresh
  Response: { "new_posts": 5, "errors": [] }
  Nota: ignora next_retry_at e tenta imediatamente.
        Se feed estava disabled e refresh sucede, reativa automaticamente.

POST /api/feeds/:id/enable
  Response: { "ok": true }
  Nota: reseta error_count, disabled_at, next_retry_at. Tenta fetch imediato.

POST /api/feeds/import-opml
  Body: multipart/form-data com arquivo OPML
  Response: { "imported": 10, "errors": ["..."] }

GET /api/feeds/export-opml
  Response: application/xml (arquivo OPML)
```

### Posts

```
GET /api/posts
  Query: ?feed_id=1&category_id=1&unread_only=true&search=termo&limit=50&offset=0
  Response: {
    "posts": [{ "id": 1, "title": "...", "one_line_summary": "...", "published_at": "...", "is_read": false }, ...],
    "total": 500,
    "has_more": true
  }

GET /api/posts/:id
  Response: {
    "id": 1,
    "title": "...",
    "content": "...",
    "full_content": "...",
    "summary_pt": "...",
    "summary_status": "ready" | "pending" | "failed",
    ...
  }

PATCH /api/posts/:id/read
  Body: { "is_read": true }
  Response: { "ok": true }

POST /api/posts/mark-read
  Body: { "post_ids": [1, 2, 3] }
    ou { "feed_id": 1 }
    ou { "category_id": 1 }
    ou { "all": true }
  Response: { "marked": 50 }
```

### Proxy

```
GET /api/proxy?url=https://example.com/article
  Response: HTML do artigo (sanitizado)
```

### Admin (protegido)

```
POST /api/admin/reprocess-summary
  Body: { "content_hash": "..." }
  Response: { "ok": true, "queued": true }

POST /api/admin/vacuum
  Response: { "ok": true, "freed_bytes": 1000000 }
```

### Ordenação de Posts

Posts são ordenados por `sort_date DESC` (mais recentes primeiro).

O campo `sort_date` é preenchido no insert:
- `sort_date = published_at` se published_at não for NULL
- `sort_date = fetched_at` caso contrário

Isso simplifica queries e permite índice único para ordenação.

### Paginação

- `limit`: default 50, máximo 200
- `offset`: default 0
- Response inclui `total` e `has_more` para navegação


## Frontend

### Tecnologias

- Alpine.js 3.x (reatividade)
- Tailwind CSS (compilado, não CDN em produção)
- Vanilla JS para utilitários

### Assets

- Sempre locais em produção
- CDN apenas em desenvolvimento (via flag)
- Nenhum document.write, eval, ou inline scripts

### Comportamentos

- Token JWT mantido em variável JavaScript (memória)
- Ao recarregar página: exige login
- Conteúdo completo (full_content) carregado sob demanda ao abrir post
- Indicador visual para resumo pendente: "Gerando resumo..."
- Indicador visual para resumo falho: "Resumo indisponível"
- Alerta visual quando health_warning presente (banner no topo)
- Keyboard shortcuts:
  - j/k: navegar entre posts
  - Enter: abrir post selecionado
  - m: toggle lido/não lido
  - Esc: fechar modal


## Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name rss.sarmento.org;

    # SSL via WordOps (certificados Let's Encrypt)
    # ... configuração SSL ...

    root /var/www/rss.sarmento.org/htdocs;

    client_max_body_size 1m;

    # Buffers para proxy
    proxy_buffering on;
    proxy_buffer_size 4k;
    proxy_buffers 8 16k;

    # Headers de segurança
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # CSP
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https: data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self';" always;

    # Frontend estático
    location / {
        try_files $uri $uri/ /index.html;
        expires 1h;
    }

    # Assets com cache longo
    location /static/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # API backend
    location /api/ {
        proxy_pass http://127.0.0.1:8100;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_read_timeout 60s;
    }
}
```


## Backup

O ambiente WordOps/host é responsável por backups do sistema.

Recomendação: backup diário do diretório `/var/www/rss.sarmento.org/backend/data/` que contém:
- reader.db (banco SQLite)
- app.log (logs da aplicação)

SQLite em modo WAL: para backup consistente, usar `sqlite3 reader.db ".backup backup.db"` ou garantir que não há escritas durante cópia.


## Configuração Completa (.env)

```env
# === Banco de Dados ===
DATABASE_PATH=./data/reader.db

# === Autenticação ===
APP_PASSWORD=sua_senha_segura_aqui
JWT_SECRET=string_aleatoria_minimo_32_caracteres
JWT_EXPIRATION_HOURS=24

# === Cerebras IA ===
CEREBRAS_API_KEY=your_api_key_here
CEREBRAS_MAX_RPM=20
CEREBRAS_TIMEOUT=30

# === Circuit Breaker ===
FAILURE_THRESHOLD=5
RECOVERY_TIMEOUT_SECONDS=300
HALF_OPEN_MAX_REQUESTS=3

# === Rate Limiting HTTP ===
LOGIN_RATE_LIMIT=5
API_RATE_LIMIT=100
FEEDS_REFRESH_RATE_LIMIT=10

# === Retenção ===
MAX_POSTS_PER_FEED=500
MAX_POST_AGE_DAYS=365
MAX_UNREAD_DAYS=90
MAX_DB_SIZE_MB=1024

# === Jobs ===
FEED_UPDATE_INTERVAL_MINUTES=30
SUMMARY_LOCK_TIMEOUT_SECONDS=300
CLEANUP_HOUR=3

# === Proxy ===
PROXY_TIMEOUT_SECONDS=10
PROXY_MAX_SIZE_BYTES=5242880

# === Logging ===
LOG_LEVEL=INFO
LOG_FILE=./data/app.log

# === Segurança ===
CORS_ORIGINS=https://rss.sarmento.org
```


## Dependências (requirements.txt)

```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
sqlalchemy>=2.0.0
alembic>=1.13.0
pydantic-settings>=2.0.0
feedparser>=6.0.0
httpx>=0.26.0
readability-lxml>=0.8.0
lxml>=5.0.0
lxml-html-clean>=0.1.0
bleach>=6.1.0
apscheduler>=3.10.0
python-jose[cryptography]>=3.3.0
python-multipart>=0.0.6
slowapi>=0.1.9
```


## Limitações Assumidas

- Single-user (sem multi-tenancy)
- Sem multi-worker (1 processo uvicorn)
- Sem HA (alta disponibilidade)
- Sem busca full-text avançada (apenas LIKE em título)
- Falhas da IA não bloqueiam o app
- Imagens externas não são cacheadas/proxiadas
- Sem notificações push
- Sem modo offline


## Resultado Esperado

O sistema:
- Não perde estado em restart
- Não duplica jobs
- Não cresce indefinidamente
- Não expõe XSS ou SSRF óbvios
- Tem custo previsível de IA
- É mantível por uma única pessoa
- Degrada graciosamente quando IA falha
- Recupera automaticamente de falhas temporárias
- Fornece visibilidade sobre problemas (health warnings)

