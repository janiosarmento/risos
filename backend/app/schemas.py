"""
Schemas Pydantic para validação de requests/responses.
"""
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List


# === Autenticação ===

class LoginRequest(BaseModel):
    """Request para login"""
    password: str


class LoginResponse(BaseModel):
    """Response do login com token JWT"""
    token: str
    expires_at: datetime


class UserInfo(BaseModel):
    """Informações do usuário autenticado"""
    authenticated: bool


# === Categorias ===

class CategoryCreate(BaseModel):
    """Request para criar categoria"""
    name: str
    parent_id: Optional[int] = None
    position: Optional[int] = 0


class CategoryUpdate(BaseModel):
    """Request para atualizar categoria"""
    name: Optional[str] = None
    parent_id: Optional[int] = None
    position: Optional[int] = None


class CategoryResponse(BaseModel):
    """Response de categoria"""
    id: int
    name: str
    parent_id: Optional[int]
    position: int
    created_at: datetime
    feed_count: Optional[int] = 0

    model_config = ConfigDict(from_attributes=True)


class CategoryReorder(BaseModel):
    """Request para reordenar categorias"""
    order: List[int]  # Lista de IDs na nova ordem


# === Feeds ===

class FeedCreate(BaseModel):
    """Request para criar feed"""
    url: str
    title: Optional[str] = None
    category_id: Optional[int] = None


class FeedUpdate(BaseModel):
    """Request para atualizar feed"""
    title: Optional[str] = None
    url: Optional[str] = None
    category_id: Optional[int] = None


class FeedResponse(BaseModel):
    """Response de feed"""
    id: int
    category_id: Optional[int]
    title: str
    url: str
    site_url: Optional[str]
    last_fetched_at: Optional[datetime]
    error_count: int
    last_error: Optional[str]
    disabled_at: Optional[datetime]
    created_at: datetime
    unread_count: Optional[int] = 0

    model_config = ConfigDict(from_attributes=True)


# === Posts ===

class PostResponse(BaseModel):
    """Response de post"""
    id: int
    feed_id: int
    guid: Optional[str]
    url: Optional[str]
    title: Optional[str]
    author: Optional[str]
    content: Optional[str]
    published_at: Optional[datetime]
    fetched_at: datetime
    sort_date: datetime
    is_read: bool
    read_at: Optional[datetime]
    is_starred: bool = False
    starred_at: Optional[datetime] = None
    summary_status: str = "not_configured"  # not_configured, pending, ready, failed
    one_line_summary: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PostDetail(PostResponse):
    """Response de post com conteúdo completo"""
    full_content: Optional[str]
    summary_pt: Optional[str] = None
    one_line_summary: Optional[str] = None


class PostListResponse(BaseModel):
    """Response de listagem de posts com paginação"""
    posts: List[PostResponse]
    total: int
    has_more: bool


class MarkReadRequest(BaseModel):
    """Request para marcar posts como lidos em lote"""
    feed_id: Optional[int] = None
    category_id: Optional[int] = None
    post_ids: Optional[List[int]] = None
    all: Optional[bool] = False
