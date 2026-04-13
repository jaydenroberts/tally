from typing import List
from datetime import date as date_type
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_owner

router = APIRouter(prefix="/api/savings", tags=["savings"])


def _load_goal(db: Session, goal_id: int) -> models.SavingsGoal:
    goal = (
        db.query(models.SavingsGoal)
        .options(joinedload(models.SavingsGoal.linked_account))
        .filter(models.SavingsGoal.id == goal_id)
        .first()
    )
    if not goal:
        raise HTTPException(status_code=404, detail="Savings goal not found")
    return goal


@router.get("", response_model=List[schemas.SavingsGoalResponse])
def list_savings_goals(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return (
        db.query(models.SavingsGoal)
        .options(joinedload(models.SavingsGoal.linked_account))
        .order_by(models.SavingsGoal.is_completed, models.SavingsGoal.deadline.asc().nulls_last())
        .all()
    )


@router.get("/account/{account_id}/summary")
def account_savings_summary(
    account_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Return balance, total allocated to active goals, and available amount for a savings account."""
    account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    active_goals = (
        db.query(models.SavingsGoal)
        .filter(
            models.SavingsGoal.linked_account_id == account_id,
            models.SavingsGoal.is_completed == False,
        )
        .all()
    )
    total_allocated = round(sum(g.current_amount for g in active_goals), 2)
    available = round(account.balance - total_allocated, 2)
    return {
        "account_id": account_id,
        "account_name": account.name,
        "balance": account.balance,
        "total_allocated": total_allocated,
        "available": available,
        "active_goal_count": len(active_goals),
    }


@router.post("/allocate", response_model=schemas.AllocateResponse)
def bulk_allocate(
    payload: schemas.AllocateRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Allocate available balance from a savings account to one or more goals atomically.
    Creates a SavingsContribution record per goal for audit history.
    """
    if not payload.allocations:
        raise HTTPException(status_code=400, detail="No allocations provided")

    account = db.query(models.Account).filter(models.Account.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    linked_goals = (
        db.query(models.SavingsGoal)
        .filter(
            models.SavingsGoal.linked_account_id == payload.account_id,
            models.SavingsGoal.is_completed == False,
        )
        .all()
    )
    allocated_total = sum(g.current_amount for g in linked_goals)
    available_before = round(account.balance - allocated_total, 2)

    for item in payload.allocations:
        if item.amount <= 0:
            raise HTTPException(status_code=400, detail=f"Allocation amount for goal {item.goal_id} must be positive")

    allocation_sum = round(sum(item.amount for item in payload.allocations), 2)
    if allocation_sum > available_before + 0.001:
        raise HTTPException(
            status_code=400,
            detail=f"Total allocation {allocation_sum} exceeds available balance {available_before}",
        )

    goal_map: dict[int, models.SavingsGoal] = {}
    for item in payload.allocations:
        goal = (
            db.query(models.SavingsGoal)
            .options(joinedload(models.SavingsGoal.linked_account))
            .filter(models.SavingsGoal.id == item.goal_id)
            .first()
        )
        if not goal:
            raise HTTPException(status_code=404, detail=f"Savings goal {item.goal_id} not found")
        if goal.linked_account_id != payload.account_id:
            raise HTTPException(
                status_code=400,
                detail=f"Goal '{goal.name}' is not linked to the specified account",
            )
        if goal.is_completed:
            raise HTTPException(status_code=400, detail=f"Goal '{goal.name}' is already completed")
        goal_map[item.goal_id] = goal

    for item in payload.allocations:
        goal = goal_map[item.goal_id]
        new_amount = round(goal.current_amount + item.amount, 2)
        goal.current_amount = new_amount
        if new_amount >= goal.target_amount:
            goal.is_completed = True
        db.add(models.SavingsContribution(
            goal_id=goal.id,
            amount=item.amount,
            balance_after=new_amount,
            notes="Bulk allocation",
        ))

    db.commit()
    available_after = round(available_before - allocation_sum, 2)
    updated_goals = [_load_goal(db, item.goal_id) for item in payload.allocations]
    return schemas.AllocateResponse(
        updated_goals=updated_goals,
        available_before=available_before,
        available_after=available_after,
    )


@router.post("/{goal_id}/withdraw", response_model=schemas.WithdrawResponse)
def withdraw_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Mark a goal as spent. Creates a manual debit transaction on the linked savings
    account (source='manual', is_verified=False) so it reconciles on the next import.
    """
    goal = _load_goal(db, goal_id)
    if not goal.linked_account_id:
        raise HTTPException(
            status_code=400,
            detail="Goal has no linked account. Link a savings account before withdrawing.",
        )
    if goal.current_amount <= 0:
        raise HTTPException(status_code=400, detail="Goal has no saved amount to withdraw")

    tx = models.Transaction(
        account_id=goal.linked_account_id,
        date=date_type.today(),
        description=f"Savings withdrawal: {goal.name}",
        amount=round(-goal.current_amount, 2),
        source="manual",
        is_verified=False,
        savings_goal_id=goal.id,
    )
    db.add(tx)
    goal.is_completed = True
    db.commit()
    db.refresh(tx)
    return schemas.WithdrawResponse(
        goal=_load_goal(db, goal_id),
        transaction=tx,
    )


@router.post("", response_model=schemas.SavingsGoalResponse, status_code=status.HTTP_201_CREATED)
def create_savings_goal(
    payload: schemas.SavingsGoalCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    if payload.linked_account_id:
        account = db.query(models.Account).filter(models.Account.id == payload.linked_account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Linked account not found")
    goal = models.SavingsGoal(user_id=current_user.id, **payload.model_dump())
    db.add(goal)
    db.commit()
    return _load_goal(db, goal.id)


@router.get("/{goal_id}", response_model=schemas.SavingsGoalResponse)
def get_savings_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return _load_goal(db, goal_id)


@router.patch("/{goal_id}", response_model=schemas.SavingsGoalResponse)
def update_savings_goal(
    goal_id: int,
    payload: schemas.SavingsGoalUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    goal = _load_goal(db, goal_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    # Auto-complete if current meets or exceeds target
    if goal.current_amount >= goal.target_amount:
        goal.is_completed = True
    db.commit()
    return _load_goal(db, goal_id)


@router.post("/{goal_id}/contribute", response_model=schemas.SavingsGoalResponse)
def log_contribution(
    goal_id: int,
    payload: schemas.ContributionRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Add an amount to the goal's current balance. Records an immutable
    SavingsContribution entry for audit history. Auto-completes the goal
    if the target is reached.
    """
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Contribution amount must be positive")
    goal = _load_goal(db, goal_id)
    if goal.is_completed:
        raise HTTPException(status_code=400, detail="Goal is already completed")

    new_amount = round(goal.current_amount + payload.amount, 2)
    goal.current_amount = new_amount
    if new_amount >= goal.target_amount:
        goal.is_completed = True

    # Record the contribution in the audit trail
    contribution_record = models.SavingsContribution(
        goal_id=goal_id,
        amount=payload.amount,
        balance_after=new_amount,
        notes=payload.notes,
    )
    db.add(contribution_record)
    db.commit()
    return _load_goal(db, goal_id)


@router.get("/{goal_id}/contributions", response_model=List[schemas.SavingsContributionResponse])
def list_contributions(
    goal_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Return all recorded contributions for a savings goal, most recent first."""
    if not db.query(models.SavingsGoal).filter(models.SavingsGoal.id == goal_id).first():
        raise HTTPException(status_code=404, detail="Savings goal not found")
    return (
        db.query(models.SavingsContribution)
        .filter(models.SavingsContribution.goal_id == goal_id)
        .order_by(models.SavingsContribution.contributed_at.desc())
        .all()
    )


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_savings_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    goal = db.query(models.SavingsGoal).filter(models.SavingsGoal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Savings goal not found")
    db.delete(goal)
    db.commit()
