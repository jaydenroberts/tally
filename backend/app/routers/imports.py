"""
Import router — reads financial files from the read-only mount and imports
transactions into SQLite. Originals are never modified.

Matching algorithm
------------------
When a bank import row arrives, Tally looks for an existing *manual* (unverified)
transaction in the same account that:
  - Has a date within ±3 days of the bank date
  - Has an amount within 15% (or $1, whichever is larger) of the bank amount
If multiple candidates exist, the closest amount wins.

On match:
  - The bank amount overwrites the manual amount (bank is source of truth)
  - original_amount records what the user estimated
  - match_note records the delta if amounts differ
  - is_verified is set to True, source stays 'manual' (to preserve user category/notes)

No match:
  - A new transaction is created with source='import', is_verified=True
"""
import os
from datetime import timedelta
from pathlib import Path
from typing import List

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, require_owner

FINANCIAL_DATA_PATH = os.getenv("FINANCIAL_DATA_PATH", "/financial-data")
MATCH_DATE_WINDOW_DAYS = 3
MATCH_AMOUNT_TOLERANCE_PCT = 0.15
MATCH_AMOUNT_TOLERANCE_MIN = 1.00   # always allow $1 variance regardless of %

router = APIRouter(prefix="/api/import", tags=["imports"])


def _safe_path(filename: str) -> Path:
    base = Path(FINANCIAL_DATA_PATH).resolve()
    target = (base / filename).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid file path")
    return target


def _find_match(
    db: Session,
    account_id: int,
    bank_date,
    bank_amount: float,
) -> models.Transaction | None:
    """
    Find the best-matching unverified manual transaction for a bank row.
    Returns None if no acceptable match exists.
    """
    window_start = bank_date - timedelta(days=MATCH_DATE_WINDOW_DAYS)
    window_end   = bank_date + timedelta(days=MATCH_DATE_WINDOW_DAYS)

    candidates = db.query(models.Transaction).filter(
        models.Transaction.account_id == account_id,
        models.Transaction.source == "manual",
        models.Transaction.is_verified == False,
        models.Transaction.date >= window_start,
        models.Transaction.date <= window_end,
    ).all()

    tolerance = max(abs(bank_amount) * MATCH_AMOUNT_TOLERANCE_PCT, MATCH_AMOUNT_TOLERANCE_MIN)

    valid = [
        c for c in candidates
        if abs(c.amount - bank_amount) <= tolerance
    ]
    if not valid:
        return None

    # Closest amount wins; ties broken by closest date
    return min(valid, key=lambda c: (abs(c.amount - bank_amount), abs((c.date - bank_date).days)))


@router.get("/files")
def list_importable_files(_: models.User = Depends(require_owner)):
    base = Path(FINANCIAL_DATA_PATH)
    if not base.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Financial data path not mounted: {FINANCIAL_DATA_PATH}",
        )
    files = []
    for ext in ("*.csv", "*.CSV", "*.pdf", "*.PDF"):
        for f in sorted(base.rglob(ext)):
            files.append({
                "filename": str(f.relative_to(base)),
                "size_bytes": f.stat().st_size,
                "file_type": f.suffix.lower().lstrip("."),
            })
    return files


@router.post(
    "/csv",
    response_model=schemas.ReconciliationSummary,
    status_code=status.HTTP_201_CREATED,
)
def import_csv(
    filename: str = Query(..., description="Relative path within financial data directory"),
    account_id: int = Query(...),
    date_col: str = Query("Date"),
    desc_col: str = Query("Description"),
    amount_col: str = Query("Amount"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    file_path = _safe_path(filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        df = pd.read_csv(file_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse CSV: {exc}")

    missing = [c for c in (date_col, desc_col, amount_col) if c not in df.columns]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Columns not found: {missing}. Available: {list(df.columns)}",
        )

    log = models.ImportLog(
        user_id=current_user.id,
        filename=filename,
        file_path=str(file_path),
        file_type="csv",
        status="success",
    )
    db.add(log)
    db.flush()

    matched_count = 0
    new_count = 0
    errors = []
    amount_diff_warnings: list[schemas.MatchWarning] = []

    for _, row in df.iterrows():
        try:
            bank_date   = pd.to_datetime(row[date_col]).date()
            bank_amount = float(row[amount_col])
            bank_desc   = str(row[desc_col]) if pd.notna(row[desc_col]) else None

            match = _find_match(db, account_id, bank_date, bank_amount)

            if match:
                # Bank overwrites the manual estimate
                manual_amount = match.amount
                if abs(manual_amount - bank_amount) > 0.005:
                    match.match_note = (
                        f"Matched import; amount updated "
                        f"{manual_amount:+.2f} → {bank_amount:+.2f}"
                    )
                    amount_diff_warnings.append(schemas.MatchWarning(
                        transaction_id=match.id,
                        description=match.description or bank_desc,
                        manual_amount=manual_amount,
                        bank_amount=bank_amount,
                    ))
                    match.original_amount = manual_amount
                else:
                    match.match_note = "Matched import; amounts agreed"

                match.amount      = bank_amount
                match.is_verified = True
                match.import_log_id = log.id
                # Keep source='manual' so user category/notes are preserved
                matched_count += 1

            else:
                # No manual match → create a new verified import transaction
                tx = models.Transaction(
                    account_id=account_id,
                    date=bank_date,
                    description=bank_desc,
                    amount=bank_amount,
                    source="import",
                    is_verified=True,
                    import_log_id=log.id,
                )
                db.add(tx)
                new_count += 1

        except Exception as exc:
            errors.append(str(exc))

    log.transaction_count = matched_count + new_count
    if errors:
        log.status = "partial"
        log.error_detail = "; ".join(errors[:10])

    db.commit()
    db.refresh(log)

    # Count remaining unverified manual entries for this account
    estimates_pending = db.query(models.Transaction).filter(
        models.Transaction.account_id == account_id,
        models.Transaction.is_verified == False,
        models.Transaction.source == "manual",
    ).count()

    return schemas.ReconciliationSummary(
        matched_count=matched_count,
        new_from_bank_count=new_count,
        estimates_pending=estimates_pending,
        amount_diff_warnings=amount_diff_warnings,
        import_log=log,
    )


@router.get("/logs", response_model=List[schemas.ImportLogResponse])
def list_import_logs(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    return db.query(models.ImportLog).order_by(models.ImportLog.imported_at.desc()).all()
