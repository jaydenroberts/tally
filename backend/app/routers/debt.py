from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_owner

router = APIRouter(prefix="/api/debt", tags=["debt"])


def _load_debt(db: Session, debt_id: int) -> models.Debt:
    debt = (
        db.query(models.Debt)
        .options(joinedload(models.Debt.linked_account))
        .filter(models.Debt.id == debt_id)
        .first()
    )
    if not debt:
        raise HTTPException(status_code=404, detail="Debt not found")
    return debt


@router.get("", response_model=List[schemas.DebtResponse])
def list_debts(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Debt)
        .options(joinedload(models.Debt.linked_account))
        # Active debts first, then paid off; within active: highest interest rate first
        .order_by(
            models.Debt.is_paid_off,
            models.Debt.interest_rate.desc().nulls_last(),
        )
        .all()
    )


@router.post("", response_model=schemas.DebtResponse, status_code=status.HTTP_201_CREATED)
def create_debt(
    payload: schemas.DebtCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    if payload.linked_account_id:
        account = db.query(models.Account).filter(
            models.Account.id == payload.linked_account_id
        ).first()
        if not account:
            raise HTTPException(status_code=404, detail="Linked account not found")
    debt = models.Debt(user_id=current_user.id, **payload.model_dump())
    db.add(debt)
    db.commit()
    return _load_debt(db, debt.id)


@router.get("/{debt_id}", response_model=schemas.DebtResponse)
def get_debt(
    debt_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return _load_debt(db, debt_id)


@router.patch("/{debt_id}", response_model=schemas.DebtResponse)
def update_debt(
    debt_id: int,
    payload: schemas.DebtUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    debt = _load_debt(db, debt_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(debt, field, value)
    if debt.current_balance <= 0:
        debt.is_paid_off = True
    db.commit()
    return _load_debt(db, debt_id)


@router.post("/{debt_id}/payment", response_model=schemas.DebtResponse)
def log_payment(
    debt_id: int,
    payload: schemas.PaymentRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Log a payment against a debt. Reduces current_balance by the payment amount.
    Records an immutable DebtPayment entry for audit history.
    Auto-marks the debt as paid off if balance reaches zero.
    """
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be positive")

    debt = _load_debt(db, debt_id)
    if debt.is_paid_off:
        raise HTTPException(status_code=400, detail="Debt is already paid off")

    new_balance = round(max(0.0, debt.current_balance - payload.amount), 2)
    debt.current_balance = new_balance
    if new_balance == 0:
        debt.is_paid_off = True

    # Record the payment in the audit trail
    payment_record = models.DebtPayment(
        debt_id=debt_id,
        amount=payload.amount,
        balance_after=new_balance,
        notes=payload.notes,
    )
    db.add(payment_record)
    db.commit()
    return _load_debt(db, debt_id)


@router.get("/{debt_id}/payments", response_model=List[schemas.DebtPaymentResponse])
def list_payments(
    debt_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Return all recorded payments for a debt, most recent first."""
    # Confirm the debt exists
    if not db.query(models.Debt).filter(models.Debt.id == debt_id).first():
        raise HTTPException(status_code=404, detail="Debt not found")
    return (
        db.query(models.DebtPayment)
        .filter(models.DebtPayment.debt_id == debt_id)
        .order_by(models.DebtPayment.paid_at.desc())
        .all()
    )


@router.delete("/{debt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_debt(
    debt_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    debt = db.query(models.Debt).filter(models.Debt.id == debt_id).first()
    if not debt:
        raise HTTPException(status_code=404, detail="Debt not found")
    db.delete(debt)
    db.commit()
