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
from typing import List, Optional

import pandas as pd
import pdfplumber
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
    if not (str(target).startswith(str(base) + "/") or target == base):
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
        # Exclude transactions that have already been typed (e.g. debt_payment).
        # These should not be silently overwritten by a future bank import.
        models.Transaction.transaction_type == "expense",
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


def _find_existing_import(
    db: Session,
    account_id: int,
    bank_date,
    bank_amount: float,
    bank_desc: Optional[str],
) -> bool:
    """
    Returns True if an identical imported transaction already exists.
    Matches on account_id + date + amount + description (all four must match).
    Only checks source='import' transactions.
    """
    q = db.query(models.Transaction).filter(
        models.Transaction.account_id == account_id,
        models.Transaction.source == "import",
        models.Transaction.date == bank_date,
        models.Transaction.amount == bank_amount,
    )
    if bank_desc is not None:
        q = q.filter(models.Transaction.description == bank_desc)
    else:
        q = q.filter(models.Transaction.description.is_(None))
    return q.first() is not None


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


@router.get("/csv/preview")
def preview_csv(
    filename: str = Query(..., description="Relative path within financial data directory"),
    rows: int = Query(5, ge=1, le=50, description="Number of sample rows to return"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    """
    Return column names and a sample of rows from a CSV file.
    Use before importing to confirm column mapping — identical shape to PDF preview.
    """
    file_path = _safe_path(filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        df = pd.read_csv(file_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse CSV: {exc}")

    prev_log = (
        db.query(models.ImportLog)
        .filter(
            models.ImportLog.filename == filename,
            models.ImportLog.user_id == current_user.id,
        )
        .order_by(models.ImportLog.imported_at.desc())
        .first()
    )

    return {
        "columns": list(df.columns),
        "sample_rows": df.head(rows).fillna("").to_dict(orient="records"),
        "total_rows": len(df),
        "previously_imported": prev_log is not None,
        "last_import_at": prev_log.imported_at.isoformat() if prev_log else None,
    }


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
    amount_col: Optional[str] = Query(None, description="Single signed amount column (mutually exclusive with credit_col/debit_col)"),
    credit_col: Optional[str] = Query(None, description="Credit column for split credit/debit format (e.g. ING Australia)"),
    debit_col: Optional[str] = Query(None, description="Debit column for split credit/debit format (e.g. ING Australia)"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    """
    Import transactions from a CSV bank statement.

    Supports two amount formats:
    - Single column: provide `amount_col` (signed value, credits positive)
    - Split columns: provide both `credit_col` and `debit_col`; combined amount =
      (credit or 0) - (debit or 0), producing a signed value where credits are positive.
      This matches the ING Australia CSV export format (Date, Description, Credit, Debit, Balance).
    """
    # Validate amount mode — must provide either amount_col or both credit_col + debit_col
    split_mode = credit_col is not None and debit_col is not None
    single_mode = amount_col is not None
    if not split_mode and not single_mode:
        raise HTTPException(
            status_code=422,
            detail="Provide either amount_col (single column) or both credit_col and debit_col (split format).",
        )
    if split_mode and single_mode:
        raise HTTPException(
            status_code=422,
            detail="Provide either amount_col or credit_col/debit_col — not both.",
        )

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

    # Validate that the required columns exist in the file
    if split_mode:
        required_cols = [date_col, desc_col, credit_col, debit_col]
    else:
        required_cols = [date_col, desc_col, amount_col]

    missing = [c for c in required_cols if c not in df.columns]
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
    skipped_count = 0
    errors = []
    amount_diff_warnings: list[schemas.MatchWarning] = []

    def _parse_split_amount(val) -> float:
        """Parse a credit or debit cell value; treats empty/NaN as 0."""
        if val is None:
            return 0.0
        s = str(val).strip()
        if s == '' or s.lower() == 'nan':
            return 0.0
        return float(s.replace(',', '').replace('$', ''))

    for _, row in df.iterrows():
        try:
            bank_date = pd.to_datetime(row[date_col]).date()
            bank_desc = str(row[desc_col]) if pd.notna(row[desc_col]) else None

            if split_mode:
                # ING-style: Credit and Debit are separate columns; one will be empty per row.
                # Use abs(debit) so this works whether the bank exports debits as positive or
                # already-negative values (ING exports debit as e.g. -200.00, not 200.00).
                credit = _parse_split_amount(row[credit_col])
                debit  = _parse_split_amount(row[debit_col])
                bank_amount = credit - abs(debit)
            else:
                bank_amount = float(row[amount_col])

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
                # No manual match → check for duplicate before inserting
                if _find_existing_import(db, account_id, bank_date, bank_amount, bank_desc):
                    skipped_count += 1
                else:
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
        skipped_duplicates=skipped_count,
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


def _extract_pdf_dataframe(file_path: Path) -> pd.DataFrame:
    """
    Extract transaction tables from a PDF bank statement into a single DataFrame.

    Handles two PDF table layouts:

    1. Standard layout (most banks): one or more multi-row tables per page.
       Selects the largest table by row count to skip header/summary tables,
       then concatenates all pages dropping repeated header rows.

    2. Row-per-table layout (Virgin Money): each transaction is rendered as its
       own 1-row table by pdfplumber. Detected when single-row tables vastly
       outnumber multi-row tables. Flattens by finding the dominant column count,
       identifying the repeating header row (most common row value), and
       concatenating all matching data rows.
    """
    try:
        with pdfplumber.open(file_path) as pdf:
            tables = []
            for page in pdf.pages:
                for table in page.extract_tables():
                    if table:
                        tables.append(table)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not open PDF: {exc}")

    if not tables:
        raise HTTPException(
            status_code=422,
            detail="No tables found in PDF. Tally can only import PDFs that contain structured tables.",
        )

    # Detect row-per-table layout: many 1-row tables, few multi-row tables.
    # Threshold: single-row tables outnumber multi-row tables by more than 3:1
    # (or there are at least 4 single-row tables and no significant multi-row tables).
    single_row = [t for t in tables if len(t) == 1]
    multi_row = [t for t in tables if len(t) > 1]

    if len(single_row) > max(len(multi_row) * 2, 3):
        # Row-per-table layout: flatten all 1-row tables with the dominant column count.
        from collections import Counter

        col_counts = Counter(len(t[0]) for t in single_row if t)
        if not col_counts:
            raise HTTPException(status_code=422, detail="PDF tables contained no data rows.")
        target_cols = col_counts.most_common(1)[0][0]
        candidates = [t for t in single_row if t and len(t[0]) == target_cols]

        # The header row repeats across sections — it's the most frequently seen row.
        row_counter = Counter(
            tuple(str(c).strip() if c else "" for c in t[0]) for t in candidates
        )
        header_tuple = row_counter.most_common(1)[0][0]
        headers = list(header_tuple)

        rows = []
        for t in candidates:
            row = [str(c).strip() if c is not None else "" for c in t[0]]
            if tuple(row) != header_tuple:
                rows.append(row)

        if not rows:
            raise HTTPException(status_code=422, detail="PDF tables contained no data rows.")
        return pd.DataFrame(rows, columns=headers)

    # Standard layout: select the largest table by data row count (excluding the header row).
    # On multi-page PDFs the first table is often an account summary, not transactions.
    largest_table = max(tables, key=lambda t: len(t) - 1)

    # Use the largest table's first row as headers; drop repeated header rows from other tables.
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(largest_table[0])]
    rows = []
    for table in tables:
        for row in table[1:]:  # skip header row of each table
            if row != largest_table[0]:  # drop repeated header rows from subsequent pages
                rows.append([str(c).strip() if c is not None else "" for c in row])

    if not rows:
        raise HTTPException(status_code=422, detail="PDF tables contained no data rows.")

    return pd.DataFrame(rows, columns=headers)


@router.get("/pdf/preview")
def preview_pdf(
    filename: str = Query(..., description="Relative path within financial data directory"),
    rows: int = Query(5, ge=1, le=50, description="Number of sample rows to return"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    """
    Extract tables from a PDF and return the column names plus a sample of rows.
    Use this before committing an import to confirm column mapping is correct.
    """
    file_path = _safe_path(filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    df = _extract_pdf_dataframe(file_path)

    prev_log = (
        db.query(models.ImportLog)
        .filter(
            models.ImportLog.filename == filename,
            models.ImportLog.user_id == current_user.id,
        )
        .order_by(models.ImportLog.imported_at.desc())
        .first()
    )

    return {
        "columns": list(df.columns),
        "sample_rows": df.head(rows).to_dict(orient="records"),
        "total_rows": len(df),
        "previously_imported": prev_log is not None,
        "last_import_at": prev_log.imported_at.isoformat() if prev_log else None,
    }


@router.post(
    "/pdf",
    response_model=schemas.ReconciliationSummary,
    status_code=status.HTTP_201_CREATED,
)
def import_pdf(
    filename: str = Query(..., description="Relative path within financial data directory"),
    account_id: int = Query(...),
    date_col: str = Query("Date"),
    desc_col: str = Query("Description"),
    amount_col: str = Query("Amount"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_owner),
):
    """
    Import transactions from a PDF bank statement.
    Uses the same reconciliation algorithm as CSV import.
    Call GET /api/import/pdf/preview first to confirm column names.
    """
    account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    file_path = _safe_path(filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    df = _extract_pdf_dataframe(file_path)

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
        file_type="pdf",
        status="success",
    )
    db.add(log)
    db.flush()

    matched_count = 0
    new_count = 0
    skipped_count = 0
    errors = []
    amount_diff_warnings: list[schemas.MatchWarning] = []

    def _parse_pdf_amount(val) -> float:
        """
        Parse a bank statement amount string into a signed float.

        Handles three formats:
        - Signed numeric:       '-159.20' or '2000.00'
        - Dollar with commas:   '$1,234.56' or '-$1,234.56'
        - Cr/Dr suffix (Virgin Money style): '$2,000.00 Cr' → +2000.00
                                             '$91.34 Dr'    → -91.34
        Credits (Cr) are positive; debits (Dr) are negative.
        """
        s = str(val).strip()
        # Detect and strip Cr/Dr suffix before any other processing
        is_credit = s.lower().endswith(" cr") or s.lower().endswith("cr")
        is_debit  = s.lower().endswith(" dr") or s.lower().endswith("dr")
        if is_credit or is_debit:
            s = s[:-2].strip()  # remove the two-char suffix
        # Strip currency symbols and thousands separators
        s = s.replace("$", "").replace(",", "").strip()
        amount = float(s)
        if is_debit:
            amount = -abs(amount)
        elif is_credit:
            amount = abs(amount)
        return amount

    for _, row in df.iterrows():
        try:
            bank_date   = pd.to_datetime(row[date_col]).date()
            bank_amount = _parse_pdf_amount(row[amount_col])
            bank_desc   = str(row[desc_col]) if row[desc_col] != "" else None

            match = _find_match(db, account_id, bank_date, bank_amount)

            if match:
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

                match.amount        = bank_amount
                match.is_verified   = True
                match.import_log_id = log.id
                matched_count += 1

            else:
                # No manual match → check for duplicate before inserting
                if _find_existing_import(db, account_id, bank_date, bank_amount, bank_desc):
                    skipped_count += 1
                else:
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

    estimates_pending = db.query(models.Transaction).filter(
        models.Transaction.account_id == account_id,
        models.Transaction.is_verified == False,
        models.Transaction.source == "manual",
    ).count()

    return schemas.ReconciliationSummary(
        matched_count=matched_count,
        new_from_bank_count=new_count,
        skipped_duplicates=skipped_count,
        estimates_pending=estimates_pending,
        amount_diff_warnings=amount_diff_warnings,
        import_log=log,
    )
