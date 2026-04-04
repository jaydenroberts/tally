from typing import List
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
