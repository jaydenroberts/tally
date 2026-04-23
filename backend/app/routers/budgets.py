import calendar
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_owner

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


@router.get("/summary", response_model=List[schemas.BudgetStatus])
def budget_summary(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """
    Return all active budgets with live spending breakdown for a given month.
    Both verified and unverified (estimate) transactions are included so the
    real-time household picture is always visible.
    """
    first_day = date(year, month, 1)
    last_day  = date(year, month, calendar.monthrange(year, month)[1])

    budgets = (
        db.query(models.Budget)
        .options(joinedload(models.Budget.category))
        .filter(
            models.Budget.is_active == True,
            models.Budget.start_date <= last_day,
            or_(models.Budget.end_date == None, models.Budget.end_date >= first_day),
        )
        .all()
    )

    results = []
    for budget in budgets:
        # Verified spend in this category this month.
        # Debt payments are excluded — they reduce a liability, not a spending category.
        # NULL transaction_type is treated as "expense" (legacy rows pre-dating the column).
        verified_raw = (
            db.query(func.sum(models.Transaction.amount))
            .filter(
                models.Transaction.category_id == budget.category_id,
                models.Transaction.date >= first_day,
                models.Transaction.date <= last_day,
                models.Transaction.is_verified == True,
                or_(
                    models.Transaction.transaction_type == "expense",
                    models.Transaction.transaction_type == None,
                ),
            )
            .scalar()
        ) or 0.0

        # Estimated spend (unverified manual entries), also excluding debt payments.
        # NULL transaction_type is treated as "expense" (legacy rows pre-dating the column).
        estimated_raw = (
            db.query(func.sum(models.Transaction.amount))
            .filter(
                models.Transaction.category_id == budget.category_id,
                models.Transaction.date >= first_day,
                models.Transaction.date <= last_day,
                models.Transaction.is_verified == False,
                or_(
                    models.Transaction.transaction_type == "expense",
                    models.Transaction.transaction_type == None,
                ),
            )
            .scalar()
        ) or 0.0

        # Spend = net outflow (positive value). Handles refunds naturally.
        # A net inflow (e.g. income category) is reported as 0 spent.
        verified_spend  = max(0.0, -verified_raw)
        estimated_spend = max(0.0, -estimated_raw)
        total_spend     = verified_spend + estimated_spend
        remaining       = budget.amount - total_spend

        # Avoid division by zero for $0 budgets
        divisor = budget.amount if budget.amount > 0 else 1.0
        pct_verified  = round((verified_spend  / divisor) * 100, 1)
        pct_estimated = round((estimated_spend / divisor) * 100, 1)
        pct_total     = round((total_spend     / divisor) * 100, 1)

        if pct_total >= 90:
            budget_status = "over"
        elif pct_total >= 75:
            budget_status = "warning"
        else:
            budget_status = "healthy"

        results.append(schemas.BudgetStatus(
            budget=budget,
            verified_spend=round(verified_spend, 2),
            estimated_spend=round(estimated_spend, 2),
            total_spend=round(total_spend, 2),
            remaining=round(remaining, 2),
            pct_total=pct_total,
            pct_verified=pct_verified,
            pct_estimated=pct_estimated,
            status=budget_status,
        ))

    # Sort: over → warning → healthy, then by category name
    order = {"over": 0, "warning": 1, "healthy": 2}
    results.sort(key=lambda r: (order[r.status], r.budget.category.name if r.budget.category else ""))
    return results


@router.get("", response_model=List[schemas.BudgetResponse])
def list_budgets(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return db.query(models.Budget).options(
        joinedload(models.Budget.category)
    ).filter(models.Budget.is_active == True).all()


@router.post("", response_model=schemas.BudgetResponse, status_code=status.HTTP_201_CREATED)
def create_budget(
    payload: schemas.BudgetCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    category = db.query(models.Category).filter(models.Category.id == payload.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    budget = models.Budget(user_id=current_user.id, **payload.model_dump())
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


@router.patch("/{budget_id}", response_model=schemas.BudgetResponse)
def update_budget(
    budget_id: int,
    payload: schemas.BudgetUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    budget = db.query(models.Budget).filter(models.Budget.id == budget_id).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(budget, field, value)
    db.commit()
    db.refresh(budget)
    return budget


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(
    budget_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    budget = db.query(models.Budget).filter(models.Budget.id == budget_id).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    budget.is_active = False
    db.commit()
