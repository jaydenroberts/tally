from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_owner

router = APIRouter(prefix="/api/categories", tags=["categories"])

DEFAULT_CATEGORIES = [
    {"name": "Housing", "color": "#a1efe4", "icon": "home"},
    {"name": "Food & Dining", "color": "#00f769", "icon": "utensils"},
    {"name": "Transport", "color": "#ea51b2", "icon": "car"},
    {"name": "Health", "color": "#f7f7fb", "icon": "heart"},
    {"name": "Entertainment", "color": "#a1efe4", "icon": "tv"},
    {"name": "Shopping", "color": "#ea51b2", "icon": "shopping-bag"},
    {"name": "Savings", "color": "#00f769", "icon": "piggy-bank"},
    {"name": "Income", "color": "#00f769", "icon": "trending-up"},
    {"name": "Utilities", "color": "#a1efe4", "icon": "zap"},
    {"name": "Insurance", "color": "#f7f7fb", "icon": "shield"},
    {"name": "Debt Payment", "color": "#ea51b2", "icon": "credit-card"},
    {"name": "Other", "color": "#f7f7fb", "icon": "more-horizontal"},
]


@router.get("", response_model=List[schemas.CategoryResponse])
def list_categories(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Return system categories + categories owned by the current user
    return db.query(models.Category).filter(
        (models.Category.user_id == None) | (models.Category.user_id == current_user.id)
    ).all()


@router.post("", response_model=schemas.CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    if payload.parent_id:
        parent = db.query(models.Category).filter(models.Category.id == payload.parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent category not found")
    category = models.Category(user_id=current_user.id, **payload.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.patch("/{category_id}", response_model=schemas.CategoryResponse)
def update_category(
    category_id: int,
    payload: schemas.CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    if category.is_system:
        raise HTTPException(status_code=400, detail="System categories cannot be modified")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    if category.is_system:
        raise HTTPException(status_code=400, detail="System categories cannot be deleted")
    db.delete(category)
    db.commit()
