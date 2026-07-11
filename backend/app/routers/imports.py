"""
Staged-import router — CSV / PDF upload → preview → commit → optional rollback.

Replaces the legacy file-based import endpoints (v1.3.x) with a wizard flow:
  POST   /api/imports              upload CSV or PDF → create draft in preview_ready state
  GET    /api/imports/:id/preview  fetch draft rows + dedup flags
  PATCH  /api/imports/:id          update column mapping or row decisions
  POST   /api/imports/:id/commit   TOCTOU-safe status transition → write transactions
  POST   /api/imports/:id/rollback undo within IMPORT_ROLLBACK_WINDOW_SECONDS
  DELETE /api/imports/:id          cancel a preview_ready draft
  GET    /api/imports              import history with rollback_available flag

Security notes:
  BASTION-3: MIME validation by parser result, not Content-Type header
  BASTION-4: IMPORT_DRAFTS_ENABLED gate returns 404 (not 401) when off
  BASTION-5: TOCTOU-safe transitions via UPDATE WHERE status=$expected + rowcount check
  BASTION-8: Stuck 'committing' drafts recovered to 'preview_ready' on startup
  BASTION-9: db.flush() before re-reading draft after TOCTOU UPDATE
  BASTION-11: file.filename sanitised at ingest
  MASON-2:   amount dedup uses round(float(x), 2) to avoid Decimal/Float IEEE 754 mismatch
  MASON-3:   WRatio scorer acceptable; adjacent-day same-amount dedup is conservative by design
  MASON-4:   column_mapping validated via ColumnMappingSchema at intake
  Option B:  PDF dispatch via import_parsers.pdf_parser (worker-process, 30s wall-clock kill)
"""
import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from rapidfuzz import fuzz
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import require_owner
from ..database import get_db
from ..import_parsers import csv_parser, pdf_parser

IMPORT_DRAFTS_ENABLED = os.getenv("IMPORT_DRAFTS_ENABLED", "true").lower() == "true"
IMPORT_ROLLBACK_WINDOW_SECONDS = int(os.getenv("IMPORT_ROLLBACK_WINDOW_SECONDS", "300"))
MAX_UPLOAD_BYTES = 10 * 1024 * 1024   # 10 MB
DRAFT_TTL_HOURS = 24
DEDUP_SCORE_THRESHOLD = 0.85
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._\- ]")

# FE-012 — reconciliation matcher (ported from v1.3.2, amended by Advisory A2/A6/A7).
MATCH_DATE_WINDOW_DAYS     = 3
MATCH_AMOUNT_TOLERANCE_PCT = 0.15
MATCH_AMOUNT_TOLERANCE_MIN = 1.00    # always allow a $1 variance
MATCH_AMOUNT_TOLERANCE_MAX = 15.00   # A7: cap so big-ticket estimates can't match wildly
# A6: only sign-aware expense/income manual estimates are matchable. Transfers and
# debt-linked typed rows carry linked records and are deliberately excluded.
MATCH_TYPES = ("expense", "income")

# BACKLOG-036 — merchant-confidence tiers. token_set_ratio returns 0-100; we
# divide by 100.0 so these thresholds live on a 0-1 scale (spec §12.2).
MATCH_MERCHANT_HIGH  = 0.80   # comparable & score >= HIGH → Confident (auto-reconcile)
MATCH_MERCHANT_FLOOR = 0.50   # comparable & FLOOR <= score < HIGH → Review;
                              # comparable & score < FLOOR → None (cross-merchant, reject);
                              # not-comparable (boilerplate either side) → Review regardless

# AU-bank boilerplate carrying no merchant identity — TUNABLE (spec §4.1).
GENERIC_TOKENS = {
    "direct", "debit", "credit", "purchase", "eftpos", "withdrawal",
    "deposit", "transfer", "reversal", "receipt", "payment", "card", "pos",
}
_RECEIPT_RE = re.compile(r"\breceipt\b.*$", re.I)   # drop "- Receipt 12345 ..." tail
# Drop the "<payment-method> Purchase" segment structurally (e.g. card-network or
# eftpos purchase labels) so the network word never survives into the residual and is
# never named literally in source. The leading method word + "purchase" go together.
_METHOD_RE  = re.compile(r"\b\w+\s+purchase\b", re.I)
_NONWORD_RE = re.compile(r"[^a-z0-9 ]+")

# Perf sanity (spec §12.6): log if a single row survives the structural gate
# against more than this many candidates. Fuzzy scoring is cheap; this just
# documents the expected bound.
MATCH_FANOUT_WARN = 50

router = APIRouter(prefix="/imports", tags=["imports"])


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a stored datetime to tz-aware UTC (FE-003).

    Persisted ``committed_at`` values are naive UTC (SQLite has no tz support).
    Naive values are interpreted as UTC and stamped with ``timezone.utc`` so the
    Pydantic response serializes with a ``+00:00`` offset and all window
    comparisons are aware-vs-aware. Already-aware values are converted to UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _require_enabled():
    # BASTION-4: 404 (not 401) when feature flag is off — reveals nothing to caller
    if not IMPORT_DRAFTS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")


def _sanitise_filename(raw: str) -> str:
    # BASTION-11: strip unsafe chars, truncate to 255
    safe = SAFE_FILENAME_RE.sub("_", raw or "upload")
    return safe[:255] or "upload"


def _detect_account_last4(raw_lines: list[str]) -> Optional[str]:
    """Scan first ~5 lines for a masked-account number — naive matching hint.

    LOW (imports.py last4): require a 6+ digit run so a bare 4-digit year
    ("2026") or a "20/04/2026" date token can't masquerade as an account tail.
    Real account/card numbers are always longer than 4 digits; statement dates
    are 4-digit years. We also skip any digit-run inside an obvious date pattern.
    """
    date_like = re.compile(r"\d{1,4}[/\-]\d{1,2}[/\-]\d{1,4}")
    for line in raw_lines[:5]:
        scrubbed = date_like.sub(" ", line)          # remove dd/mm/yyyy style tokens
        m = re.search(r"\b\d{6,}\b", scrubbed)        # need 6+ digits to be an account
        if m:
            return m.group(0)[-4:]
    return None


# Date formats accepted by _normalise_date — first match wins.
# ISO first for already-clean upstream paths; AU formats for PDF imports
# (v1.3.2 used "%d/%m/%Y"; some credit-card statements emit "%d/%m/%y").
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d-%m-%y",
)

# Cr/Dr suffix detector — case-insensitive. Captures the suffix so we can apply sign.
_CR_DR_SUFFIX_RE = re.compile(r"\s*(cr|dr)\s*$", re.IGNORECASE)

# Accounting parens-negative — "(1234.56)" or "($1,234.56)".
_PARENS_RE = re.compile(r"^\((.*)\)$")

# AUDIT-05/AUDIT-09 — structured match_note header. On reconcile we overwrite a
# manual estimate's amount (and now its date, A9) with the bank row's. To let a
# re-imported statement dedup against that row (A5), and to preserve the estimate's
# original date for provenance (A9), we stamp the bank row's identity into match_note
# as a machine-parseable first line, followed by the existing human-readable note.
_MATCH_META_PREFIX = "[recon]"
_MATCH_META_RE = re.compile(
    r"^\[recon\]\s+bankdesc=(?P<bankdesc>.*?)\tbankdate=(?P<bankdate>\S*)\testdate=(?P<estdate>\S*)"
    r"(?:\s+\|\s+(?P<human>.*))?$",
    re.DOTALL,
)


def _make_match_note(*, bank_desc, bank_date, est_date, human: str) -> str:
    """Build a match_note carrying the reconciled bank row's identity + the estimate's
    original date, so dedup (A5) and provenance (A9) work without new columns."""
    bd = (bank_desc or "").replace("\t", " ").replace("\n", " ")
    bank_date_s = bank_date.isoformat() if bank_date else ""
    est_date_s = est_date.isoformat() if est_date else ""
    return (
        f"{_MATCH_META_PREFIX} bankdesc={bd}\tbankdate={bank_date_s}\testdate={est_date_s}"
        f" | {human}"
    )


def _parse_match_note(note):
    """Extract {bank_desc, bank_date, est_date, human} from a structured match_note,
    or None if the note is absent/legacy/unstructured."""
    if not note:
        return None
    m = _MATCH_META_RE.match(note)
    if not m:
        return None
    return {
        "bank_desc": m.group("bankdesc") or "",
        "bank_date": _normalise_date(m.group("bankdate")),
        "est_date": _normalise_date(m.group("estdate")),
        "human": m.group("human") or "",
    }


def _normalise_amount(raw):
    """Convert a raw cell string into a Decimal, or None on parse failure.

    Handles:
      "1234.56"          → Decimal("1234.56")
      "$1,234.56"        → Decimal("1234.56")        (strips $ and ,)
      "-1234.56"         → Decimal("-1234.56")
      "$48.56 Dr"        → Decimal("-48.56")          (Dr → negative)
      "$215.00 Cr"       → Decimal("215.00")          (Cr → positive)
      "$1,234.56 cr"     → Decimal("1234.56")         (case-insensitive)
      "(1234.56)"        → Decimal("-1234.56")        (accounting parens-negative)
      "($48.56)"         → Decimal("-48.56")
      None / empty / unparseable → None

    Convention: Cr = positive, Dr = negative — matches v1.3.2 split-CSV
    `credit - abs(debit)` semantic. Universal for both ledger accounts
    (credit deposits in) and credit-card accounts (Cr payments reduce
    balance owing).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    sign = 1

    # 1. Cr/Dr suffix → strip, set sign.
    m = _CR_DR_SUFFIX_RE.search(s)
    if m:
        suffix = m.group(1).lower()
        s = _CR_DR_SUFFIX_RE.sub("", s).strip()
        if suffix == "dr":
            sign = -1
        # cr → positive (sign stays +1)

    # 2. Accounting parens → strip, force negative.
    pm = _PARENS_RE.match(s)
    if pm:
        s = pm.group(1).strip()
        sign = -1

    # 3. Strip $ and , — anywhere in the string.
    s = s.replace("$", "").replace(",", "").strip()

    if not s:
        return None

    try:
        value = Decimal(s)
    except (InvalidOperation, ValueError):
        return None

    # AUDIT-03: apply the detected sign as -abs(value), never a bare negation.
    # A Dr suffix or accounting parens means "this is negative" — if the numeric
    # body ALSO carried a "-" (e.g. "-48.56 Dr" or "(-48.56)"), a bare `-value`
    # double-negates back to positive, booking a debit as income. Force the
    # magnitude negative instead so sign detection is idempotent.
    if sign == -1:
        value = -abs(value)
    return value


def _normalise_date(raw):
    """Parse a date string against a small set of accepted formats.

    Order: ISO ("%Y-%m-%d"), AU full-year ("%d/%m/%Y"), AU short-year
    ("%d/%m/%y"), AU dash full-year, AU dash short-year. First match wins;
    returns None on no match or empty input.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _cell_at(raw_row: list[str], idx) -> Optional[Decimal]:
    """Normalise the cell at ``idx`` to a Decimal, or None if out of range/blank/unparseable."""
    if idx is None:
        return None
    try:
        if idx < len(raw_row):
            return _normalise_amount(raw_row[idx])
    except (IndexError, TypeError):
        pass
    return None


def _apply_mapping(raw_row: list[str], mapping: dict) -> tuple:
    """Extract date/description/amount from a raw row given column_mapping.

    Amount resolution (FE-001):
      * If a ``credit`` and/or ``debit`` index is mapped, amount =
        ``credit - abs(debit)``, treating a missing/blank/unparseable cell as 0.
        Cr is positive, Dr is negative — matches the ``_normalise_amount``
        convention and the v1.3.2 split-CSV semantic.
      * Otherwise fall back to the single signed ``amount`` column (no change
        from prior behaviour for single-column files).
    """
    try:
        raw_date = raw_row[mapping["date"]] if mapping.get("date") is not None else None
        row_date = _normalise_date(raw_date) if raw_date else None
    except (IndexError, KeyError):
        row_date = None

    try:
        desc_idx = mapping.get("description")
        row_desc = raw_row[desc_idx] if desc_idx is not None and desc_idx < len(raw_row) else None
    except (IndexError, KeyError):
        row_desc = None

    credit_idx = mapping.get("credit")
    debit_idx = mapping.get("debit")

    if credit_idx is not None or debit_idx is not None:
        # Split credit/debit path. Missing/blank cells count as 0 so a row that
        # carries only a debit (or only a credit) still resolves to a value.
        credit = _cell_at(raw_row, credit_idx)
        debit = _cell_at(raw_row, debit_idx)
        if credit is None and debit is None:
            row_amount = None
        else:
            row_amount = (credit or Decimal(0)) - abs(debit or Decimal(0))
    else:
        try:
            amt_idx = mapping.get("amount")
            row_amount = (
                _normalise_amount(raw_row[amt_idx])
                if amt_idx is not None and amt_idx < len(raw_row)
                else None
            )
        except (IndexError, KeyError):
            row_amount = None

    return row_date, row_desc, row_amount


def _guess_mapping(header: list[str]) -> dict:
    """Best-effort column mapping from header names.

    Recognises separate Credit/Debit columns (common in AU bank CSVs) and
    never maps a Balance column as the transaction amount — both were silent
    failure modes that surfaced real debits as $0 or as running balances.
    Falls back to positional defaults when headers are unrecognised.
    """
    lower = [(h or "").strip().lower() for h in header]

    def find(keywords, exclude=()):
        for i, h in enumerate(lower):
            if any(k in h for k in keywords) and not any(x in h for x in exclude):
                return i
        return None

    date_idx   = find(["date"])
    desc_idx   = find(["description", "narrative", "detail", "particular", "memo", "reference"])
    credit_idx = find(["credit", "money in", "deposit", "paid in"])
    debit_idx  = find(["debit", "money out", "withdraw", "paid out"])
    amount_idx = find(["amount", "value"], exclude=["balance"])

    mapping = {
        "date": date_idx if date_idx is not None else 0,
        "description": desc_idx if desc_idx is not None else 1,
    }
    if credit_idx is not None or debit_idx is not None:
        # Separate money-in / money-out columns → credit - abs(debit).
        mapping["credit"] = credit_idx
        mapping["debit"] = debit_idx
        mapping["amount"] = None
    else:
        # Single signed amount column; avoid Balance, fall back to col 2.
        mapping["amount"] = amount_idx if amount_idx is not None else 2
        mapping["credit"] = None
        mapping["debit"] = None
    return mapping


def _dedup_row(
    db: Session, account_id: int, row_date, row_amount, row_desc
) -> tuple[Optional[int], Optional[float]]:
    """
    Find a matching committed transaction for dedup purposes.
    Rules: same account, exact amount (rounded float — MASON-2), ±1 day, WRatio ≥ 0.85.
    Returns (tx_id, score) or (None, None).
    Adjacent-day same-amount same-description matches are conservative by design (MASON-3).

    FE-012: pristine manual estimates (source='manual', unverified, import_id NULL) are
    deliberately NOT dedup candidates — they are the reconciliation matcher's job. If
    dedup flagged them the bank row would auto-exclude and the estimate would never get
    confirmed. Dedup therefore only guards against re-importing an already-recorded row.
    """
    if row_date is None or row_amount is None or not row_desc:
        return None, None

    # MASON-2: compare as rounded floats to avoid Decimal/Float IEEE 754 mismatch
    target_amount = round(float(row_amount), 2)

    candidates = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.account_id == account_id,
            models.Transaction.date >= row_date - timedelta(days=1),
            models.Transaction.date <= row_date + timedelta(days=1),
            # Exclude pristine manual estimates (matcher territory, not dedup).
            ~(
                (models.Transaction.source == "manual")
                & (models.Transaction.is_verified == False)   # noqa: E712
                & (models.Transaction.import_id.is_(None))
            ),
        )
        .all()
    )

    for c in candidates:
        if round(float(c.amount), 2) != target_amount:
            continue
        # AUDIT-05: a reconciled estimate keeps source='manual' with the bank amount,
        # but its description/date are the user's original estimate — so a re-imported
        # statement row (which carries the BANK desc/date) would never dedup against it
        # and would double-count. If this candidate was reconciled, compare against the
        # stored bank description; fall back to the visible desc for un-reconciled rows.
        meta = _parse_match_note(getattr(c, "match_note", None))
        compare_desc = c.description or ""
        if meta is not None and meta.get("bank_desc"):
            compare_desc = meta["bank_desc"]
        score = fuzz.WRatio(row_desc, compare_desc) / 100.0
        if score >= DEDUP_SCORE_THRESHOLD:
            return c.id, score

    return None, None


def _merchant_residual(desc: Optional[str]) -> str:
    """Strip AU-bank boilerplate + receipt IDs, leaving the merchant identity (spec §4.1).

    Examples:
      "ZORPCO MART - Card Purchase - Receipt 133767"     → "zorpco mart"
      "Direct Debit"                                     → ""   (pure boilerplate)
      "RAA - Direct Debit - Receipt 102895"             → "raa"

    An empty residual means there is no merchant identity to compare → the pair can
    never be Confident (the comparable guard in _compute_match_plan enforces this).
    """
    if not desc:
        return ""
    s = _RECEIPT_RE.sub("", desc.lower())
    s = _METHOD_RE.sub(" ", s)          # drop "<method> purchase" (incl. the network word)
    s = _NONWORD_RE.sub(" ", s)
    toks = [t for t in s.split() if t not in GENERIC_TOKENS and not t.isdigit()]
    return " ".join(toks)


def _amount_tolerance(bank_amount: float) -> float:
    """A7 tolerance: min(max(|amount|*15%, $1), $15)."""
    return min(
        max(abs(bank_amount) * MATCH_AMOUNT_TOLERANCE_PCT, MATCH_AMOUNT_TOLERANCE_MIN),
        MATCH_AMOUNT_TOLERANCE_MAX,
    )


def _passes_structural_gate(
    candidate: models.Transaction, account_id: int, bank_date, bank_amount: float
) -> bool:
    """The full structural gate for a (bank_row, candidate) pair (spec §4.2 + §12.1.3).

    Same account; candidate pristine (manual / unverified / import_id NULL / typed
    expense|income); date within ±window; SIGNED amount within tolerance. Used both
    when building the plan and re-checked at apply time against the live candidate.
    """
    if bank_date is None or bank_amount is None:
        return False
    if candidate.account_id != account_id:
        return False
    if candidate.source != "manual":
        return False
    if candidate.is_verified:
        return False
    if candidate.import_id is not None:
        return False
    if candidate.transaction_type not in MATCH_TYPES:
        return False
    if abs((candidate.date - bank_date).days) > MATCH_DATE_WINDOW_DAYS:
        return False
    cand_amount = float(candidate.amount)
    # LOW (cross-sign sub-$1): the $1 tolerance floor otherwise lets a +$0.50 estimate
    # match a -$0.50 bank row (|diff| = $1.00). An income estimate must never reconcile
    # against an expense debit (or vice-versa) — require the same sign. Zero on either
    # side is treated as sign-compatible (a $0 row carries no direction).
    if cand_amount and bank_amount and (cand_amount > 0) != (bank_amount > 0):
        return False
    if abs(cand_amount - bank_amount) > _amount_tolerance(bank_amount):
        return False
    return True


class MatchPlanEntry:
    """One row's planned reconciliation (Confident or Review). Plain object — never
    persisted; rebuilt deterministically at preview and at commit (spec §4.5)."""
    __slots__ = (
        "row_id", "candidate_id", "score", "tier", "comparable",
        "candidate_desc", "candidate_amount", "candidate_date",
        "bank_desc", "bank_amount", "bank_date",
    )

    def __init__(self, *, row_id, candidate_id, score, tier, comparable,
                 candidate_desc, candidate_amount, candidate_date,
                 bank_desc, bank_amount, bank_date):
        self.row_id = row_id
        self.candidate_id = candidate_id
        self.score = score
        self.tier = tier               # "confident" | "review"
        self.comparable = comparable
        self.candidate_desc = candidate_desc
        self.candidate_amount = candidate_amount
        self.candidate_date = candidate_date
        self.bank_desc = bank_desc
        self.bank_amount = bank_amount
        self.bank_date = bank_date


def _compute_match_plan(
    db: Session, draft: models.ImportDraft
) -> dict[int, MatchPlanEntry]:
    """Pure, read-only global best-first one-to-one assignment (spec §3, §4.3, §12.1.1).

    Returns {row_id → MatchPlanEntry} for every ready (non-excluded) bank row that the
    planner assigns a candidate to. Rows tier None (cross-merchant or no candidate) are
    absent from the dict — the caller imports them as new.

    Read-only contract (spec §12.5): performs NO db.add / attribute mutation. The
    candidate query is materialised with .all() up front so a later apply loop's writes
    can never feed back into the plan via autoflush (spec §12.1.1).
    """
    # Pull every pristine candidate on this account ONCE. Per-pair date/amount/merchant
    # gating happens in Python so the plan is a single read against a stable snapshot.
    candidates = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.account_id == draft.account_id,
            models.Transaction.source == "manual",
            models.Transaction.is_verified == False,   # noqa: E712 (SQL boolean)
            models.Transaction.import_id.is_(None),
            models.Transaction.transaction_type.in_(MATCH_TYPES),
        )
        .all()
    )

    ready_rows = [r for r in draft.rows if not r.excluded and r.amount is not None]

    # Precompute residuals once per candidate.
    cand_residual = {c.id: _merchant_residual(c.description) for c in candidates}

    # Build the assignable pair set: structurally-valid pairs that are either
    # comparable-with-score>=FLOOR, or not-comparable. Comparable-but-<FLOOR is
    # discarded (cross-merchant — spec §3 H1, §4.3 step 1).
    pairs = []  # each: (comparable, score, amt_diff, date_diff, candidate, row)
    for row in ready_rows:
        bank_amount = float(row.amount)
        survivors = 0
        br = _merchant_residual(row.description)
        for c in candidates:
            if not _passes_structural_gate(c, draft.account_id, row.date, bank_amount):
                continue
            survivors += 1
            er = cand_residual[c.id]
            comparable = bool(br) and bool(er)
            score = fuzz.token_set_ratio(br, er) / 100.0 if comparable else 0.0
            if comparable and score < MATCH_MERCHANT_FLOOR:
                continue   # compared merchants, they differ → reject (cross-merchant)
            amt_diff = abs(float(c.amount) - bank_amount)
            date_diff = abs((c.date - row.date).days)
            pairs.append((comparable, score, amt_diff, date_diff, c, row))
        if survivors > MATCH_FANOUT_WARN:
            # Perf sanity (spec §12.6) — fuzzy is cheap, this just documents expectation.
            import logging
            logging.getLogger(__name__).info(
                "import matcher: row_id=%s survived structural gate against %d candidates",
                row.id, survivors,
            )

    # Sort assignable pairs: comparable first, then score desc, then closest
    # amount/date, then stable id/index tiebreaks (spec §4.3 step 2). row_index is
    # the ordering tiebreak ONLY — identity is always row.id.
    pairs.sort(key=lambda p: (
        not p[0],            # comparable desc (False sorts before True → invert)
        -p[1],               # score desc
        p[2],                # |amt diff| asc
        p[3],                # |date diff| asc
        p[4].id,             # candidate.id asc
        p[5].row_index,      # row.row_index asc
    ))

    plan: dict[int, MatchPlanEntry] = {}
    consumed_rows: set[int] = set()
    consumed_cands: set[int] = set()
    for comparable, score, _amt, _date, cand, row in pairs:
        if row.id in consumed_rows or cand.id in consumed_cands:
            continue
        consumed_rows.add(row.id)
        consumed_cands.add(cand.id)
        tier = "confident" if (comparable and score >= MATCH_MERCHANT_HIGH) else "review"
        plan[row.id] = MatchPlanEntry(
            row_id=row.id,
            candidate_id=cand.id,
            score=score,
            tier=tier,
            comparable=comparable,
            candidate_desc=cand.description,
            candidate_amount=float(cand.amount),
            candidate_date=cand.date,
            bank_desc=row.description,
            bank_amount=float(row.amount),
            bank_date=row.date,
        )
    return plan


def _build_preview_response(db: Session, draft: models.ImportDraft) -> schemas.ImportDraftPreviewResponse:
    rows_ready = [r for r in draft.rows if not r.excluded]
    duplicates = sum(1 for r in draft.rows if r.duplicate_of is not None)
    meta = draft.parsed_meta or {}
    detected_last4 = meta.get("detected_account_last4")

    # Option B — surface PDF wizard fields when present. parsed_meta already
    # stores the wire-safe candidate list (no header/rows) per MASON-2.
    candidates = meta.get("candidate_tables")
    candidate_schemas = (
        [schemas.CandidateTableSchema(**c) for c in candidates] if candidates else None
    )

    # BACKLOG-036 — compute the merchant-confidence plan for display. Confident
    # pairs ship as id-pairs only (cheap even at ~200, spec §12.3); Review pairs
    # ship in full so the wizard can render the quick-check card.
    plan = _compute_match_plan(db, draft)
    confident_matches: list[schemas.ConfidentPair] = []
    review_suggestions: list[schemas.MatchSuggestion] = []
    for entry in plan.values():
        if entry.tier == "confident":
            confident_matches.append(schemas.ConfidentPair(
                row_id=entry.row_id,
                candidate_transaction_id=entry.candidate_id,
            ))
        else:
            review_suggestions.append(schemas.MatchSuggestion(
                row_id=entry.row_id,
                score=entry.score,
                candidate_transaction_id=entry.candidate_id,
                candidate_description=entry.candidate_desc,
                candidate_amount=entry.candidate_amount,
                candidate_date=entry.candidate_date,
                bank_description=entry.bank_desc,
                bank_amount=entry.bank_amount,
                bank_date=entry.bank_date,
            ))

    return schemas.ImportDraftPreviewResponse(
        id=draft.id,
        status=draft.status,
        account=draft.account,
        parsed_meta=draft.parsed_meta,
        column_mapping=draft.column_mapping,
        rows=draft.rows,
        summary=schemas.ImportDraftSummary(
            total=len(draft.rows),
            duplicates=duplicates,
            ready_to_import=len(rows_ready),
            detected_account_last4=detected_last4,
        ),
        format=meta.get("format") or draft.format,
        extraction_strategy=meta.get("extraction_strategy"),
        candidate_tables=candidate_schemas,
        selected_table_index=meta.get("selected_table_index"),
        confident_matches=confident_matches,
        confident_match_count=len(confident_matches),
        review_suggestions=review_suggestions,
    )


# ---------------------------------------------------------------------------
# POST /api/imports — upload CSV, create draft
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, response_model=schemas.ImportDraftPreviewResponse)
def create_import(
    file: UploadFile = File(...),
    account_id: int = Query(...),
    format: Optional[str] = Query(None),
    selected_table_index: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_owner),
):
    _require_enabled()

    # Size check before any processing
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    fmt = (format or "csv").lower()
    if fmt not in ("csv", "pdf"):
        raise HTTPException(
            status_code=400,
            detail=f"Format '{fmt}' not supported (CSV or PDF only)",
        )

    # BASTION-3: content-based MIME validation via the parser.
    # CSV parser ignores selected_table_index; PDF parser honours it.
    parser = pdf_parser if fmt == "pdf" else csv_parser
    parse_result = parser.parse(raw, selected_table_index=selected_table_index)
    header = parse_result.header
    data_rows = parse_result.rows

    # BASTION-11: sanitise filename at ingest
    safe_filename = _sanitise_filename(file.filename or "")

    # Account ownership check
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.user_id == user.id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # MASON-4: validate default column mapping — all indices must be within header bounds
    col_count = len(header)
    if col_count < 3:
        raise HTTPException(
            status_code=400,
            detail={"kind": "parse_error", "message": f"File has only {col_count} column(s); at least 3 required"},
        )
    default_mapping = _guess_mapping(header)

    # Last-4 detection runs over both header + data row joins.
    detected_last4 = _detect_account_last4(
        [",".join(header)] + [",".join(r) for r in data_rows[:4]]
    )

    # Wire-safe candidate list — header/rows stripped per MASON-2.
    candidate_wire = None
    if parse_result.candidate_tables:
        candidate_wire = [
            {
                "index": c.index,
                "row_count": c.row_count,
                "column_count": c.column_count,
                "first_row_preview": c.first_row_preview,
            }
            for c in parse_result.candidate_tables
        ]

    draft = models.ImportDraft(
        user_id=user.id,
        account_id=account_id,
        filename=safe_filename,
        format=fmt,
        parsed_meta={
            "row_count": len(data_rows),
            "detected_account_last4": detected_last4,
            "header": header,
            "format": fmt,
            "candidate_tables": candidate_wire,
            "selected_table_index": parse_result.selected_table_index,
            "extraction_strategy": parse_result.extraction_strategy,
        },
        column_mapping=default_mapping,
        status="preview_ready",
        expires_at=datetime.utcnow() + timedelta(hours=DRAFT_TTL_HOURS),
    )
    db.add(draft)
    db.flush()

    for i, raw_row in enumerate(data_rows):
        row_date, row_desc, row_amount = _apply_mapping(raw_row, default_mapping)
        dup_id, dup_score = _dedup_row(db, account_id, row_date, row_amount, row_desc)
        db.add(models.ImportDraftRow(
            draft_id=draft.id,
            row_index=i,
            raw=raw_row,
            date=row_date,
            description=row_desc,
            amount=row_amount,
            duplicate_of=dup_id,
            duplicate_score=dup_score,
            excluded=(dup_id is not None),   # default: exclude suspected duplicates
        ))

    db.commit()
    db.refresh(draft)
    return _build_preview_response(db, draft)


# ---------------------------------------------------------------------------
# GET /api/imports/:id/preview — fetch draft rows + summary
# ---------------------------------------------------------------------------

@router.get("/{draft_id}/preview", response_model=schemas.ImportDraftPreviewResponse)
def get_preview(
    draft_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_owner),
):
    _require_enabled()
    draft = db.query(models.ImportDraft).filter(
        models.ImportDraft.id == draft_id,
        models.ImportDraft.user_id == user.id,
    ).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _build_preview_response(db, draft)


# ---------------------------------------------------------------------------
# PATCH /api/imports/:id — update column mapping or row decisions
# ---------------------------------------------------------------------------

@router.patch("/{draft_id}", response_model=schemas.ImportDraftPreviewResponse)
def patch_draft(
    draft_id: int,
    payload: schemas.ImportDraftPatchRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_owner),
):
    _require_enabled()
    draft = db.query(models.ImportDraft).filter(
        models.ImportDraft.id == draft_id,
        models.ImportDraft.user_id == user.id,
        models.ImportDraft.status == "preview_ready",
    ).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not editable")

    mapping_changed = False
    if payload.column_mapping is not None:
        # MASON-4: ColumnMappingSchema already validated by Pydantic
        draft.column_mapping = payload.column_mapping.model_dump()
        mapping_changed = True

    if payload.row_updates:
        rows_by_id = {r.id: r for r in draft.rows}
        for upd in payload.row_updates:
            r = rows_by_id.get(upd.id)
            if not r:
                continue
            if upd.excluded is not None:
                r.excluded = upd.excluded
            if upd.category_id is not None:
                r.category_id = upd.category_id
            if upd.user_edited is not None:
                r.user_edited = upd.user_edited
            if upd.date is not None:
                r.date = upd.date
            if upd.description is not None:
                r.description = upd.description
            if upd.amount is not None:
                r.amount = upd.amount

    if mapping_changed:
        for row in draft.rows:
            # AUDIT-10: a mapping change must NOT clobber rows the user hand-edited.
            # user_edited rows carry deliberate overrides — re-deriving them from the
            # new column map would silently discard the user's corrections.
            if row.user_edited:
                dup_id, dup_score = _dedup_row(
                    db, draft.account_id, row.date, row.amount, row.description
                )
                row.duplicate_of = dup_id
                row.duplicate_score = dup_score
                continue

            row_date, row_desc, row_amount = _apply_mapping(row.raw, draft.column_mapping)
            row.date = row_date
            row.description = row_desc
            row.amount = row_amount
            dup_id, dup_score = _dedup_row(db, draft.account_id, row_date, row_amount, row_desc)
            row.duplicate_of = dup_id
            row.duplicate_score = dup_score
            # AUDIT-10: remap recomputed duplicate_of but previously left `excluded` stale —
            # reset exclude to track the fresh dedup result for non-user-edited rows.
            row.excluded = (dup_id is not None)

    db.commit()
    db.refresh(draft)
    return _build_preview_response(db, draft)


# ---------------------------------------------------------------------------
# POST /api/imports/:id/commit — TOCTOU-safe, write transactions
# ---------------------------------------------------------------------------

@router.post("/{draft_id}/commit", response_model=schemas.ImportCommitResponse)
def commit_draft(
    draft_id: int,
    payload: schemas.ImportCommitRequest = schemas.ImportCommitRequest(),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_owner),
):
    _require_enabled()

    # BASTION-5: TOCTOU-safe transition — atomic UPDATE with WHERE on expected status.
    # The intermediate 'committing' state blocks a concurrent request from also matching
    # 'preview_ready'. A crash here leaves the draft in 'committing'; the startup recovery
    # in run_startup_migrations() resets it to 'preview_ready' (BASTION-8).
    # AUDIT-11: gate on expires_at inside the atomic UPDATE so a draft that crossed
    # its TTL while open in the wizard (stale dedup flags) can't be committed.
    now_utc = datetime.utcnow()
    result = db.execute(
        text(
            "UPDATE import_drafts SET status = 'committing', committed_at = :now "
            "WHERE id = :id AND user_id = :uid AND status = 'preview_ready' "
            "AND expires_at > :now"
        ),
        {"id": draft_id, "uid": user.id, "now": now_utc},
    )
    if result.rowcount == 0:
        draft_row = db.execute(
            text("SELECT status, expires_at FROM import_drafts WHERE id = :id AND user_id = :uid"),
            {"id": draft_id, "uid": user.id},
        ).first()
        if draft_row is not None and draft_row[0] == "preview_ready":
            raise HTTPException(status_code=409, detail="Draft has expired; please re-upload")
        raise HTTPException(status_code=409, detail="Draft is not in preview_ready state")

    db.flush()   # BASTION-9: make write visible to subsequent ORM reads on this connection

    draft = db.query(models.ImportDraft).filter(models.ImportDraft.id == draft_id).first()

    def _reject_and_reset(detail):
        # AUDIT-04/AUDIT-11: we already flipped the draft to 'committing' (TOCTOU gate).
        # A validation rejection must return the draft to 'preview_ready' immediately so
        # the user can fix rows and retry without waiting for the BASTION-8 boot recovery.
        db.execute(
            text("UPDATE import_drafts SET status = 'preview_ready', committed_at = NULL "
                 "WHERE id = :id AND status = 'committing'"),
            {"id": draft_id},
        )
        db.commit()
        raise HTTPException(status_code=409, detail=detail)

    # BACKLOG-036 — unified commit-apply guard (spec §12.1).
    #   (1) Plan computed ONCE, read-only, materialised before any write.
    #   (2) Nothing applies unless the client echoed {row_id, candidate_transaction_id}
    #       AND the recomputed plan still maps that row to that candidate at the same tier.
    #   (3) The FULL structural gate is re-checked against the live candidate at apply.
    #   (4) Confident and accepted-Review share ONE apply path (this is what makes the
    #       §7 rollback claim true).
    plan = _compute_match_plan(db, draft)

    # The client echoes BOTH auto-checked Confident pairs and user-toggled Review pairs.
    # Build a {row_id → candidate_transaction_id} lookup of what the client confirmed.
    confirmed = {m.row_id: m.candidate_transaction_id for m in payload.confirmed_matches}

    # AUDIT-04: refuse to commit non-excluded rows with an unparseable amount or date.
    # A None amount would book $0.00 as verified; a None date would 500 the INSERT.
    # Reject the whole commit (nothing written) with the offending rows listed.
    invalid_rows = [
        {
            "row_id": r.id,
            "row_index": r.row_index,
            "reason": "missing amount" if r.amount is None else "missing date",
        }
        for r in draft.rows
        if not r.excluded and (r.amount is None or r.date is None)
    ]
    if invalid_rows:
        _reject_and_reset({
            "kind": "invalid_rows",
            "message": (
                f"{len(invalid_rows)} row(s) have no parseable amount or date. "
                "Exclude or correct them before importing."
            ),
            "rows": invalid_rows,
        })

    # AUDIT-11: dedup flags were computed at UPLOAD; re-run dedup for every non-excluded,
    # non-matcher row and 409 on a FRESH duplicate the user hasn't already acknowledged.
    fresh_dupes = []
    for r in draft.rows:
        if r.excluded or r.amount is None or r.date is None:
            continue
        if r.id in plan:
            continue
        dup_id, _score = _dedup_row(db, draft.account_id, r.date, r.amount, r.description)
        if dup_id is not None and r.duplicate_of is None:
            fresh_dupes.append({"row_id": r.id, "row_index": r.row_index, "duplicate_of": dup_id})
    if fresh_dupes:
        _reject_and_reset({
            "kind": "stale_duplicates",
            "message": (
                f"{len(fresh_dupes)} row(s) now match a transaction committed since upload. "
                "Re-open the preview to review before importing."
            ),
            "rows": fresh_dupes,
        })

    # FE-012 — reconciliation matcher. All mutations below (match-revisions, inserts,
    # and the committing→committed flip) share the single db.commit() at the end so
    # they land in ONE unit of work on the same connection as the BASTION-5 TOCTOU
    # UPDATE (A3). A failure anywhere in the loop leaves zero rows mutated.
    created = 0
    auto_matched = 0
    confirmed_matched = 0
    could_not_apply = 0
    amount_diff_warnings: list[schemas.MatchWarning] = []

    # Cache live candidate rows by id for the apply-time gate re-check.
    cand_cache: dict[int, Optional[models.Transaction]] = {}

    def _live_candidate(cid: int) -> Optional[models.Transaction]:
        if cid not in cand_cache:
            cand_cache[cid] = (
                db.query(models.Transaction)
                .filter(models.Transaction.id == cid)
                .first()
            )
        return cand_cache[cid]

    for row in draft.rows:
        if row.excluded:
            continue
        row_amount = 0.0 if row.amount is None else float(row.amount)

        entry = plan.get(row.id)
        # A pair applies only if: planned this run, client confirmed the SAME candidate,
        # and the recomputed plan still maps that row to that candidate (spec §12.1.2).
        # Confident pairs are echoed automatically by the UI, so the same echo check
        # covers both tiers — a post-preview edit changes the recomputed plan (or drops
        # the row entirely), the echo no longer matches, and it falls through to import-new.
        match = None
        if entry is not None and confirmed.get(row.id) == entry.candidate_id:
            candidate = _live_candidate(entry.candidate_id)
            # §12.1.3 — re-run the FULL structural gate against the LIVE candidate.
            if candidate is not None and _passes_structural_gate(
                candidate, draft.account_id, row.date, row_amount
            ):
                match = candidate
            else:
                # Client confirmed a pair that no longer passes the gate (concurrent
                # candidate mutation). Import as new + count it (spec §12.4).
                could_not_apply += 1
        elif row.id in confirmed:
            # Client echoed this row but the recomputed plan no longer maps it to that
            # candidate — either remapped to a different candidate, or dropped from the
            # plan (a post-preview row edit moved it out of any tier). Safe default:
            # import as new + count as could-not-apply (spec §12.1.2 + §12.4).
            could_not_apply += 1

        if match is not None:
            tier = entry.tier
            manual_amount = float(match.amount)
            est_date = match.date          # AUDIT-09: capture BEFORE we overwrite it
            if abs(manual_amount - row_amount) > 0.005:
                # Amounts differ — bank wins; preserve the original for rollback/provenance.
                # A2: never overwrite a non-null original_amount (the candidate gate already
                # guarantees a pristine import_id-null row, so this is always first-write).
                match.original_amount = manual_amount
                human = f"Matched import; amount updated {manual_amount:+.2f} → {row_amount:+.2f}"
                amount_diff_warnings.append(schemas.MatchWarning(
                    transaction_id=match.id,
                    description=match.description,
                    manual_amount=manual_amount,
                    bank_amount=row_amount,
                ))
            else:
                human = "Matched import; amounts agreed"
            # AUDIT-05 + AUDIT-09: stamp the bank row's identity (desc + date) and the
            # estimate's ORIGINAL date into a structured match_note. Lets a re-imported
            # statement dedup against this reconciled row (A5) and preserves the pre-reconcile
            # date for provenance/rollback (A9) — all without new columns.
            match.match_note = _make_match_note(
                bank_desc=row.description,
                bank_date=row.date,
                est_date=est_date,
                human=human,
            )
            match.amount = row_amount
            # AUDIT-09: the estimate's date was a guess; the bank row's date is authoritative.
            # Keeping the estimate date books spend in the wrong month across a ±3-day
            # boundary. Adopt the bank date. FORWARD-ONLY: affects only rows reconciled by
            # THIS commit — no historical rows are touched (no migration).
            if row.date is not None:
                match.date = row.date
            match.is_verified = True
            match.source = "manual"          # keep manual provenance (user category/notes)
            match.import_id = draft.id        # tag so rollback can revert THIS import's matches
            if tier == "confident":
                auto_matched += 1
            else:
                confirmed_matched += 1
        else:
            # A5: an unmatched row flagged as a near-duplicate (duplicate_of set) that the
            # user chose NOT to exclude commits as a manual-style estimate — is_verified=False
            # ("Review") — so genuine anomalies (double charges, fraud) still prompt a look.
            # Clean unmatched rows auto-verify (statement is source of truth).
            is_near_dup = row.duplicate_of is not None
            db.add(models.Transaction(
                account_id=draft.account_id,
                date=row.date,
                description=row.description,
                amount=row_amount,
                category_id=row.category_id,
                source="import",
                is_verified=not is_near_dup,
                import_id=draft.id,
            ))
            created += 1

    draft.status = "committed"
    db.commit()
    db.refresh(draft)

    committed_at = _as_utc(draft.committed_at)
    rollback_until = committed_at + timedelta(seconds=IMPORT_ROLLBACK_WINDOW_SECONDS)
    matched = auto_matched + confirmed_matched
    return schemas.ImportCommitResponse(
        id=draft.id,
        status=draft.status,
        committed_at=committed_at,
        rollback_until=rollback_until,
        transactions_created=created,
        matched_count=matched,                 # back-compat = auto + confirmed
        auto_matched_count=auto_matched,
        confirmed_matched_count=confirmed_matched,
        review_suggested_count=sum(1 for e in plan.values() if e.tier == "review"),
        could_not_apply_count=could_not_apply,
        amount_diff_warnings=amount_diff_warnings,
    )


# ---------------------------------------------------------------------------
# POST /api/imports/:id/rollback — undo within window
# ---------------------------------------------------------------------------

@router.post("/{draft_id}/rollback")
def rollback_import(
    draft_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_owner),
):
    _require_enabled()

    draft = db.query(models.ImportDraft).filter(
        models.ImportDraft.id == draft_id,
        models.ImportDraft.user_id == user.id,
        models.ImportDraft.status == "committed",
    ).first()
    if not draft:
        raise HTTPException(status_code=404, detail="No committed draft to rollback")

    # FE-003: compare aware-vs-aware. committed_at is stored naive UTC; coerce it.
    rollback_until = _as_utc(draft.committed_at) + timedelta(seconds=IMPORT_ROLLBACK_WINDOW_SECONDS)
    now = datetime.now(timezone.utc)
    if now > rollback_until:
        elapsed = int((now - rollback_until).total_seconds())
        raise HTTPException(status_code=409, detail=f"Rollback window expired ({elapsed}s ago)")

    # BASTION-5: TOCTOU-safe transition for rollback
    result = db.execute(
        text("UPDATE import_drafts SET status = 'rolled_back' WHERE id = :id AND status = 'committed'"),
        {"id": draft_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail="Concurrent state change; rollback aborted")

    # FE-012 (A1): rollback splits by source. Rows tagged with this draft's import_id
    # fall into two disjoint sets that must NOT be treated as one:
    #
    #   * source=='manual' → matched estimates. REVERT only (un-verify, restore the
    #     original amount, clear matcher tags). Do NOT null their FKs and do NOT touch
    #     other drafts' duplicate_of links pointing at them — these rows existed before
    #     this import and survive it.
    #   * source=='import' → rows this import inserted. FE-009 FK-null (DebtPayment /
    #     SavingsContribution / ImportDraftRow.duplicate_of) THEN delete.
    matched_rows = db.query(models.Transaction).filter(
        models.Transaction.import_id == draft.id,
        models.Transaction.source == "manual",
    ).all()
    reverted = 0
    for tx in matched_rows:
        tx.is_verified = False
        if tx.original_amount is not None:
            tx.amount = tx.original_amount
        # AUDIT-09: if this row's date was overwritten with the bank date on reconcile,
        # restore the estimate's original date (parked in the structured match_note).
        meta = _parse_match_note(tx.match_note)
        if meta is not None and meta.get("est_date") is not None:
            tx.date = meta["est_date"]
        tx.original_amount = None
        tx.match_note = None
        tx.import_id = None
        reverted += 1

    # Null FK refs to the INSERTED import rows before deleting (foreign_keys=ON).
    # A later import's draft rows may mark these as duplicates, and the user may have
    # linked them to a debt/goal — all must be unpinned first or the delete fails.
    import_tx_ids = [r[0] for r in db.query(models.Transaction.id).filter(
        models.Transaction.import_id == draft.id,
        models.Transaction.source == "import",
    ).all()]
    if import_tx_ids:
        db.query(models.DebtPayment).filter(models.DebtPayment.transaction_id.in_(import_tx_ids)).update(
            {"transaction_id": None}, synchronize_session=False
        )
        db.query(models.SavingsContribution).filter(models.SavingsContribution.transaction_id.in_(import_tx_ids)).update(
            {"transaction_id": None}, synchronize_session=False
        )
        db.query(models.ImportDraftRow).filter(models.ImportDraftRow.duplicate_of.in_(import_tx_ids)).update(
            {"duplicate_of": None}, synchronize_session=False
        )
    deleted = db.query(models.Transaction).filter(
        models.Transaction.import_id == draft.id,
        models.Transaction.source == "import",
    ).delete(synchronize_session=False)
    db.commit()

    return {
        "status": "rolled_back",
        "transactions_deleted": deleted,
        "matches_reverted": reverted,
    }


# ---------------------------------------------------------------------------
# DELETE /api/imports/:id — cancel a preview_ready draft
# ---------------------------------------------------------------------------

@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_owner),
):
    _require_enabled()

    result = db.execute(
        text(
            "UPDATE import_drafts SET status = 'cancelled' "
            "WHERE id = :id AND user_id = :uid AND status = 'preview_ready'"
        ),
        {"id": draft_id, "uid": user.id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Draft not cancellable")
    db.commit()
    return None


# ---------------------------------------------------------------------------
# GET /api/imports — import history
# ---------------------------------------------------------------------------

@router.get("", response_model=schemas.ImportHistoryResponse)
def list_imports(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_owner),
):
    _require_enabled()

    q = db.query(models.ImportDraft).filter(models.ImportDraft.user_id == user.id)
    if account_id:
        q = q.filter(models.ImportDraft.account_id == account_id)

    total = q.count()
    items = q.order_by(models.ImportDraft.created_at.desc()).offset(offset).limit(limit).all()

    history_items = []
    for d in items:
        # FE-012: "added" reflects NEW import rows only (source='import'). Matched
        # manual estimates also carry this import_id but were not "added" by it.
        tx_count = (
            db.query(models.Transaction)
            .filter(
                models.Transaction.import_id == d.id,
                models.Transaction.source == "import",
            )
            .count()
        )
        committed_at = _as_utc(d.committed_at)
        rollback_until = (
            committed_at + timedelta(seconds=IMPORT_ROLLBACK_WINDOW_SECONDS)
            if committed_at
            else None
        )
        rollback_available = bool(
            d.status == "committed"
            and rollback_until
            and datetime.now(timezone.utc) < rollback_until
        )
        history_items.append(
            schemas.ImportHistoryItem(
                id=d.id,
                status=d.status,
                filename=d.filename,
                account=d.account,
                # LOW (created_at not UTC): coerce naive UTC to an aware value so the
                # wire value carries +00:00 and the FE never renders it as local time.
                created_at=_as_utc(d.created_at),
                committed_at=committed_at,
                rollback_until=rollback_until,
                rollback_available=rollback_available,
                transactions_count=tx_count,
            )
        )

    return schemas.ImportHistoryResponse(items=history_items, total=total)
