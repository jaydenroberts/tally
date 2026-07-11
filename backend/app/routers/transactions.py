from typing import List, Optional
from datetime import date as date_type
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_owner

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


def _apply_tx_filters(
    q,
    *,
    account_id=None,
    category_id=None,
    is_verified=None,
    source=None,
    transaction_type=None,
    amount_sign=None,
    exclude_transfers=False,
    date_from=None,
    date_to=None,
):
    """Apply the shared transaction filter set (FE-011).

    ``amount_sign`` is 'positive' | 'negative' — drives the Income/Expenses
    segments, which are sign-based rather than a stored column. ``exclude_transfers``
    keeps transfer pairs out of Income/Expenses/Unverified segments so server-side
    counts and stats match the page's prior client-side semantics.
    """
    if account_id is not None:
        q = q.filter(models.Transaction.account_id == account_id)
    if category_id is not None:
        q = q.filter(models.Transaction.category_id == category_id)
    if is_verified is not None:
        q = q.filter(models.Transaction.is_verified == is_verified)
    if source is not None:
        q = q.filter(models.Transaction.source == source)
    if transaction_type is not None:
        q = q.filter(models.Transaction.transaction_type == transaction_type)
    if amount_sign == "positive":
        q = q.filter(models.Transaction.amount > 0)
    elif amount_sign == "negative":
        q = q.filter(models.Transaction.amount < 0)
    if exclude_transfers:
        # Canonical exclusion set (mirrored in dashboard.py / budgets.py):
        # both transfer legs are excluded from income AND expense aggregates.
        # debt_payment is handled separately (excluded from expenses only) by
        # the summary aggregate, not here.
        q = q.filter(
            models.Transaction.transaction_type.notin_(("transfer", "savings_transfer"))
        )
    if date_from is not None:
        q = q.filter(models.Transaction.date >= date_from)
    if date_to is not None:
        q = q.filter(models.Transaction.date <= date_to)
    return q


def build_allocations(tx: models.Transaction, db: Session) -> list[schemas.AllocationView]:
    """Compute the full link state of a transaction.

    Returns one AllocationView per linked savings contribution (positive or
    negative — withdrawals are surfaced as negative amounts) and one for the
    debt link if any. Names come from the related goal/debt rows so the
    frontend can render without extra lookups.
    """
    items: list[schemas.AllocationView] = []

    contribs = (
        db.query(models.SavingsContribution, models.SavingsGoal)
        .join(models.SavingsGoal, models.SavingsContribution.goal_id == models.SavingsGoal.id)
        .filter(models.SavingsContribution.transaction_id == tx.id)
        .all()
    )
    for contrib, goal in contribs:
        items.append(schemas.AllocationView(
            kind="goal",
            ref_id=goal.id,
            name=goal.name,
            amount=contrib.amount,  # signed: positive = contribution, negative = withdrawal
        ))

    if tx.debt_id is not None:
        row = (
            db.query(models.DebtPayment, models.Debt)
            .join(models.Debt, models.DebtPayment.debt_id == models.Debt.id)
            .filter(models.DebtPayment.transaction_id == tx.id)
            .first()
        )
        if row:
            payment, debt = row
            items.append(schemas.AllocationView(
                kind="debt",
                ref_id=debt.id,
                name=debt.name,
                amount=payment.amount,  # debt payments are stored as positive magnitudes
            ))

    return items


def attach_allocations(tx: models.Transaction, db: Session) -> models.Transaction:
    """Attach computed allocations to the ORM instance so Pydantic
    from_attributes=True picks them up on the response. Mutates and returns tx."""
    tx.allocations = build_allocations(tx, db)
    return tx


def _reverse_debt_link(tx: models.Transaction, db: Session) -> None:
    """Reverse a debt payment link the way DELETE /{tx_id}/link-debt does:
    add the RECORDED payment amount back to the debt balance and clear paid-off.
    The recorded DebtPayment.amount is the effective applied delta (AUDIT-07),
    so this is exactly symmetric. Deletes the DebtPayment audit row."""
    if tx.debt_id is None:
        return
    payment = db.query(models.DebtPayment).filter(
        models.DebtPayment.transaction_id == tx.id
    ).first()
    if payment:
        debt = db.query(models.Debt).filter(models.Debt.id == tx.debt_id).first()
        if debt:
            debt.current_balance = round(debt.current_balance + payment.amount, 2)
            debt.is_paid_off = False  # upward correction — two-way reset (AUDIT-23)
        db.delete(payment)
    tx.debt_id = None


def _reverse_savings_links(tx: models.Transaction, db: Session) -> None:
    """Reverse every SavingsContribution attached to this transaction, restoring
    each goal's current_amount by the signed contribution amount, and delete the
    audit rows. Mirrors PHASE 2 of batch_update_allocations."""
    contribs = db.query(models.SavingsContribution).filter(
        models.SavingsContribution.transaction_id == tx.id
    ).all()
    for contrib in contribs:
        goal = db.query(models.SavingsGoal).filter(
            models.SavingsGoal.id == contrib.goal_id
        ).first()
        if goal:
            # Subtract the signed amount: a contribution (+) reduces the goal back,
            # a withdrawal (-) restores it. round() keeps float drift bounded.
            goal.current_amount = round(max(0.0, goal.current_amount - contrib.amount), 2)
            # Two-way completion flag (AUDIT-23): a reversal can only lower the
            # balance, so re-open the goal if it now falls short of a real target.
            if goal.current_amount < goal.target_amount:
                goal.is_completed = False
        db.delete(contrib)


def _reset_transfer_pair_sibling(tx: models.Transaction, db: Session) -> None:
    """When a transfer leg is deleted, its sibling must not be left stranded as a
    dangling 'transfer' with a pair id that points at nothing (AUDIT-06). Reset
    every OTHER member of the pair back to a plain income/expense row by sign."""
    if tx.transfer_pair_id is None:
        return
    siblings = db.query(models.Transaction).filter(
        models.Transaction.transfer_pair_id == tx.transfer_pair_id,
        models.Transaction.id != tx.id,
    ).all()
    for sib in siblings:
        sib.transaction_type = "income" if sib.amount > 0 else "expense"
        sib.transfer_pair_id = None


def _reverse_all_links_before_delete(tx: models.Transaction, db: Session) -> None:
    """Single entry point for delete paths: reverse any debt/goal balance effect
    and un-strand a transfer-pair sibling BEFORE the row is removed (AUDIT-06)."""
    _reverse_debt_link(tx, db)
    _reverse_savings_links(tx, db)
    _reset_transfer_pair_sibling(tx, db)


@router.get("", response_model=List[schemas.TransactionResponse])
def list_transactions(
    account_id: Optional[int] = Query(None),
    category_id: Optional[int] = Query(None),
    is_verified: Optional[bool] = Query(None),
    source: Optional[str] = Query(None, description="'manual' or 'import'"),
    transaction_type: Optional[str] = Query(None, description="expense | income | transfer | debt_payment"),
    amount_sign: Optional[str] = Query(None, description="'positive' or 'negative' — drives Income/Expenses segments"),
    exclude_transfers: bool = Query(False, description="Exclude transfer-type rows (Income/Expenses/Unverified segments)"),
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
    q = _apply_tx_filters(
        q,
        account_id=account_id, category_id=category_id, is_verified=is_verified,
        source=source, transaction_type=transaction_type, amount_sign=amount_sign,
        exclude_transfers=exclude_transfers, date_from=date_from, date_to=date_to,
    )

    # Map accepted sort_by values to ORM columns; reject anything unexpected
    sortable_columns = {
        "date":        models.Transaction.date,
        "amount":      models.Transaction.amount,
        "account_id":  models.Transaction.account_id,
        "is_verified": models.Transaction.is_verified,
    }
    sort_col = sortable_columns.get(sort_by, models.Transaction.date)
    order_expr = sort_col.asc() if sort_dir == "asc" else sort_col.desc()

    # Stable tiebreak on id so paging never drops/repeats rows that share a sort key.
    return q.order_by(order_expr, models.Transaction.id.desc()).offset(skip).limit(limit).all()


@router.get("/count")
def count_transactions(
    account_id: Optional[int] = Query(None),
    category_id: Optional[int] = Query(None),
    is_verified: Optional[bool] = Query(None),
    source: Optional[str] = Query(None),
    transaction_type: Optional[str] = Query(None),
    amount_sign: Optional[str] = Query(None),
    exclude_transfers: bool = Query(False),
    date_from: Optional[date_type] = Query(None),
    date_to: Optional[date_type] = Query(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = _apply_tx_filters(
        db.query(models.Transaction),
        account_id=account_id, category_id=category_id, is_verified=is_verified,
        source=source, transaction_type=transaction_type, amount_sign=amount_sign,
        exclude_transfers=exclude_transfers, date_from=date_from, date_to=date_to,
    )
    return {"count": q.count()}


@router.get("/summary")
def transaction_summary(
    date_from: Optional[date_type] = Query(None, description="Start of the stat window (e.g. month start)"),
    date_to: Optional[date_type] = Query(None),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Aggregate income / expense / net over a date window, transfers excluded (FE-011).

    Computed in SQL so the Transactions page stat cards stay correct across pagination
    without loading every row. ``unverified_count`` counts non-transfer unverified rows
    over ALL time (matches the page's prior whole-dataset semantic), independent of the
    date window used for the MTD money figures.
    """
    money_q = _apply_tx_filters(
        db.query(models.Transaction),
        account_id=account_id, exclude_transfers=True,
        date_from=date_from, date_to=date_to,
    )
    income = money_q.with_entities(
        func.coalesce(func.sum(models.Transaction.amount), 0.0)
    ).filter(models.Transaction.amount > 0).scalar() or 0.0
    # debt_payment legs are excluded from the expense aggregate to match budgets.py
    # (a debt payment is a balance-sheet transfer, not discretionary spend).
    expenses = money_q.with_entities(
        func.coalesce(func.sum(models.Transaction.amount), 0.0)
    ).filter(
        models.Transaction.amount < 0,
        models.Transaction.transaction_type != "debt_payment",
    ).scalar() or 0.0

    unverified_count = _apply_tx_filters(
        db.query(models.Transaction),
        account_id=account_id, is_verified=False, exclude_transfers=True,
    ).count()

    income = float(income)
    expenses = abs(float(expenses))   # report expenses as a positive magnitude
    return {
        "income": income,
        "expenses": expenses,
        "net": income - expenses,
        "unverified_count": unverified_count,
    }


@router.post("", response_model=schemas.TransactionResponse, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: schemas.TransactionCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    account = db.query(models.Account).filter(models.Account.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    # transaction_type comes from the payload ('expense' or 'income').
    # We pass it explicitly via model_dump() rather than relying on the SQLAlchemy
    # column default, which is not applied to rows on ALTER-added columns.
    tx = models.Transaction(
        **payload.model_dump(),
        source="manual",   # manual entries are always estimates
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
    """Delete multiple transactions by ID. Owner-only. Silently skips IDs that don't exist.

    Each transaction has its linked debt/goal balance effect reversed and any
    transfer-pair sibling un-stranded before deletion (AUDIT-06), so a bulk delete
    can never leave money orphaned. Reversals run per-row because the applied delta
    lives on the individual DebtPayment/SavingsContribution audit rows.
    """
    txs = db.query(models.Transaction).filter(models.Transaction.id.in_(ids)).all()
    # A transfer pair may be deleted whole (both legs in `ids`) or half. Reversing
    # per-row is safe: _reset_transfer_pair_sibling only touches siblings NOT being
    # deleted in the same call, because a sibling still in `ids` is reset-then-deleted.
    delete_id_set = {t.id for t in txs}
    for tx in txs:
        _reverse_debt_link(tx, db)
        _reverse_savings_links(tx, db)
        if tx.transfer_pair_id is not None:
            siblings = db.query(models.Transaction).filter(
                models.Transaction.transfer_pair_id == tx.transfer_pair_id,
                models.Transaction.id != tx.id,
            ).all()
            for sib in siblings:
                if sib.id in delete_id_set:
                    continue  # sibling is also being deleted; no need to reset it
                sib.transaction_type = "income" if sib.amount > 0 else "expense"
                sib.transfer_pair_id = None
    db.query(models.ImportDraftRow).filter(models.ImportDraftRow.duplicate_of.in_(ids)).update(
        {"duplicate_of": None}, synchronize_session=False
    )
    for tx in txs:
        db.delete(tx)
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

    # A transfer moves money OUT of one account and INTO another: the two legs must
    # have opposite signs (one debit, one credit). Reject same-sign pairs and any
    # zero-amount leg. Tolerance guards float noise around zero.
    _SIGN_TOL = 0.005
    if tx_a.amount > _SIGN_TOL and tx_b.amount > _SIGN_TOL:
        raise HTTPException(status_code=400, detail="Transfer legs must have opposite signs (one debit, one credit)")
    if tx_a.amount < -_SIGN_TOL and tx_b.amount < -_SIGN_TOL:
        raise HTTPException(status_code=400, detail="Transfer legs must have opposite signs (one debit, one credit)")
    if abs(tx_a.amount) <= _SIGN_TOL or abs(tx_b.amount) <= _SIGN_TOL:
        raise HTTPException(status_code=400, detail="Transfer legs must have a non-zero amount")

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

    requested = round(abs(tx.amount), 2)
    # Effective applied delta (AUDIT-07): a withdrawal can only take the goal to zero,
    # so record what was actually removed, keeping link/unlink symmetric.
    withdrawal_amount = round(min(requested, goal.current_amount), 2)
    new_amount = round(goal.current_amount - withdrawal_amount, 2)

    goal.current_amount = new_amount
    # AUDIT-23: draining a goal to zero must NOT mark it complete+locked — a spend is
    # not goal attainment. Completion is (current >= target AND target > 0) only.

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
    return attach_allocations(tx, db)


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


@router.patch("/{tx_id}/allocations", response_model=schemas.TransactionResponse)
def batch_update_allocations(
    tx_id: int,
    payload: schemas.BatchAllocationsRequest,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """
    Replace all goal and debt allocations on a transaction in one call.

    Full-replace semantics: existing savings contributions (both contribution
    and withdrawal direction) and any debt payment link are removed first,
    then the new set is applied. The amount on each AllocationItem is always
    a positive magnitude — direction is inferred from the transaction's sign:
      - Credit (amount > 0) + goal → contribution (increases goal balance)
      - Debit  (amount < 0) + goal → withdrawal  (decreases goal balance)
      - Debit  (amount < 0) + debt → debt payment (decreases debt balance)
    Transfer-type transactions are rejected — they cannot hold allocations.

    Validation runs to completion BEFORE any state mutation, so a validation
    failure on the last item does not leave the database half-applied.
    """
    tx = db.query(models.Transaction).options(
        joinedload(models.Transaction.category)
    ).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if tx.transaction_type == "transfer":
        raise HTTPException(status_code=400, detail="Transfer transactions cannot have allocations")

    # ── PHASE 1: validate everything before touching state ─────────────────────
    for item in payload.allocations:
        if item.amount <= 0:
            raise HTTPException(status_code=400, detail="All allocation amounts must be positive")

    goal_items = [a for a in payload.allocations if a.kind == "goal"]
    debt_items = [a for a in payload.allocations if a.kind == "debt"]

    if len(debt_items) > 1:
        raise HTTPException(status_code=400, detail="A transaction can only be linked to one debt")

    if debt_items and tx.amount >= 0:
        raise HTTPException(status_code=400, detail="Only debit transactions can be linked to a debt payment")

    tx_abs = round(abs(tx.amount), 2)
    if payload.allocations:
        total = round(sum(a.amount for a in payload.allocations), 2)
        if total > tx_abs:
            raise HTTPException(
                status_code=400,
                detail=f"Total allocations ({total}) exceed transaction amount ({tx_abs})",
            )

    # Resolve goal/debt rows up front so 404s surface before any writes
    goals_by_ref = {}
    for item in goal_items:
        goal = db.query(models.SavingsGoal).filter(models.SavingsGoal.id == item.ref_id).first()
        if not goal:
            raise HTTPException(status_code=404, detail=f"Savings goal {item.ref_id} not found")
        goals_by_ref[item.ref_id] = goal

    debt_obj = None
    if debt_items:
        debt_obj = db.query(models.Debt).filter(models.Debt.id == debt_items[0].ref_id).first()
        if not debt_obj:
            raise HTTPException(status_code=404, detail=f"Debt {debt_items[0].ref_id} not found")
        if debt_obj.is_paid_off:
            raise HTTPException(status_code=400, detail="Debt is already paid off")

    # ── PHASE 2: unlink everything currently attached ──────────────────────────
    # Existing contributions can be either contribution-direction (positive amount)
    # or withdrawal-direction (negative). Reverse each according to its sign.
    existing_contribs = db.query(models.SavingsContribution).filter(
        models.SavingsContribution.transaction_id == tx_id,
    ).all()
    for contrib in existing_contribs:
        goal = db.query(models.SavingsGoal).filter(models.SavingsGoal.id == contrib.goal_id).first()
        if goal:
            if contrib.amount > 0:
                # Reverse a contribution → reduce goal back
                goal.current_amount = round(max(0.0, goal.current_amount - contrib.amount), 2)
                if goal.current_amount < goal.target_amount:
                    goal.is_completed = False
            else:
                # Reverse a withdrawal → restore goal
                goal.current_amount = round(goal.current_amount + abs(contrib.amount), 2)
        db.delete(contrib)

    if tx.debt_id is not None:
        payment = db.query(models.DebtPayment).filter(
            models.DebtPayment.transaction_id == tx_id
        ).first()
        if payment:
            debt = db.query(models.Debt).filter(models.Debt.id == tx.debt_id).first()
            if debt:
                debt.current_balance = round(debt.current_balance + payment.amount, 2)
                debt.is_paid_off = False
            db.delete(payment)
        tx.debt_id = None

    # Reset transaction type to a neutral baseline; phase 3 may upgrade it
    tx.transaction_type = "income" if tx.amount > 0 else "expense"

    # ── PHASE 3: apply the new allocations ─────────────────────────────────────
    is_withdrawal = tx.amount < 0  # debit transactions allocate to goals as withdrawals

    if goal_items:
        # Re-check goal completion status using the freshly-decremented current_amount
        # in case a goal had been set is_completed=True by the now-removed contribution
        for item in goal_items:
            goal = goals_by_ref[item.ref_id]
            # We may have just decremented this goal in phase 2; re-check completion
            # to give the user a clean error rather than silently skipping.
            if goal.is_completed and not is_withdrawal:
                raise HTTPException(
                    status_code=400,
                    detail=f"Savings goal '{goal.name}' is already completed",
                )

            if is_withdrawal:
                new_amount = round(max(0.0, goal.current_amount - item.amount), 2)
                goal.current_amount = new_amount
                if new_amount < goal.target_amount:
                    goal.is_completed = False
                signed_amount = -item.amount
            else:
                new_amount = round(goal.current_amount + item.amount, 2)
                goal.current_amount = new_amount
                if new_amount >= goal.target_amount:
                    goal.is_completed = True
                signed_amount = item.amount

            db.add(models.SavingsContribution(
                goal_id=item.ref_id,
                amount=signed_amount,
                balance_after=new_amount,
                transaction_id=tx_id,
            ))
        tx.transaction_type = "savings_transfer"

    if debt_items:
        item = debt_items[0]
        payment_amount = round(item.amount, 2)
        new_balance = round(max(0.0, debt_obj.current_balance - payment_amount), 2)
        debt_obj.current_balance = new_balance
        if new_balance == 0:
            debt_obj.is_paid_off = True
        db.add(models.DebtPayment(
            debt_id=item.ref_id,
            amount=payment_amount,
            balance_after=new_balance,
            notes=None,
            paid_at=tx.date,
            transaction_id=tx_id,
        ))
        tx.debt_id = item.ref_id
        tx.transaction_type = "debt_payment"

        # Auto-assign system "Debt Payment" category if the tx isn't already categorised
        # — parity with the legacy POST /{tx_id}/link-debt endpoint
        if tx.category_id is None:
            debt_cat = db.query(models.Category).filter(
                models.Category.name == "Debt Payment",
                models.Category.is_system == True,
            ).first()
            if debt_cat:
                tx.category_id = debt_cat.id

    db.commit()
    db.refresh(tx)
    return attach_allocations(tx, db)


@router.delete("/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    tx_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    tx = db.query(models.Transaction).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    # Reverse any linked balance effect and un-strand a transfer-pair sibling BEFORE
    # deleting, so money is never left orphaned on a debt/goal (AUDIT-06). This also
    # deletes the DebtPayment/SavingsContribution audit rows that reference this tx.
    _reverse_all_links_before_delete(tx, db)
    # ImportDraftRow.duplicate_of is a soft pointer, not a reversible balance effect —
    # just null it so the delete doesn't violate the FK.
    db.query(models.ImportDraftRow).filter(models.ImportDraftRow.duplicate_of == tx_id).update({"duplicate_of": None})
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

    if debt.is_paid_off or debt.current_balance <= 0:
        raise HTTPException(status_code=400, detail="Debt is already paid off")

    # Guard against double-recording (e.g. the tx was previously linked then unlinked
    # and re-linked while a stale DebtPayment still references it).
    existing = db.query(models.DebtPayment).filter(
        models.DebtPayment.transaction_id == tx_id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Transaction is already recorded as a payment")

    requested = round(abs(tx.amount), 2)
    # Record the EFFECTIVE applied delta, not the requested magnitude: an overpayment
    # can only reduce the balance to zero, so the audit row (and thus the unlink
    # reversal) must reflect what was actually applied (AUDIT-07). Otherwise unlink
    # over-credits the debt.
    payment_amount = round(min(requested, debt.current_balance), 2)
    new_balance = round(debt.current_balance - payment_amount, 2)

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
