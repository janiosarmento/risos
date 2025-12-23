"""
Modelos ORM do banco de dados.
Schema completo conforme PROJETO.md
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey, CheckConstraint, Float, Index
)
from sqlalchemy.orm import relationship

from app.database import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"))
    position = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relacionamentos
    feeds = relationship("Feed", back_populates="category")


class Feed(Base):
    __tablename__ = "feeds"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"))
    title = Column(Text, nullable=False)
    url = Column(Text, unique=True, nullable=False)
    site_url = Column(Text)
    last_fetched_at = Column(DateTime)

    # Tratamento de erros
    error_count = Column(Integer, default=0)
    last_error = Column(Text)
    last_error_at = Column(DateTime)
    next_retry_at = Column(DateTime)
    disabled_at = Column(DateTime)
    disable_reason = Column(Text)

    # Detecção de GUID instável
    guid_unreliable = Column(Boolean, default=False)
    guid_collision_count = Column(Integer, default=0)

    # Bypass de deduplicação por URL
    allow_duplicate_urls = Column(Boolean, default=False)

    # Metadados
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relacionamentos
    category = relationship("Category", back_populates="feeds")
    posts = relationship("Post", back_populates="feed", cascade="all, delete-orphan")


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True)
    feed_id = Column(Integer, ForeignKey("feeds.id", ondelete="CASCADE"), nullable=False)
    guid = Column(Text)
    url = Column(Text)
    normalized_url = Column(Text)
    title = Column(Text)
    author = Column(Text)
    content = Column(Text)  # Resumo até 500 chars
    full_content = Column(Text)  # Conteúdo completo (sob demanda)
    content_hash = Column(Text)
    published_at = Column(DateTime)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    sort_date = Column(DateTime)  # published_at ou fetched_at
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime)
    is_starred = Column(Boolean, default=False)
    starred_at = Column(DateTime)
    fetch_full_attempted_at = Column(DateTime)

    # Relacionamentos
    feed = relationship("Feed", back_populates="posts")
    summary_queue_entry = relationship("SummaryQueue", back_populates="post", cascade="all, delete-orphan")


# Índices para Post (parciais para deduplicação)
Index("idx_posts_guid", Post.feed_id, Post.guid, unique=True, sqlite_where=Post.guid.isnot(None))
Index("idx_posts_url", Post.feed_id, Post.normalized_url, unique=True, sqlite_where=Post.normalized_url.isnot(None))
Index("idx_posts_content_hash", Post.feed_id, Post.content_hash, unique=True,
      sqlite_where=(Post.content_hash.isnot(None) & Post.guid.is_(None) & Post.normalized_url.is_(None)))
Index("idx_posts_feed", Post.feed_id)
Index("idx_posts_read", Post.is_read)
Index("idx_posts_sort", Post.sort_date.desc())
Index("idx_posts_hash", Post.content_hash)
Index("idx_posts_read_at", Post.read_at, sqlite_where=Post.is_read == True)
Index("idx_posts_starred", Post.is_starred, sqlite_where=Post.is_starred == True)


class AISummary(Base):
    __tablename__ = "ai_summaries"

    id = Column(Integer, primary_key=True)
    content_hash = Column(Text, unique=True, nullable=False)
    summary_pt = Column(Text, nullable=False)
    one_line_summary = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SummaryQueue(Base):
    __tablename__ = "summary_queue"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), unique=True, nullable=False)
    content_hash = Column(Text, nullable=False)
    priority = Column(Integer, default=0)  # 0=background, 10=usuário abriu
    attempts = Column(Integer, default=0)
    last_error = Column(Text)
    error_type = Column(Text)  # 'temporary' ou 'permanent'
    locked_at = Column(DateTime)
    cooldown_until = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relacionamentos
    post = relationship("Post", back_populates="summary_queue_entry")


Index("idx_queue_priority", SummaryQueue.priority.desc(), SummaryQueue.created_at)
Index("idx_queue_pending", SummaryQueue.locked_at, SummaryQueue.cooldown_until)


class SummaryFailure(Base):
    __tablename__ = "summary_failures"

    id = Column(Integer, primary_key=True)
    content_hash = Column(Text, nullable=False)
    last_error = Column(Text)
    failed_at = Column(DateTime, default=datetime.utcnow)


Index("idx_failures_hash", SummaryFailure.content_hash)


class AppSettings(Base):
    __tablename__ = "app_settings"

    key = Column(Text, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    jti = Column(Text, primary_key=True)
    expires_at = Column(DateTime, nullable=False)


Index("idx_blacklist_expires", TokenBlacklist.expires_at)


class SchedulerLock(Base):
    __tablename__ = "scheduler_lock"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row_check"),
    )

    id = Column(Integer, primary_key=True)
    locked_by = Column(Text, nullable=False)
    locked_at = Column(DateTime, nullable=False)
    heartbeat_at = Column(DateTime, nullable=False)


class CleanupLog(Base):
    __tablename__ = "cleanup_logs"

    id = Column(Integer, primary_key=True)
    executed_at = Column(DateTime, default=datetime.utcnow)
    posts_removed = Column(Integer, default=0)
    full_content_cleared = Column(Integer, default=0)
    summaries_cleared = Column(Integer, default=0)
    unread_removed = Column(Integer, default=0)
    bytes_freed = Column(Integer, default=0)
    duration_seconds = Column(Float)
    notes = Column(Text)


Index("idx_cleanup_executed", CleanupLog.executed_at.desc())
