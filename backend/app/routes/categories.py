"""
Rotas de categorias.
CRUD completo + reordenação.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Category, Feed
from app.schemas import (
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
    CategoryReorder,
)

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=List[CategoryResponse])
def list_categories(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """Lista todas as categorias ordenadas por posição."""
    # Subquery para contar feeds por categoria
    feed_count_subq = (
        db.query(Feed.category_id, func.count(Feed.id).label("feed_count"))
        .group_by(Feed.category_id)
        .subquery()
    )

    categories = (
        db.query(Category, func.coalesce(feed_count_subq.c.feed_count, 0).label("feed_count"))
        .outerjoin(feed_count_subq, Category.id == feed_count_subq.c.category_id)
        .order_by(func.lower(Category.name))
        .all()
    )

    result = []
    for cat, feed_count in categories:
        cat_dict = {
            "id": cat.id,
            "name": cat.name,
            "parent_id": cat.parent_id,
            "position": cat.position or 0,
            "created_at": cat.created_at,
            "feed_count": feed_count,
        }
        result.append(CategoryResponse(**cat_dict))

    return result


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    category: CategoryCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """Cria uma nova categoria."""
    # Verificar se parent_id existe (se fornecido)
    if category.parent_id:
        parent = db.query(Category).filter(Category.id == category.parent_id).first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent category not found"
            )

    db_category = Category(
        name=category.name,
        parent_id=category.parent_id,
        position=category.position or 0,
    )
    db.add(db_category)
    db.commit()
    db.refresh(db_category)

    return CategoryResponse(
        id=db_category.id,
        name=db_category.name,
        parent_id=db_category.parent_id,
        position=db_category.position or 0,
        created_at=db_category.created_at,
        feed_count=0,
    )


@router.get("/{category_id}", response_model=CategoryResponse)
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """Busca uma categoria por ID."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )

    feed_count = db.query(func.count(Feed.id)).filter(Feed.category_id == category_id).scalar()

    return CategoryResponse(
        id=category.id,
        name=category.name,
        parent_id=category.parent_id,
        position=category.position or 0,
        created_at=category.created_at,
        feed_count=feed_count,
    )


@router.put("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: int,
    category_update: CategoryUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """Atualiza uma categoria."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )

    # Verificar parent_id (se fornecido e diferente)
    if category_update.parent_id is not None and category_update.parent_id != category.parent_id:
        if category_update.parent_id == category_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category cannot be its own parent"
            )
        if category_update.parent_id != 0:  # 0 significa remover parent
            parent = db.query(Category).filter(Category.id == category_update.parent_id).first()
            if not parent:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Parent category not found"
                )

    # Atualizar campos
    if category_update.name is not None:
        category.name = category_update.name
    if category_update.parent_id is not None:
        category.parent_id = category_update.parent_id if category_update.parent_id != 0 else None
    if category_update.position is not None:
        category.position = category_update.position

    db.commit()
    db.refresh(category)

    feed_count = db.query(func.count(Feed.id)).filter(Feed.category_id == category_id).scalar()

    return CategoryResponse(
        id=category.id,
        name=category.name,
        parent_id=category.parent_id,
        position=category.position or 0,
        created_at=category.created_at,
        feed_count=feed_count,
    )


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Deleta uma categoria.
    Feeds da categoria terão category_id setado para NULL.
    """
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )

    # Feeds terão category_id = NULL devido ao ON DELETE SET NULL
    db.delete(category)
    db.commit()

    return None


@router.patch("/reorder", response_model=List[CategoryResponse])
def reorder_categories(
    reorder: CategoryReorder,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Reordena categorias.
    Recebe lista de IDs na nova ordem.
    """
    # Verificar se todos os IDs existem
    existing_ids = set(
        id for (id,) in db.query(Category.id).filter(Category.id.in_(reorder.order)).all()
    )

    if len(existing_ids) != len(reorder.order):
        missing = set(reorder.order) - existing_ids
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Categories not found: {missing}"
        )

    # Atualizar posições
    for position, category_id in enumerate(reorder.order):
        db.query(Category).filter(Category.id == category_id).update({"position": position})

    db.commit()

    # Retornar lista atualizada
    return list_categories(db=db, user=user)
