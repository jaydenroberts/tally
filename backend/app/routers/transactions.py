from typing import List, Optional
from datetime import date as date_type
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_owner

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("", response_model=List[schemas.TransactionResponse])
def list_transactions(
    account_id: Optional[int] = Query(None),
    category_id: Optional[int] = Query(None),
    is_verified: Optional[bool] = Query(None),
    source: Optional[str] = Query(None, description="'manual' or 'import'"),
    date_from: Optional[date_type] = Query(None),
    date_to: Optional[date_type] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.Transaction).options(
        joinedload(models.Transaction.category)
    )
    if account_id is not None:
        q = q.filter(models.Transaction.account_id == account_id)
    if category_id is not None:
        q = q.filter(models.Transaction.category_id == category_id)
    if is_verified is not None:
        q = q.filter(models.Transaction.is_verified == is_verified)
    if source is not None:
        q = q.filter(models.Transaction.source == source)
    if date_from is not None:
        q = q.filter(models.Transaction.date >= date_from)
    if date_to is not None:
        q = q.filter(models.Transaction.date <= date_to)
    return q.order_by(models.Transaction.date.desc()).offset(skip).limit(limit).all()


@router.get("/count")
def count_transactions(
    account_id: Optional[int] = Query(None),
    category_id: Optional[int] = Query(None),
    is_verified: Optional[bool] = Query(None),
    source: Optional[str] = Query(None),
    date_from: Optional[date_type] = Query(None),
    date_to: Optional[date_type] = Query(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.Transaction)
    if account_id is not None:
        q = q.filter(models.Transaction.account_id == account_id)
    if category_id is not None:
        q = q.filter(models.Transaction.category_id == category_id)
    if is_verified is not None:
        q = q.filter(models.Transaction.is_verified == is_verified)
    if source is not None:
        q = q.filter(models.Transaction.source == source)
    if date_from is not None:
        q = q.filter(models.Transaction.date >= date_from)
    if date_to is not None:
        q = q.filter(models.Transaction.date <= date_to)
    return {"count": q.count()}


@router.post("", response_model=schemas.TransactionResponse, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: schemas.TransactionCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    account = db.query(models.Account).filter(models.Account.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    tx = models.Transaction(
        **payload.model_dump(),
        source="manual",      # manual entries are always estimates
        is_verified=False,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


@router.delete("/bulk", status_code=status.HTTP_204_NO_CONTENT)
def bulk_delete_transactions(
    ids: List[int] = Query(..., description="List of transaction IDs to delete"),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """Delete multiple transactions by ID. Owner-only. Silently skips IDs that don't exist."""
    db.query(models.Transaction).filter(models.Transaction.id.in_(ids)).delete(synchronize_session=False)
    db.commit()


@router.get("/{tx_id}", response_model=schemas.TransactionResponse)
def get_transaction(
    tx_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    tx = db.query(models.Transaction).options(
        joinedload(models.Transaction.category)
    ).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return tx


@router.patch("/{tx_id}", response_model=schemas.TransactionResponse)
def update_transaction(
    tx_id: int,
    payload: schemas.TransactionUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    tx = db.query(models.Transaction).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    # Do not allow editing verified (imported) transactions — they are source of truth
    if tx.is_verified and tx.source == "import":
        raise HTTPException(
            status_code=400,
            detail="Imported (verified) transactions cannot be edited. Delete and re-import if needed.",
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tx, field, value)
    db.commit()
    db.refresh(tx)
    return tx


@router.delete("/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    tx_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    tx = db.query(models.Transaction).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.delete(tx)
    db.commit()
