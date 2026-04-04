"""
Recurring transactions router.

Recurring entries auto-generate a real Transaction on each due date.
The scheduler (called from main.py lifespan) calls run_due_recurring()
once at startup; any overdue entries are generated and next_due is
advanced forward to the next period.

Frequency advancement:
  daily       → +1 day
  weekly      → +7 days
  fortnightly → +14 days
  monthly     → +1 calendar month (same day, handles month-end clamping)
  yearly      → +1 calendar year
"""
from datetime import date, timedelta
from typing import List

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_owner

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


# ---------------------------------------------------------------------------
# Scheduling helpers
# ---------------------------------------------------------------------------

def _advance_date(current: date, frequency: str) -> date:
    """Return the next due date after current for a given frequency."""
    if frequency == "daily":
        return current + timedelta(days=1)
    if frequency == "weekly":
        return current + timedelta(weeks=1)
    if frequency == "fortnightly":
        return current + timedelta(weeks=2)
    if frequency == "monthly":
        return current + relativedelta(months=1)
    if frequency == "yearly":
        return current + relativedelta(years=1)
    raise ValueError(f"Unknown frequency: {frequency!r}")


def run_due_recurring(db: Session) -> int:
    """
    Check all active recurring transactions with next_due <= today.
    For each one, generate a Transaction and advance next_due.
    Returns the number of transactions generated.
    """
    today = date.today()
    due = (
        db.query(models.RecurringTransaction)
        .filter(
            models.RecurringTransaction.is_active == True,
            models.RecurringTransaction.next_due <= today,
        )
        .all()
    )

    generated = 0
    for rec in due:
        # Generate one transaction per overdue period
        due_date = rec.next_due
        while due_date <= today:
            # Stop if an end_date is set and we've passed it
            if rec.end_date and due_date > rec.end_date:
                rec.is_active = False
                break

            tx = models.Transaction(
                account_id=rec.account_id,
                date=due_date,
                description=rec.description,
                amount=rec.amount,
                category_id=rec.category_id,
                source="manual",     # recurring entries start as unverified estimates
                is_verified=False,
                notes=f"Auto-generated from recurring: {rec.description}",
            )
            db.add(tx)
            generated += 1

            due_date = _advance_date(due_date, rec.frequency)

        # Advance next_due to the first future date
        rec.next_due = due_date

    if generated:
        db.commit()
    return generated


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[schemas.RecurringTransactionResponse])
def list_recurring(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return (
        db.query(models.RecurringTransaction)
        .options(
            joinedload(models.RecurringTransaction.account),
            joinedload(models.RecurringTransaction.category),
        )
        .order_by(
            models.RecurringTransaction.is_active.desc(),
            models.RecurringTransaction.next_due.asc(),
        )
        .all()
    )


@router.post("", response_model=schemas.RecurringTransactionResponse, status_code=status.HTTP_201_CREATED)
def create_recurring(
    payload: schemas.RecurringTransactionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    account = db.query(models.Account).filter(models.Account.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if payload.category_id:
        if not db.query(models.Category).filter(models.Category.id == payload.category_id).first():
            raise HTTPException(status_code=404, detail="Category not found")

    rec = models.RecurringTransaction(
        user_id=current_user.id,
        next_due=payload.start_date,   # first generation on start_date
        **payload.model_dump(),
    )
    db.add(rec)
    db.commit()
    return _load(db, rec.id)


@router.get("/{rec_id}", response_model=schemas.RecurringTransactionResponse)
def get_recurring(
    rec_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return _load(db, rec_id)


@router.patch("/{rec_id}", response_model=schemas.RecurringTransactionResponse)
def update_recurring(
    rec_id: int,
    payload: schemas.RecurringTransactionUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    rec = _load(db, rec_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rec, field, value)
    db.commit()
    return _load(db, rec_id)


@router.delete("/{rec_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring(
    rec_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    rec = db.query(models.RecurringTransaction).filter(models.RecurringTransaction.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")
    db.delete(rec)
    db.commit()


# ---------------------------------------------------------------------------
# Internal loader
# ---------------------------------------------------------------------------

def _load(db: Session, rec_id: int) -> models.RecurringTransaction:
    rec = (
        db.query(models.RecurringTransaction)
        .options(
            joinedload(models.RecurringTransaction.account),
            joinedload(models.RecurringTransaction.category),
        )
        .filter(models.RecurringTransaction.id == rec_id)
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")
    return rec
