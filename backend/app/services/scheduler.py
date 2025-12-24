"""
Scheduler para background jobs.
Usa lock no banco para garantir apenas uma instância ativa.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import SchedulerLock

logger = logging.getLogger(__name__)

# Configurações
HEARTBEAT_INTERVAL = 30  # segundos
LOCK_TIMEOUT = 60  # segundos - lock expira se heartbeat parar


class Scheduler:
    """Gerenciador de jobs em background com lock distribuído."""

    def __init__(self):
        self.instance_id = str(uuid.uuid4())
        self.is_leader = False
        self._running = False
        self._tasks = []

    async def start(self):
        """Inicia o scheduler."""
        self._running = True
        logger.info(f"Scheduler iniciando (instance_id: {self.instance_id})")

        # Tentar adquirir lock
        await self._try_acquire_lock()

        # Iniciar heartbeat
        asyncio.create_task(self._heartbeat_loop())

        # Se for líder, iniciar jobs
        if self.is_leader:
            await self._start_jobs()

    async def stop(self):
        """Para o scheduler e libera lock."""
        self._running = False
        logger.info("Scheduler parando...")

        # Cancelar tasks
        for task in self._tasks:
            task.cancel()

        # Liberar lock
        if self.is_leader:
            await self._release_lock()

    async def _try_acquire_lock(self) -> bool:
        """
        Tenta adquirir lock de líder.
        Usa INSERT OR REPLACE com verificação de heartbeat expirado.
        """
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            timeout = now - timedelta(seconds=LOCK_TIMEOUT)

            # Verificar lock existente
            existing = db.query(SchedulerLock).filter(SchedulerLock.id == 1).first()

            if existing:
                # Verificar se expirou
                if existing.heartbeat_at < timeout:
                    logger.info(
                        f"Lock expirado (último heartbeat: {existing.heartbeat_at}). "
                        f"Adquirindo..."
                    )
                    existing.locked_by = self.instance_id
                    existing.locked_at = now
                    existing.heartbeat_at = now
                    db.commit()
                    self.is_leader = True
                elif existing.locked_by == self.instance_id:
                    # Já somos o líder
                    self.is_leader = True
                else:
                    # Outro processo é líder
                    logger.info(
                        f"Outra instância é líder: {existing.locked_by}"
                    )
                    self.is_leader = False
            else:
                # Criar lock
                lock = SchedulerLock(
                    id=1,
                    locked_by=self.instance_id,
                    locked_at=now,
                    heartbeat_at=now,
                )
                db.add(lock)
                db.commit()
                self.is_leader = True

            if self.is_leader:
                logger.info(f"Lock adquirido. Esta instância é o líder.")

            return self.is_leader

        except Exception as e:
            logger.error(f"Erro ao adquirir lock: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    async def _release_lock(self):
        """Libera lock de líder."""
        db = SessionLocal()
        try:
            db.query(SchedulerLock).filter(
                SchedulerLock.id == 1,
                SchedulerLock.locked_by == self.instance_id
            ).delete()
            db.commit()
            logger.info("Lock liberado")
        except Exception as e:
            logger.error(f"Erro ao liberar lock: {e}")
            db.rollback()
        finally:
            db.close()

    async def _heartbeat_loop(self):
        """Loop de heartbeat para manter lock ativo."""
        while self._running:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                if not self._running:
                    break

                if self.is_leader:
                    await self._update_heartbeat()
                else:
                    # Tentar adquirir lock se não for líder
                    await self._try_acquire_lock()
                    if self.is_leader:
                        await self._start_jobs()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no heartbeat: {e}")

    async def _update_heartbeat(self):
        """Atualiza heartbeat do lock."""
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            result = db.query(SchedulerLock).filter(
                SchedulerLock.id == 1,
                SchedulerLock.locked_by == self.instance_id
            ).update({"heartbeat_at": now})

            if result == 0:
                # Perdemos o lock
                logger.warning("Lock perdido! Outra instância assumiu.")
                self.is_leader = False
                # Cancelar jobs
                for task in self._tasks:
                    task.cancel()
                self._tasks = []
            else:
                db.commit()

        except Exception as e:
            logger.error(f"Erro ao atualizar heartbeat: {e}")
            db.rollback()
        finally:
            db.close()

    async def _start_jobs(self):
        """Inicia todos os jobs em background."""
        logger.info("Iniciando jobs...")

        # Job: update_feeds (a cada 30 minutos)
        self._tasks.append(
            asyncio.create_task(self._job_update_feeds())
        )

        # Job: cleanup_retention (diário às 03:00)
        self._tasks.append(
            asyncio.create_task(self._job_cleanup_retention())
        )

        # Job: health_check (a cada 5 minutos)
        self._tasks.append(
            asyncio.create_task(self._job_health_check())
        )

        # Job: process_summaries (a cada 1 minuto)
        self._tasks.append(
            asyncio.create_task(self._job_process_summaries())
        )

    async def _job_update_feeds(self):
        """Job para atualizar feeds periodicamente."""
        from app.services.feed_ingestion import ingest_feed
        from app.models import Feed

        interval = settings.feed_update_interval_minutes * 60

        while self._running and self.is_leader:
            try:
                logger.info("Job update_feeds: iniciando...")

                db = SessionLocal()
                try:
                    now = datetime.utcnow()

                    # Buscar feeds elegíveis
                    feeds = (
                        db.query(Feed)
                        .filter(
                            Feed.disabled_at.is_(None),
                            (Feed.next_retry_at.is_(None)) | (Feed.next_retry_at <= now)
                        )
                        .order_by(Feed.error_count.asc())  # Priorizar feeds sem erro
                        .limit(20)
                        .all()
                    )

                    logger.info(f"Job update_feeds: {len(feeds)} feeds para atualizar")

                    for feed in feeds:
                        if not self._running or not self.is_leader:
                            break

                        try:
                            result = await ingest_feed(db, feed)
                            logger.info(
                                f"Feed {feed.id} atualizado: "
                                f"{result.new_posts} novos, "
                                f"{result.skipped_duplicates} duplicados"
                            )
                        except Exception as e:
                            logger.error(f"Erro ao atualizar feed {feed.id}: {e}")

                        # Pequeno delay entre feeds
                        await asyncio.sleep(1)

                finally:
                    db.close()

                logger.info("Job update_feeds: concluído")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no job update_feeds: {e}")

            # Aguardar próximo ciclo
            await asyncio.sleep(interval)

    async def _job_cleanup_retention(self):
        """Job para limpeza de posts antigos."""
        from app.models import Post, CleanupLog

        while self._running and self.is_leader:
            try:
                now = datetime.utcnow()

                # Verificar se é hora de rodar (03:00)
                target_hour = settings.cleanup_hour
                if now.hour != target_hour:
                    # Calcular tempo até próxima execução
                    next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
                    if now.hour >= target_hour:
                        next_run += timedelta(days=1)
                    wait_seconds = (next_run - now).total_seconds()
                    await asyncio.sleep(min(wait_seconds, 3600))  # Max 1h de espera
                    continue

                logger.info("Job cleanup_retention: iniciando...")

                db = SessionLocal()
                start_time = datetime.utcnow()

                try:
                    posts_removed = 0
                    full_content_cleared = 0
                    unread_removed = 0

                    # 1. Remover posts lidos há mais de MAX_POST_AGE_DAYS
                    # (exceto favoritos que nunca são removidos)
                    cutoff_read = now - timedelta(days=settings.max_post_age_days)
                    result = db.query(Post).filter(
                        Post.is_read == True,
                        Post.read_at < cutoff_read,
                        (Post.is_starred == False) | (Post.is_starred.is_(None))
                    ).delete(synchronize_session=False)
                    posts_removed += result

                    # 2. Remover posts não lidos há mais de MAX_UNREAD_DAYS
                    # (exceto favoritos que nunca são removidos)
                    cutoff_unread = now - timedelta(days=settings.max_unread_days)
                    result = db.query(Post).filter(
                        Post.is_read == False,
                        Post.fetched_at < cutoff_unread,
                        (Post.is_starred == False) | (Post.is_starred.is_(None))
                    ).delete(synchronize_session=False)
                    unread_removed += result

                    # 3. Limpar full_content de posts lidos há mais de 30 dias
                    # (exceto favoritos que mantêm conteúdo)
                    cutoff_full = now - timedelta(days=30)
                    result = db.query(Post).filter(
                        Post.is_read == True,
                        Post.read_at < cutoff_full,
                        Post.full_content.isnot(None),
                        (Post.is_starred == False) | (Post.is_starred.is_(None))
                    ).update({"full_content": None}, synchronize_session=False)
                    full_content_cleared += result

                    db.commit()

                    # Registrar em cleanup_logs
                    duration = (datetime.utcnow() - start_time).total_seconds()
                    log = CleanupLog(
                        posts_removed=posts_removed,
                        full_content_cleared=full_content_cleared,
                        unread_removed=unread_removed,
                        duration_seconds=duration,
                    )
                    db.add(log)
                    db.commit()

                    logger.info(
                        f"Job cleanup_retention: concluído em {duration:.1f}s - "
                        f"posts removidos: {posts_removed}, "
                        f"unread removidos: {unread_removed}, "
                        f"full_content limpos: {full_content_cleared}"
                    )

                except Exception as e:
                    db.rollback()
                    raise
                finally:
                    db.close()

                # Aguardar próximo dia
                await asyncio.sleep(3600)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no job cleanup_retention: {e}")
                await asyncio.sleep(3600)

    async def _job_health_check(self):
        """Job para verificar saúde do sistema."""
        from app.models import AppSettings
        import os

        interval = 300  # 5 minutos

        while self._running and self.is_leader:
            try:
                logger.debug("Job health_check: verificando...")

                db = SessionLocal()
                warnings = []

                try:
                    # 1. Verificar SELECT 1
                    db.execute(text("SELECT 1"))

                    # 2. Verificar espaço em disco
                    statvfs = os.statvfs(".")
                    free_mb = (statvfs.f_frsize * statvfs.f_bavail) / (1024 * 1024)
                    if free_mb < 100:
                        warnings.append(f"Espaço em disco baixo: {free_mb:.0f}MB")

                    # 3. Verificar tamanho do banco
                    db_path = settings.database_path
                    if os.path.exists(db_path):
                        db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
                        if db_size_mb > settings.max_db_size_mb:
                            warnings.append(f"Banco muito grande: {db_size_mb:.0f}MB")

                    # Atualizar app_settings
                    if warnings:
                        warning_text = "; ".join(warnings)
                        logger.warning(f"Health check warnings: {warning_text}")
                        existing = db.query(AppSettings).filter(
                            AppSettings.key == "health_warning"
                        ).first()
                        if existing:
                            existing.value = warning_text
                        else:
                            db.add(AppSettings(key="health_warning", value=warning_text))
                    else:
                        db.query(AppSettings).filter(
                            AppSettings.key == "health_warning"
                        ).delete()

                    db.commit()

                except Exception as e:
                    db.rollback()
                    logger.error(f"Health check falhou: {e}")
                finally:
                    db.close()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no job health_check: {e}")

            await asyncio.sleep(interval)

    async def _job_process_summaries(self):
        """Job para processar fila de resumos IA."""
        from app.models import SummaryQueue, AISummary, SummaryFailure, Post
        from app.services.cerebras import (
            generate_summary,
            circuit_breaker,
            TemporaryError,
            PermanentError,
        )
        from app.services.content_extractor import extract_full_content

        # Intervalo baseado no rate limit (com margem de segurança)
        interval = max(5, 60 // settings.cerebras_max_rpm + 1)

        while self._running and self.is_leader:
            try:
                # Verificar se pode chamar API
                can_call, reason = circuit_breaker.can_call()
                if not can_call:
                    logger.debug(f"Job process_summaries: {reason}")
                    await asyncio.sleep(interval)
                    continue

                db = SessionLocal()
                try:
                    now = datetime.utcnow()
                    lock_timeout = now - timedelta(seconds=settings.summary_lock_timeout_seconds)

                    # Buscar próximo item elegível
                    candidate = (
                        db.query(SummaryQueue)
                        .filter(
                            (SummaryQueue.locked_at.is_(None)) | (SummaryQueue.locked_at < lock_timeout),
                            (SummaryQueue.cooldown_until.is_(None)) | (SummaryQueue.cooldown_until < now),
                        )
                        .order_by(SummaryQueue.priority.desc(), SummaryQueue.created_at.asc())
                        .first()
                    )

                    if not candidate:
                        logger.debug("Job process_summaries: fila vazia")
                        await asyncio.sleep(interval)
                        continue

                    # Tentar adquirir lock atomicamente
                    result = db.query(SummaryQueue).filter(
                        SummaryQueue.id == candidate.id,
                        (SummaryQueue.locked_at.is_(None)) | (SummaryQueue.locked_at < lock_timeout),
                    ).update({"locked_at": now})

                    if result == 0:
                        # Outro worker pegou
                        db.rollback()
                        continue

                    db.commit()

                    # Verificar se resumo já existe para este hash
                    existing_summary = db.query(AISummary).filter(
                        AISummary.content_hash == candidate.content_hash
                    ).first()

                    if existing_summary:
                        # Resumo já existe, remover da fila
                        db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
                        db.commit()
                        logger.debug(f"Resumo já existe para hash {candidate.content_hash[:16]}...")
                        continue

                    # Buscar post para obter conteúdo
                    post = db.query(Post).filter(Post.id == candidate.post_id).first()
                    if not post:
                        # Post foi deletado, remover da fila
                        db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
                        db.commit()
                        continue

                    # Pular posts já lidos (não vale gastar API com eles)
                    if post.is_read:
                        db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
                        db.commit()
                        logger.debug(f"Post {post.id} já lido, pulando resumo")
                        continue

                    # Buscar full_content se não disponível
                    content = post.full_content
                    if not content and post.url:
                        try:
                            logger.info(f"Buscando conteúdo completo para post {post.id}...")
                            result = await extract_full_content(post.url)
                            if result.success and result.content:
                                content = result.content
                                post.full_content = content
                                db.commit()
                                logger.info(f"Conteúdo completo salvo para post {post.id}")
                            # Delay para evitar rate limit (429)
                            await asyncio.sleep(2)
                        except Exception as e:
                            logger.warning(f"Falha ao extrair conteúdo do post {post.id}: {e}")

                    # Fallback para content do RSS
                    if not content:
                        content = post.content

                    if not content:
                        # Sem conteúdo, remover da fila
                        db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
                        db.commit()
                        continue

                    # Chamar API
                    try:
                        logger.info(f"Gerando resumo para post {post.id}...")
                        summary_result = await generate_summary(content)

                        # Salvar resumo
                        ai_summary = AISummary(
                            content_hash=candidate.content_hash,
                            summary_pt=summary_result.summary_pt,
                            one_line_summary=summary_result.one_line_summary,
                        )
                        db.add(ai_summary)

                        # Remover da fila
                        db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
                        db.commit()

                        logger.info(f"Resumo gerado com sucesso para post {post.id}")

                    except TemporaryError as e:
                        # Erro temporário - incrementar attempts
                        candidate.attempts = (candidate.attempts or 0) + 1
                        candidate.last_error = str(e)
                        candidate.error_type = 'temporary'

                        if candidate.attempts >= 5:
                            # Cooldown de 24h
                            candidate.cooldown_until = now + timedelta(hours=24)
                            candidate.attempts = 0
                            logger.warning(f"Post {post.id}: 5 erros, cooldown 24h")

                        candidate.locked_at = None
                        db.commit()
                        logger.warning(f"Erro temporário post {post.id}: {e}")

                    except PermanentError as e:
                        # Erro permanente
                        candidate.attempts = (candidate.attempts or 0) + 1
                        candidate.last_error = str(e)
                        candidate.error_type = 'permanent'

                        if candidate.attempts >= 5:
                            # Mover para failures
                            failure = SummaryFailure(
                                content_hash=candidate.content_hash,
                                last_error=str(e),
                            )
                            db.add(failure)
                            db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
                            logger.error(f"Post {post.id}: falha permanente após 5 tentativas")
                        else:
                            candidate.locked_at = None

                        db.commit()
                        logger.error(f"Erro permanente post {post.id}: {e}")

                except Exception as e:
                    db.rollback()
                    logger.error(f"Erro no job process_summaries: {e}")
                finally:
                    db.close()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no job process_summaries: {e}")

            await asyncio.sleep(interval)


# Instância global
scheduler = Scheduler()
