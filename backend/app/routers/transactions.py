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
    sort_by: Optional[str] = Query("date", description="Column to sort by: date, amount, account_id, is_verified"),
    sort_dir: Optional[str] = Query("desc", description="Sort direction: asc or desc"),
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

    # Map accepted sort_by values to ORM columns; reject anything unexpected
    sortable_columns = {
        "date":        models.Transaction.date,
        "amount":      models.Transaction.amount,
        "account_id":  models.Transaction.account_id,
        "is_verified": models.Transaction.is_verified,
    }
    sort_col = sortable_columns.get(sort_by, models.Transaction.date)
    order_expr = sort_col.asc() if sort_dir == "asc" else sort_col.desc()

    return q.order_by(order_expr).offset(skip).limit(limit).all()


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
    # Null FK refs before deleting to avoid constraint violations (foreign_keys=ON)
    db.query(models.DebtPayment).filter(models.DebtPayment.transaction_id.in_(ids)).update(
        {"transaction_id": None}, synchronize_session=False
    )
    db.query(models.SavingsContribution).filter(models.SavingsContribution.transaction_id.in_(ids)).update(
        {"transaction_id": None}, synchronize_session=False
    )
    db.query(models.Transaction).filter(models.Transaction.id.in_(ids)).delete(synchronize_session=False)
    db.commit()


@router.post("/transfer", response_model=schemas.TransferResponse, status_code=status.HTTP_201_CREATED)
def create_transfer(
    payload: schemas.TransferCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Create an account-to-account transfer as a linked transaction pair.

    Produces two transactions that share a transfer_pair_id:
      - A debit (negative) on the source account
      - A credit (positive) on the destination account

    Both are typed as 'transfer' and are excluded from budget calculations.
    """
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Transfer amount must be greater than zero")

    if payload.source_account_id == payload.destination_account_id:
        raise HTTPException(status_code=400, detail="Source and destination accounts must be different")

    source_account = db.query(models.Account).filter(
        models.Account.id == payload.source_account_id
    ).first()
    if not source_account or not source_account.is_active:
        raise HTTPException(status_code=404, detail="Source account not found or inactive")

    dest_account = db.query(models.Account).filter(
        models.Account.id == payload.destination_account_id
    ).first()
    if not dest_account or not dest_account.is_active:
        raise HTTPException(status_code=404, detail="Destination account not found or inactive")

    amount = round(payload.amount, 2)
    description = payload.description

    # Debit side — money leaves the source account
    debit_tx = models.Transaction(
        account_id=payload.source_account_id,
        amount=-amount,
        date=payload.date,
        description=description or f"Transfer to {dest_account.name}",
        notes=payload.notes,
        source="manual",
        is_verified=False,
        transaction_type="transfer",
    )
    db.add(debit_tx)
    db.flush()  # get the id before setting transfer_pair_id

    # Use the debit transaction's id as the shared grouping key
    debit_tx.transfer_pair_id = debit_tx.id

    # Credit side — money arrives at the destination account
    credit_tx = models.Transaction(
        account_id=payload.destination_account_id,
        amount=amount,
        date=payload.date,
        description=description or f"Transfer from {source_account.name}",
        notes=payload.notes,
        source="manual",
        is_verified=False,
        transaction_type="transfer",
        transfer_pair_id=debit_tx.id,
    )
    db.add(credit_tx)
    db.commit()
    db.refresh(debit_tx)
    db.refresh(credit_tx)

    return schemas.TransferResponse(
        debit_transaction=debit_tx,
        credit_transaction=credit_tx,
        transfer_pair_id=debit_tx.id,
    )


@router.post("/link-transfer-pair", response_model=schemas.TransferResponse)
def link_transfer_pair(
    payload: schemas.LinkTransferPairRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Retroactively link two existing transactions as a transfer pair.

    Both transactions must be on different accounts and must not already
    be part of a transfer pair. The transaction with the lower (negative)
    amount is designated the debit side; the other is the credit side.
    """
    if payload.transaction_a_id == payload.transaction_b_id:
        raise HTTPException(status_code=400, detail="transaction_a_id and transaction_b_id must be different")

    tx_a = db.query(models.Transaction).filter(models.Transaction.id == payload.transaction_a_id).first()
    if not tx_a:
        raise HTTPException(status_code=404, detail=f"Transaction {payload.transaction_a_id} not found")

    tx_b = db.query(models.Transaction).filter(models.Transaction.id == payload.transaction_b_id).first()
    if not tx_b:
        raise HTTPException(status_code=404, detail=f"Transaction {payload.transaction_b_id} not found")

    if tx_a.account_id == tx_b.account_id:
        raise HTTPException(status_code=400, detail="Transfer pair must be on different accounts")

    if tx_a.transfer_pair_id is not None or tx_b.transfer_pair_id is not None:
        raise HTTPException(status_code=409, detail="One or more transactions are already part of a transfer pair")

    if tx_a.transaction_type == "transfer" or tx_b.transaction_type == "transfer":
        raise HTTPException(status_code=409, detail="One or more transactions are already part of a transfer pair")

    # Use tx_a's id as the shared grouping key
    tx_a.transaction_type = "transfer"
    tx_a.transfer_pair_id = tx_a.id
    tx_b.transaction_type = "transfer"
    tx_b.transfer_pair_id = tx_a.id

    db.commit()
    db.refresh(tx_a)
    db.refresh(tx_b)

    # Assign debit/credit by sign — negative amount is the debit side
    if tx_b.amount < tx_a.amount:
        debit_tx, credit_tx = tx_b, tx_a
    else:
        debit_tx, credit_tx = tx_a, tx_b

    return schemas.TransferResponse(
        debit_transaction=debit_tx,
        credit_transaction=credit_tx,
        transfer_pair_id=tx_a.id,
    )


@router.delete("/{tx_id}/link-transfer-pair", status_code=status.HTTP_204_NO_CONTENT)
def unlink_transfer_pair(
    tx_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Unlink both sides of a transfer pair.
    Both transactions are reset to 'expense' type and their transfer_pair_id is cleared.
    """
    tx = db.query(models.Transaction).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if tx.transfer_pair_id is None:
        raise HTTPException(status_code=400, detail="Transaction is not part of a transfer pair")

    # Find the paired transaction (same transfer_pair_id, different id)
    pair_tx = db.query(models.Transaction).filter(
        models.Transaction.transfer_pair_id == tx.transfer_pair_id,
        models.Transaction.id != tx_id,
    ).first()

    # Reset this transaction
    tx.transaction_type = "expense"
    tx.transfer_pair_id = None

    # Reset the paired transaction if it exists
    if pair_tx:
        pair_tx.transaction_type = "expense"
        pair_tx.transfer_pair_id = None

    db.commit()


@router.post("/{tx_id}/link-savings-withdrawal", response_model=schemas.TransactionResponse)
def link_savings_withdrawal(
    tx_id: int,
    payload: schemas.LinkSavingsWithdrawalRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Link an existing debit (negative) transaction to a savings goal as a withdrawal.
    This reduces the goal's current_amount and creates a negative SavingsContribution
    audit record (negative amount indicates withdrawal direction).
    """
    tx = db.query(models.Transaction).options(
        joinedload(models.Transaction.category)
    ).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if tx.amount >= 0:
        raise HTTPException(
            status_code=400,
            detail="Only debit transactions can be linked as a savings withdrawal",
        )

    if tx.transaction_type in ("savings_transfer", "transfer", "debt_payment"):
        raise HTTPException(status_code=409, detail="Transaction is already linked")

    goal = db.query(models.SavingsGoal).filter(models.SavingsGoal.id == payload.goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Savings goal not found")

    if goal.is_completed:
        raise HTTPException(status_code=400, detail="Savings goal is already completed")

    withdrawal_amount = round(abs(tx.amount), 2)
    new_amount = round(max(0.0, goal.current_amount - withdrawal_amount), 2)

    goal.current_amount = new_amount
    if new_amount == 0:
        goal.is_completed = True

    # Negative amount on the contribution indicates withdrawal direction
    contribution = models.SavingsContribution(
        goal_id=payload.goal_id,
        amount=-withdrawal_amount,
        balance_after=new_amount,
        transaction_id=tx_id,
    )
    db.add(contribution)

    tx.transaction_type = "savings_transfer"

    db.commit()
    db.refresh(tx)
    return tx


@router.delete("/{tx_id}/link-savings-withdrawal", status_code=status.HTTP_204_NO_CONTENT)
def unlink_savings_withdrawal(
    tx_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Reverse a savings goal withdrawal linkage.
    Restores the goal's balance, deletes the contribution record, and resets the
    transaction type back to 'expense'.
    """
    tx = db.query(models.Transaction).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # The withdrawal contribution is identified by negative amount on this transaction
    contribution = db.query(models.SavingsContribution).filter(
        models.SavingsContribution.transaction_id == tx_id,
        models.SavingsContribution.amount < 0,
    ).first()
    if not contribution:
        raise HTTPException(status_code=404, detail="No savings withdrawal contribution found for this transaction")

    goal = db.query(models.SavingsGoal).filter(models.SavingsGoal.id == contribution.goal_id).first()
    if goal:
        goal.current_amount = round(goal.current_amount + abs(contribution.amount), 2)
        goal.is_completed = False  # reversal means goal is no longer complete

    db.delete(contribution)
    tx.transaction_type = "expense"

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

    updates = payload.model_dump(exclude_unset=True)

    # Imported/verified transactions are source-of-truth for core fields.
    # Category is always editable (that's the point of inline categorisation).
    # Block only if the patch touches any protected field.
    PROTECTED_FIELDS = {"amount", "date", "description", "account_id"}
    if tx.is_verified and tx.source == "import":
        blocked = PROTECTED_FIELDS & updates.keys()
        if blocked:
            raise HTTPException(
                status_code=400,
                detail="Imported (verified) transactions cannot be edited. Delete and re-import if needed.",
            )

    for field, value in updates.items():
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
    # Null FK refs before deleting to avoid constraint violations (foreign_keys=ON)
    db.query(models.DebtPayment).filter(models.DebtPayment.transaction_id == tx_id).update({"transaction_id": None})
    db.query(models.SavingsContribution).filter(models.SavingsContribution.transaction_id == tx_id).update({"transaction_id": None})
    db.delete(tx)
    db.commit()


@router.post("/{tx_id}/link-debt", response_model=schemas.TransactionResponse)
def link_transaction_to_debt(
    tx_id: int,
    payload: schemas.LinkTransactionToDebtRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Link an existing debit transaction to a debt record.
    This reduces the debt's current_balance and creates a DebtPayment audit entry.
    Only debit (negative amount) transactions may be linked.
    """
    tx = db.query(models.Transaction).options(
        joinedload(models.Transaction.category)
    ).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if tx.amount >= 0:
        raise HTTPException(
            status_code=400,
            detail="Only debit transactions (negative amount) can be linked to a debt payment",
        )

    if tx.debt_id is not None:
        raise HTTPException(status_code=409, detail="Transaction is already linked to a debt")

    debt = db.query(models.Debt).filter(models.Debt.id == payload.debt_id).first()
    if not debt:
        raise HTTPException(status_code=404, detail="Debt not found")

    if debt.is_paid_off:
        raise HTTPException(status_code=400, detail="Debt is already paid off")

    # Guard against double-recording (e.g. the tx was previously linked then unlinked
    # and re-linked while a stale DebtPayment still references it).
    existing = db.query(models.DebtPayment).filter(
        models.DebtPayment.transaction_id == tx_id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Transaction is already recorded as a payment")

    payment_amount = round(abs(tx.amount), 2)
    new_balance = round(max(0.0, debt.current_balance - payment_amount), 2)

    debt.current_balance = new_balance
    if new_balance == 0:
        debt.is_paid_off = True

    payment = models.DebtPayment(
        debt_id=payload.debt_id,
        amount=payment_amount,
        balance_after=new_balance,
        notes=None,
        paid_at=tx.date,
        transaction_id=tx_id,
    )
    db.add(payment)

    tx.debt_id = payload.debt_id
    tx.transaction_type = "debt_payment"

    # Auto-assign "Debt Payment" category if the transaction isn't already categorised
    if tx.category_id is None:
        debt_payment_cat = db.query(models.Category).filter(
            models.Category.name == "Debt Payment",
            models.Category.is_system == True,
        ).first()
        if debt_payment_cat:
            tx.category_id = debt_payment_cat.id

    db.commit()
    db.refresh(tx)
    return tx


@router.post("/{tx_id}/link-savings", response_model=schemas.LinkTransactionToSavingsResponse)
def link_transaction_to_savings(
    tx_id: int,
    payload: schemas.LinkTransactionToSavingsRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Allocate a credit transaction across one or more savings goals.

    Each allocation creates a SavingsContribution audit record linked back to this
    transaction. The transaction is reclassified as 'savings_transfer' so it is
    excluded from budget calculations. Partial allocation is permitted — the sum
    of allocations does not need to equal the full transaction amount.
    """
    tx = db.query(models.Transaction).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if not payload.allocations:
        raise HTTPException(status_code=400, detail="No allocations provided")

    # Validate every allocation amount is positive
    for item in payload.allocations:
        if item.amount <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Allocation amount for goal {item.goal_id} must be positive",
            )

    # Partial allocation is allowed; total must not exceed the transaction amount
    total = round(sum(item.amount for item in payload.allocations), 2)
    tx_abs = round(abs(tx.amount), 2)
    if total > tx_abs:
        raise HTTPException(
            status_code=400,
            detail=f"Total allocations (${total}) exceed transaction amount (${tx_abs})",
        )

    contributions = []
    for item in payload.allocations:
        goal = db.query(models.SavingsGoal).filter(models.SavingsGoal.id == item.goal_id).first()
        if not goal:
            raise HTTPException(status_code=404, detail=f"Savings goal {item.goal_id} not found")
        if goal.is_completed:
            raise HTTPException(
                status_code=400,
                detail=f"Savings goal '{goal.name}' is already completed",
            )

        new_amount = round(goal.current_amount + item.amount, 2)
        goal.current_amount = new_amount
        if new_amount >= goal.target_amount:
            goal.is_completed = True

        contribution = models.SavingsContribution(
            goal_id=item.goal_id,
            amount=item.amount,
            balance_after=new_amount,
            transaction_id=tx_id,
        )
        db.add(contribution)
        contributions.append(contribution)

    # Reclassify the transaction so it is excluded from budget calculations
    tx.transaction_type = "savings_transfer"

    db.commit()
    for c in contributions:
        db.refresh(c)

    return schemas.LinkTransactionToSavingsResponse(
        contributions=contributions,
        total_allocated=total,
        transaction_id=tx_id,
    )


@router.delete("/{tx_id}/link-debt", status_code=status.HTTP_204_NO_CONTENT)
def unlink_transaction_from_debt(
    tx_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Remove the debt linkage from a transaction.
    Reverses the DebtPayment record and restores the debt's current_balance.
    Debt is also marked not paid-off (the reversal may bring balance above zero).
    """
    tx = db.query(models.Transaction).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if tx.debt_id is None:
        raise HTTPException(status_code=400, detail="Transaction is not linked to a debt")

    payment = db.query(models.DebtPayment).filter(
        models.DebtPayment.transaction_id == tx_id
    ).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Linked payment record not found")

    debt = db.query(models.Debt).filter(models.Debt.id == tx.debt_id).first()
    if debt:
        debt.current_balance = round(debt.current_balance + payment.amount, 2)
        debt.is_paid_off = False

    db.delete(payment)

    tx.debt_id = None
    tx.transaction_type = "expense"

    db.commit()
