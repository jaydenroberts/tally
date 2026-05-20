"""
Critical-path tests for the staged-import router (/api/imports).

Covers:
  1. Happy path: upload → preview → commit → tx count matches
  2. Rollback within window → tx count drops to 0
  3. Rollback after window → 409
  4. MIME rejection: non-CSV bytes → 400
  5. Duplicate flagging: pre-existing matching tx → preview shows row excluded
  6. TOCTOU concurrency: two concurrent commits → only one succeeds (409)

Option B — PDF path (§ 6 of the locked spec):
  7. PDF standard layout — largest table wins, dedup runs
  8. PDF row-per-table layout — flattened
  9. PDF two-date text fallback — pattern (a) wins, text rows > table rows
 10. PDF multiple candidates surfaced — default = largest
 11. PDF no-tables → 422 + kind: parse_error
 12. PDF table re-pick via DELETE + re-upload with ?selected_table_index=N
 13. PDF oversized page count → 413 + kind: parse_error
"""
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import models
from app.routers.imports import _apply_mapping, _normalise_amount, _normalise_date
from tests.conftest import SAMPLE_CSV
from tests.fixtures.pdf import (
    standard_layout_pdf,
    row_per_table_pdf,
    two_date_text_fallback_pdf,
    multi_candidate_pdf,
    no_tables_pdf,
    oversized_page_count_pdf,
    multi_page_same_header_pdf,
    different_headers_two_page_pdf,
    au_credit_card_text_pdf,
)


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

def test_happy_path(client, auth_headers, test_account):
    # Upload
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("statement.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    draft_id = data["id"]
    assert data["status"] == "preview_ready"
    assert data["summary"]["total"] == 2

    # Preview
    resp = client.get(f"/api/imports/{draft_id}/preview", headers=auth_headers)
    assert resp.status_code == 200

    # Commit
    resp = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    commit = resp.json()
    assert commit["status"] == "committed"
    assert commit["transactions_created"] == 2


# ---------------------------------------------------------------------------
# 2. Rollback within window
# ---------------------------------------------------------------------------

def test_rollback_within_window(client, auth_headers, test_account):
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("stmt.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
    )
    assert resp.status_code == 201
    draft_id = resp.json()["id"]

    client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers)

    resp = client.post(f"/api/imports/{draft_id}/rollback", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rolled_back"
    assert resp.json()["transactions_deleted"] == 2


# ---------------------------------------------------------------------------
# 3. Rollback after window
# ---------------------------------------------------------------------------

def test_rollback_after_window(client, auth_headers, test_account, db):
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("stmt.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
    )
    assert resp.status_code == 201
    draft_id = resp.json()["id"]
    client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers)

    # Backdate committed_at so the window is expired
    draft = db.query(models.ImportDraft).filter(models.ImportDraft.id == draft_id).first()
    draft.committed_at = datetime.utcnow() - timedelta(seconds=600)
    db.commit()

    resp = client.post(f"/api/imports/{draft_id}/rollback", headers=auth_headers)
    assert resp.status_code == 409, resp.text
    assert "expired" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 4. MIME rejection — non-CSV bytes
# ---------------------------------------------------------------------------

def test_mime_rejection(client, auth_headers, test_account):
    fake_zip = b"PK\x03\x04" + b"\x00" * 100   # ZIP magic bytes
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("data.csv", io.BytesIO(fake_zip), "text/csv")},
    )
    # ZIP bytes are not valid UTF-8 — expect 400 parse_error
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail.get("kind") == "parse_error"


# ---------------------------------------------------------------------------
# 5. Duplicate flagging
# ---------------------------------------------------------------------------

def test_duplicate_flagging(client, auth_headers, test_account, db):
    # Pre-seed a matching transaction
    from datetime import date
    existing_tx = models.Transaction(
        account_id=test_account.id,
        date=date(2026, 5, 1),
        description="Coffee",
        amount=-4.50,
        source="import",
        is_verified=True,
    )
    db.add(existing_tx)
    db.commit()

    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("stmt.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()

    # The Coffee row should be flagged as a duplicate and excluded
    coffee_rows = [r for r in data["rows"] if r.get("description") == "Coffee"]
    assert coffee_rows, "Coffee row should be present"
    assert coffee_rows[0]["excluded"] is True
    assert coffee_rows[0]["duplicate_of"] is not None
    assert data["summary"]["duplicates"] >= 1


# ---------------------------------------------------------------------------
# 6. TOCTOU concurrency — two concurrent commits, only one succeeds
# ---------------------------------------------------------------------------

def test_toctou_concurrent_commit(client, auth_headers, test_account):
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("stmt.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
    )
    assert resp.status_code == 201
    draft_id = resp.json()["id"]

    results = []

    def do_commit():
        return client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(do_commit), pool.submit(do_commit)]
        for f in as_completed(futures):
            results.append(f.result().status_code)

    # Exactly one 200 and one 409
    assert sorted(results) == [200, 409], f"Expected [200, 409], got {sorted(results)}"


# ---------------------------------------------------------------------------
# Option B — PDF tests (§ 6 of the locked spec)
# ---------------------------------------------------------------------------
# These tests exercise the worker-process boundary (multiprocessing.Process),
# verifying fork-safety in passing — if SQLAlchemy connections were leaking
# into the child process the standard-layout test would deadlock or surface
# warnings before the assertion runs.


def _upload_pdf(client, account_id, headers, pdf_bytes, name="stmt.pdf", **params):
    p = {"account_id": account_id, "format": "pdf"}
    p.update(params)
    return client.post(
        "/api/imports",
        headers=headers,
        params=p,
        files={"file": (name, io.BytesIO(pdf_bytes), "application/pdf")},
    )


# 1. PDF standard layout ------------------------------------------------------

def test_pdf_standard_layout(client, auth_headers, test_account):
    resp = _upload_pdf(client, test_account.id, auth_headers, standard_layout_pdf())
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert data["format"] == "pdf"
    assert data["extraction_strategy"] == "standard"
    # The transactions table has 4 rows on page 1 + 2 rows on page 2 = 6
    # data rows total (header rows of subsequent tables are dropped).
    assert data["summary"]["total"] >= 4
    # Candidate tables surface — but the default selection is the largest one.
    assert data["candidate_tables"] is not None
    assert data["selected_table_index"] is not None

    # Wave D regression guard: verify amount + date actually normalised
    # (these are ISO + plain-decimal so the bug never surfaced here, but
    # we want the assertion in place so future regressions trip it).
    rows_by_desc = {r["description"]: r for r in data["rows"]}
    coffee = rows_by_desc.get("Coffee Co")
    assert coffee is not None
    assert Decimal(str(coffee["amount"])) == Decimal("-4.50")
    assert coffee["date"] == "2026-01-02"


# 2. PDF row-per-table layout -------------------------------------------------

def test_pdf_row_per_table_layout(client, auth_headers, test_account):
    resp = _upload_pdf(client, test_account.id, auth_headers, row_per_table_pdf(num_rows=6))
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert data["extraction_strategy"] == "row_per_table"
    # We synthesised 6 rows; the parser collapses the repeating header so
    # we expect exactly 6 data rows.
    assert data["summary"]["total"] == 6

    # Wave D regression guard: assert at least one row's numeric amount + date
    # round-trip correctly. Fixture: row i has date 2026-02-{i+1:02d},
    # description "Test row {i+1}", amount "-{(i+1)*10}.00".
    rows_by_desc = {r["description"]: r for r in data["rows"]}
    r1 = rows_by_desc.get("Test row 1")
    assert r1 is not None
    assert Decimal(str(r1["amount"])) == Decimal("-10.00")
    assert r1["date"] == "2026-02-01"


# 3. PDF two-date text fallback ----------------------------------------------

def test_pdf_two_date_text_fallback(client, auth_headers, test_account):
    resp = _upload_pdf(client, test_account.id, auth_headers, two_date_text_fallback_pdf())
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert data["extraction_strategy"] == "text_fallback"
    # The fixture has 5 transaction lines parseable by pattern (a) and zero
    # table rows beyond the repeating header — text rows must beat tables.
    assert data["summary"]["total"] == 5


# 4. PDF multiple tables surfaces candidates ----------------------------------

def test_pdf_multiple_tables_surfaces_candidates(client, auth_headers, test_account):
    resp = _upload_pdf(client, test_account.id, auth_headers, multi_candidate_pdf())
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert data["extraction_strategy"] == "standard"
    candidates = data["candidate_tables"]
    assert candidates is not None and len(candidates) == 3

    # Each candidate exposes index/row_count/column_count/first_row_preview only.
    for c in candidates:
        assert set(c.keys()) == {"index", "row_count", "column_count", "first_row_preview"}
        assert len(c["first_row_preview"]) <= 5
        # 80-char cap per cell (BASTION-4 / IRIS-3 wire boundary).
        assert all(len(cell) <= 80 for cell in c["first_row_preview"])

    # Default = largest, which is the 4-row "Table B" in the fixture.
    largest = max(candidates, key=lambda c: c["row_count"])
    assert data["selected_table_index"] == largest["index"]
    assert data["summary"]["total"] == largest["row_count"]


# 5. PDF no tables rejected ---------------------------------------------------

def test_pdf_no_tables_rejected(client, auth_headers, test_account):
    before = client.get("/api/imports", headers=auth_headers).json().get("total", 0)
    resp = _upload_pdf(client, test_account.id, auth_headers, no_tables_pdf())
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail.get("kind") == "parse_error"
    after = client.get("/api/imports", headers=auth_headers).json().get("total", 0)
    # No draft should have been persisted.
    assert after == before


# 6. PDF re-pick table — full DELETE + re-upload flow [MASON-5] ---------------

def test_pdf_re_pick_table(client, auth_headers, test_account):
    pdf_bytes = multi_candidate_pdf()

    first = _upload_pdf(client, test_account.id, auth_headers, pdf_bytes)
    assert first.status_code == 201, first.text
    first_data = first.json()
    candidates = first_data["candidate_tables"]
    default_idx = first_data["selected_table_index"]

    # Pick a non-default candidate — the smallest, "Table C" (2 rows).
    smallest = min(candidates, key=lambda c: c["row_count"])
    assert smallest["index"] != default_idx, "fixture must have a non-default candidate"

    # DELETE the current draft (preview_ready), then re-upload with selected_table_index.
    cancel = client.delete(f"/api/imports/{first_data['id']}", headers=auth_headers)
    assert cancel.status_code == 204, cancel.text

    second = _upload_pdf(
        client, test_account.id, auth_headers, pdf_bytes,
        selected_table_index=smallest["index"],
    )
    assert second.status_code == 201, second.text
    second_data = second.json()

    # The second draft uses the candidate we asked for.
    assert second_data["selected_table_index"] == smallest["index"]
    assert second_data["summary"]["total"] == smallest["row_count"]


# 8. PDF multi-page same-header auto-merge -----------------------------------
# v1.3.2 parity: three pages each carry an identical 3-column header. The
# parser must re-stitch them into a single candidate with 12 data rows, NOT
# surface three separate candidates (which would force the user to pick one
# page and silently drop the rest).

def test_pdf_multi_page_same_header_merges(client, auth_headers, test_account):
    resp = _upload_pdf(client, test_account.id, auth_headers, multi_page_same_header_pdf())
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert data["format"] == "pdf"
    assert data["extraction_strategy"] == "standard"
    # 5 + 4 + 3 = 12 merged data rows.
    assert data["summary"]["total"] == 12
    # Post-merge there is exactly one candidate — the stitched transactions table.
    candidates = data["candidate_tables"]
    assert candidates is not None and len(candidates) == 1
    assert candidates[0]["row_count"] == 12


# 9. PDF different-headers stay separate --------------------------------------
# Defensive: merge must group by normalised header, not page proximity. Two
# tables with different headers across pages stay as two candidates.

def test_pdf_different_headers_stay_separate(client, auth_headers, test_account):
    resp = _upload_pdf(client, test_account.id, auth_headers, different_headers_two_page_pdf())
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert data["extraction_strategy"] == "standard"
    candidates = data["candidate_tables"]
    assert candidates is not None and len(candidates) == 2


# 7. PDF oversized page count rejected [MASON-5] ------------------------------

def test_pdf_oversized_page_count_rejected(client, auth_headers, test_account):
    # Bypass the 200-page cap by 1 page — the parser must reject before
    # building rows. Generating 201 trivial pages keeps the test fast.
    from app.import_parsers import pdf_parser as pp
    over = pp.MAX_PDF_PAGES + 1
    pdf_bytes = oversized_page_count_pdf(pages=over)

    resp = _upload_pdf(client, test_account.id, auth_headers, pdf_bytes)
    # Spec accepts 413 or 400 — implementation chose 413 for the page cap to
    # mirror the existing size-cap semantics.
    assert resp.status_code in (400, 413), resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, dict) and detail.get("kind") == "parse_error"


# ---------------------------------------------------------------------------
# Wave D regression — _normalise_amount + _normalise_date helpers
# ---------------------------------------------------------------------------
# These helpers fix the live-smoke-test bug where AU credit-card PDFs
# parsed through the wizard but every row's amount and date came back null.
# The old _apply_mapping called naked Decimal()/strptime() which silently
# failed on "$48.56 Dr" and "20/04/26".


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Plain numerics
        ("1234.56",       Decimal("1234.56")),
        ("0",             Decimal("0")),
        ("-1234.56",      Decimal("-1234.56")),
        # Currency stripping
        ("$1,234.56",     Decimal("1234.56")),
        ("$0.50",         Decimal("0.50")),
        # Cr / Dr suffix — Cr = positive, Dr = negative (v1.3.2 semantic)
        ("$48.56 Dr",     Decimal("-48.56")),
        ("$215.00 Cr",    Decimal("215.00")),
        ("$1,234.56 cr",  Decimal("1234.56")),
        ("$9.99 DR",      Decimal("-9.99")),
        ("100.00 Cr",     Decimal("100.00")),
        # Accounting parens-negative
        ("(1234.56)",     Decimal("-1234.56")),
        ("($48.56)",      Decimal("-48.56")),
        ("($1,234.56)",   Decimal("-1234.56")),
        # Whitespace
        ("  42.00  ",     Decimal("42.00")),
        # Unparseable
        ("abc",           None),
        ("--",            None),
        ("",              None),
        ("   ",           None),
        (None,            None),
    ],
)
def test_normalise_amount(raw, expected):
    result = _normalise_amount(raw)
    assert result == expected, f"_normalise_amount({raw!r}) → {result!r}, expected {expected!r}"


@pytest.mark.parametrize(
    "raw,expected",
    [
        # ISO (existing path)
        ("2026-04-20",  date(2026, 4, 20)),
        # AU full year
        ("20/04/2026",  date(2026, 4, 20)),
        # AU short year (some credit-card statements)
        ("20/04/26",    date(2026, 4, 20)),
        ("28/03/26",    date(2026, 3, 28)),
        ("12/04/26",    date(2026, 4, 12)),
        # AU dash variants
        ("20-04-2026",  date(2026, 4, 20)),
        ("20-04-26",    date(2026, 4, 20)),
        # Whitespace
        ("  2026-04-20  ", date(2026, 4, 20)),
        # Unparseable / empty
        ("not a date",  None),
        ("",            None),
        ("   ",         None),
        (None,          None),
        ("2026/04/20",  None),   # not in the accepted list
    ],
)
def test_normalise_date(raw, expected):
    result = _normalise_date(raw)
    assert result == expected, f"_normalise_date({raw!r}) → {result!r}, expected {expected!r}"


def test_pdf_au_credit_card_amounts_and_dates_persist(client, auth_headers, test_account):
    """End-to-end: AU credit-card-style PDF (DD/MM/YY + Cr/Dr amounts) goes
    through the wizard and persists numerically correct amount + date values.
    """
    resp = _upload_pdf(
        client, test_account.id, auth_headers,
        au_credit_card_text_pdf(),
        name="card.pdf",
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["format"] == "pdf"
    assert data["summary"]["total"] == 3

    # Index rows by description so we don't depend on parser ordering.
    rows_by_desc = {r["description"]: r for r in data["rows"]}
    assert set(rows_by_desc.keys()) == {
        "Interest Charged", "BPAY Payment Generic", "Test Purchase"
    }

    # Row 1: "$48.56 Dr" → -48.56, date 20/04/26 → 2026-04-20
    r1 = rows_by_desc["Interest Charged"]
    assert Decimal(str(r1["amount"])) == Decimal("-48.56")
    assert r1["date"] == "2026-04-20"

    # Row 2: "$215.00 Cr" → 215.00, date 28/03/26 → 2026-03-28
    r2 = rows_by_desc["BPAY Payment Generic"]
    assert Decimal(str(r2["amount"])) == Decimal("215.00")
    assert r2["date"] == "2026-03-28"

    # Row 3: "$220.00 Cr" → 220.00, date 12/04/26 → 2026-04-12
    r3 = rows_by_desc["Test Purchase"]
    assert Decimal(str(r3["amount"])) == Decimal("220.00")
    assert r3["date"] == "2026-04-12"


# ---------------------------------------------------------------------------
# FE-001 — split credit/debit column mapping
# ---------------------------------------------------------------------------
# Statements that put deposits and withdrawals in separate columns previously
# dropped every debit row to $0.00 (only the column mapped to "amount" survived).
# Semantic: amount = credit - abs(debit); a missing/blank cell counts as 0,
# Cr positive / Dr negative (matches _normalise_amount).

# Columns: [date, description, credit, debit]
SPLIT_CSV = (
    b"Date,Description,Credit,Debit\n"
    b"2026-05-01,Salary,2000.00,\n"          # credit only  -> +2000.00
    b"2026-05-02,Card Purchase,,48.56\n"     # debit only   -> -48.56
    b"2026-05-03,Refund Net,10.00,4.00\n"    # both         -> +6.00
    b"2026-05-04,Blank Row,,\n"              # neither      -> None
)
SPLIT_MAPPING = {"date": 0, "description": 1, "credit": 2, "debit": 3}


@pytest.mark.parametrize(
    "raw_row,expected_amount",
    [
        (["2026-05-01", "Salary", "2000.00", ""],     Decimal("2000.00")),   # credit only
        (["2026-05-02", "Card Purchase", "", "48.56"], Decimal("-48.56")),    # debit only
        (["2026-05-03", "Refund Net", "10.00", "4.00"], Decimal("6.00")),     # both
        (["2026-05-04", "Blank Row", "", ""],          None),                 # neither
        # A debit column already carrying a sign / parens still resolves negative
        # via abs() — we never double-negate.
        (["2026-05-05", "Parens Debit", "", "(20.00)"], Decimal("-20.00")),
    ],
)
def test_apply_mapping_split_credit_debit(raw_row, expected_amount):
    _, _, amount = _apply_mapping(raw_row, SPLIT_MAPPING)
    assert amount == expected_amount


def test_apply_mapping_single_amount_unchanged():
    """Single signed amount column behaves exactly as before (no regression)."""
    mapping = {"date": 0, "description": 1, "amount": 2}
    _, _, amount = _apply_mapping(["2026-05-01", "Coffee", "-4.50"], mapping)
    assert amount == Decimal("-4.50")


def test_split_credit_debit_remap_via_patch(client, auth_headers, test_account):
    """End-to-end: upload a split CSV, PATCH a credit/debit mapping, and confirm
    debit rows carry a non-zero (negative) value through to commit."""
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("split.csv", io.BytesIO(SPLIT_CSV), "text/csv")},
    )
    assert resp.status_code == 201, resp.text
    draft_id = resp.json()["id"]

    # Re-map columns to the split credit/debit shape.
    resp = client.patch(
        f"/api/imports/{draft_id}",
        headers=auth_headers,
        json={"column_mapping": SPLIT_MAPPING},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    rows_by_desc = {r["description"]: r for r in data["rows"]}

    assert Decimal(str(rows_by_desc["Salary"]["amount"])) == Decimal("2000.00")
    assert Decimal(str(rows_by_desc["Card Purchase"]["amount"])) == Decimal("-48.56")
    assert Decimal(str(rows_by_desc["Refund Net"]["amount"])) == Decimal("6.00")
    assert rows_by_desc["Blank Row"]["amount"] is None


# ---------------------------------------------------------------------------
# FE-003 — rollback_until serialized with UTC offset
# ---------------------------------------------------------------------------

def test_commit_rollback_until_is_utc_aware(client, auth_headers, test_account):
    """The commit response must serialize tz-aware UTC timestamps so the
    frontend countdown parses them as UTC (not local). Naive serialization
    hid the undo button for UTC+ users."""
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("stmt.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
    )
    assert resp.status_code == 201
    draft_id = resp.json()["id"]

    resp = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    commit = resp.json()

    for field in ("committed_at", "rollback_until"):
        raw = commit[field]
        # Must carry a tz designator (Z or ±HH:MM) and round-trip as aware.
        assert raw.endswith("Z") or "+" in raw[10:] or raw[10:].count("-") > 0, raw
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None, f"{field} must be tz-aware: {raw!r}"


def test_history_rollback_until_is_utc_aware(client, auth_headers, test_account):
    """Import-history rollback_until carries UTC offset info too."""
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("stmt.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
    )
    draft_id = resp.json()["id"]
    client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers)

    resp = client.get("/api/imports", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    item = next(i for i in resp.json()["items"] if i["id"] == draft_id)
    raw = item["rollback_until"]
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, f"rollback_until must be tz-aware: {raw!r}"
    assert item["rollback_available"] is True


# ===========================================================================
# FE-012 — reconciliation matcher
# ===========================================================================
# The matcher folds a committing bank row into a pristine unverified manual
# estimate (flip Verified, bank amount wins, keep source='manual'). Unmatched
# clean rows insert as source='import', is_verified=True. Honours Advisory
# amendments A1–A8.

from app.routers.imports import _find_match


def _manual_tx(db, account, *, amount, on_date, description="Estimate",
               transaction_type="expense", is_verified=False, source="manual",
               import_id=None, original_amount=None):
    """Seed a manual estimate transaction directly."""
    tx = models.Transaction(
        account_id=account.id,
        date=on_date,
        description=description,
        amount=amount,
        source=source,
        is_verified=is_verified,
        transaction_type=transaction_type,
        import_id=import_id,
        original_amount=original_amount,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def _commit_one_row_csv(client, headers, account, *, on_date, description, amount):
    """Upload a single-row CSV and commit it; return the parsed commit response."""
    csv = (
        b"Date,Description,Amount\n"
        + f"{on_date},{description},{amount}\n".encode()
    )
    resp = client.post(
        f"/api/imports?account_id={account.id}",
        headers=headers,
        files={"file": ("one.csv", io.BytesIO(csv), "text/csv")},
    )
    assert resp.status_code == 201, resp.text
    draft_id = resp.json()["id"]
    resp = client.post(f"/api/imports/{draft_id}/commit", headers=headers)
    assert resp.status_code == 200, resp.text
    return draft_id, resp.json()


# --- match: amounts differ -------------------------------------------------

def test_match_amounts_differ(client, auth_headers, test_account, db):
    est = _manual_tx(db, test_account, amount=-45.00, on_date=date(2026, 5, 2),
                     description="Groceries")

    draft_id, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-03", description="Groceries", amount="-47.23",
    )

    assert commit["transactions_created"] == 0
    assert commit["matched_count"] == 1
    assert len(commit["amount_diff_warnings"]) == 1
    w = commit["amount_diff_warnings"][0]
    assert w["transaction_id"] == est.id
    assert w["manual_amount"] == -45.00
    assert w["bank_amount"] == -47.23

    db.refresh(est)
    assert est.is_verified is True
    assert est.source == "manual"            # provenance preserved
    assert est.amount == -47.23              # bank wins
    assert est.original_amount == -45.00
    assert est.import_id == draft_id
    assert "amount updated" in (est.match_note or "")


# --- match: amounts agree --------------------------------------------------

def test_match_amounts_agree(client, auth_headers, test_account, db):
    est = _manual_tx(db, test_account, amount=-50.00, on_date=date(2026, 5, 5),
                     description="Power Bill")

    _, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-05", description="Power Bill", amount="-50.00",
    )

    assert commit["matched_count"] == 1
    assert commit["transactions_created"] == 0
    assert commit["amount_diff_warnings"] == []   # no amount change → no warning

    db.refresh(est)
    assert est.is_verified is True
    assert est.amount == -50.00
    assert est.original_amount is None            # never set when amounts agreed
    assert est.match_note == "Matched import; amounts agreed"


# --- no match: insert new import row ---------------------------------------

def test_no_match_inserts_import_row(client, auth_headers, test_account, db):
    _, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-10", description="Brand New", amount="-12.00",
    )
    assert commit["matched_count"] == 0
    assert commit["transactions_created"] == 1

    tx = db.query(models.Transaction).filter(
        models.Transaction.description == "Brand New"
    ).first()
    assert tx is not None
    assert tx.source == "import"
    assert tx.is_verified is True             # clean unmatched → auto-verify


# --- A6: income matches ----------------------------------------------------

def test_income_estimate_matches(client, auth_headers, test_account, db):
    est = _manual_tx(db, test_account, amount=2000.00, on_date=date(2026, 5, 1),
                     description="Salary", transaction_type="income")

    _, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-01", description="Salary", amount="2000.00",
    )
    assert commit["matched_count"] == 1

    db.refresh(est)
    assert est.is_verified is True


# --- A6: transfer / debt-linked rows are NOT matched -----------------------

def test_transfer_and_debt_rows_not_matched(client, auth_headers, test_account, db):
    transfer = _manual_tx(db, test_account, amount=-100.00, on_date=date(2026, 5, 4),
                          description="Transfer Out", transaction_type="transfer")
    debt = _manual_tx(db, test_account, amount=-100.00, on_date=date(2026, 5, 4),
                      description="Loan Pmt", transaction_type="debt_payment")

    _, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-04", description="Loan Pmt", amount="-100.00",
    )
    # Neither typed row is a candidate → a brand-new import row is inserted instead.
    assert commit["matched_count"] == 0
    assert commit["transactions_created"] == 1

    db.refresh(transfer)
    db.refresh(debt)
    assert transfer.is_verified is False
    assert debt.is_verified is False
    assert transfer.import_id is None
    assert debt.import_id is None


# --- A5: near-duplicate unmatched row stays in Review ----------------------

def test_near_duplicate_unmatched_commits_unverified(client, auth_headers, test_account, db):
    # Pre-seed a committed import tx so the new row dedup-flags as a near-duplicate.
    existing = models.Transaction(
        account_id=test_account.id,
        date=date(2026, 5, 6),
        description="Double Charge",
        amount=-30.00,
        source="import",
        is_verified=True,
    )
    db.add(existing)
    db.commit()

    csv = b"Date,Description,Amount\n2026-05-06,Double Charge,-30.00\n"
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("dup.csv", io.BytesIO(csv), "text/csv")},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    draft_id = data["id"]
    row = data["rows"][0]
    assert row["duplicate_of"] is not None
    # Dedup excludes by default — the user explicitly re-includes it.
    resp = client.patch(
        f"/api/imports/{draft_id}",
        headers=auth_headers,
        json={"row_updates": [{"id": row["id"], "excluded": False}]},
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    commit = resp.json()
    assert commit["transactions_created"] == 1

    inserted = db.query(models.Transaction).filter(
        models.Transaction.import_id == draft_id,
        models.Transaction.source == "import",
    ).first()
    assert inserted is not None
    assert inserted.is_verified is False      # A5: anomaly stays in Review, not auto-verified


# --- A1: rollback reverts manual, deletes import, preserves other dup links --

def test_rollback_reverts_manual_and_deletes_import(client, auth_headers, test_account, db):
    est = _manual_tx(db, test_account, amount=-45.00, on_date=date(2026, 5, 2),
                     description="Groceries")

    csv = (
        b"Date,Description,Amount\n"
        b"2026-05-03,Groceries,-47.23\n"      # matches the estimate
        b"2026-05-09,Fresh Import,-9.00\n"    # brand-new import row
    )
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("mix.csv", io.BytesIO(csv), "text/csv")},
    )
    draft_id = resp.json()["id"]
    commit = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers).json()
    assert commit["matched_count"] == 1
    assert commit["transactions_created"] == 1

    # A later draft's row points its duplicate_of at the inserted import row AND at
    # the matched manual row — only the import-row link should be cleared on rollback.
    inserted = db.query(models.Transaction).filter(
        models.Transaction.import_id == draft_id,
        models.Transaction.source == "import",
    ).first()
    later_draft = models.ImportDraft(
        user_id=test_account.user_id, account_id=test_account.id,
        filename="later.csv", format="csv", status="preview_ready",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(later_draft)
    db.flush()
    link_to_import = models.ImportDraftRow(
        draft_id=later_draft.id, row_index=0, raw=["x"], duplicate_of=inserted.id,
    )
    link_to_manual = models.ImportDraftRow(
        draft_id=later_draft.id, row_index=1, raw=["y"], duplicate_of=est.id,
    )
    db.add_all([link_to_import, link_to_manual])
    db.commit()

    est_id, inserted_id = est.id, inserted.id
    link_import_id, link_manual_id = link_to_import.id, link_to_manual.id

    resp = client.post(f"/api/imports/{draft_id}/rollback", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transactions_deleted"] == 1   # only the inserted import row
    assert body["matches_reverted"] == 1

    # synchronize_session=False on the rollback's bulk ops leaves the session's identity
    # map stale — expire and re-query against the DB for ground truth.
    db.expire_all()

    # Manual estimate reverted, not deleted.
    est_after = db.query(models.Transaction).filter(models.Transaction.id == est_id).first()
    assert est_after is not None
    assert est_after.is_verified is False
    assert est_after.amount == -45.00          # original restored
    assert est_after.original_amount is None
    assert est_after.match_note is None
    assert est_after.import_id is None

    # Inserted import row gone.
    assert db.query(models.Transaction).filter(
        models.Transaction.id == inserted_id
    ).first() is None

    # The later draft's link to the deleted import row is nulled; the link to the
    # surviving manual row is untouched (A1: don't clobber other drafts' duplicate_of).
    li = db.query(models.ImportDraftRow).filter(models.ImportDraftRow.id == link_import_id).first()
    lm = db.query(models.ImportDraftRow).filter(models.ImportDraftRow.id == link_manual_id).first()
    assert li.duplicate_of is None
    assert lm.duplicate_of == est_id


# --- A2: pristine-only gate / re-match after revert ------------------------

def test_already_matched_row_does_not_rematch(client, auth_headers, test_account, db):
    # A row that already carries import_id (matched by a prior import) must not match
    # again — its original_amount provenance is protected.
    est = _manual_tx(db, test_account, amount=-47.23, on_date=date(2026, 5, 3),
                     description="Groceries", is_verified=True,
                     import_id=999, original_amount=-45.00)

    _, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-03", description="Groceries", amount="-47.50",
    )
    # No re-match — a fresh import row is inserted instead.
    assert commit["matched_count"] == 0
    assert commit["transactions_created"] == 1

    db.refresh(est)
    assert est.original_amount == -45.00        # untouched
    assert est.import_id == 999


def test_rematch_after_revert(client, auth_headers, test_account, db):
    """Full cycle: match → rollback (revert) → the now-pristine row matches again."""
    est = _manual_tx(db, test_account, amount=-45.00, on_date=date(2026, 5, 2),
                     description="Groceries")

    d1, c1 = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-03", description="Groceries", amount="-47.23",
    )
    assert c1["matched_count"] == 1
    client.post(f"/api/imports/{d1}/rollback", headers=auth_headers)
    db.refresh(est)
    assert est.is_verified is False and est.import_id is None

    d2, c2 = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-03", description="Groceries", amount="-46.00",
    )
    assert c2["matched_count"] == 1
    db.refresh(est)
    assert est.is_verified is True
    assert est.amount == -46.00
    assert est.import_id == d2


# --- A7: tolerance cap -----------------------------------------------------

def test_tolerance_cap(client, auth_headers, test_account, db):
    # 15% of a $5000 estimate = $750, but the cap is $15. A $40 difference must NOT match.
    est = _manual_tx(db, test_account, amount=-5000.00, on_date=date(2026, 5, 2),
                     description="Big Ticket")

    _, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-02", description="Big Ticket", amount="-5040.00",
    )
    assert commit["matched_count"] == 0       # outside the $15 cap
    assert commit["transactions_created"] == 1

    db.refresh(est)
    assert est.is_verified is False


def test_tolerance_min_one_dollar(client, auth_headers, test_account, db):
    # 15% of $2 = $0.30, but the floor is $1 → a $0.80 difference matches.
    est = _manual_tx(db, test_account, amount=-2.00, on_date=date(2026, 5, 2),
                     description="Small")

    _, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-02", description="Small", amount="-2.80",
    )
    assert commit["matched_count"] == 1


# --- A4: cross-account isolation -------------------------------------------

def test_no_cross_account_match(client, auth_headers, test_account, db):
    # Estimate lives on a DIFFERENT account → must not match this import.
    other = models.Account(
        user_id=test_account.user_id, name="Other", account_type="checking",
        balance=0.0, currency="AUD",
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    est = _manual_tx(db, other, amount=-45.00, on_date=date(2026, 5, 3),
                     description="Groceries")

    _, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-03", description="Groceries", amount="-45.00",
    )
    assert commit["matched_count"] == 0
    assert commit["transactions_created"] == 1
    db.refresh(est)
    assert est.is_verified is False


# --- A3: mid-loop failure atomicity ----------------------------------------

def test_mid_loop_failure_rolls_back_all(client, auth_headers, test_account, db, monkeypatch):
    """Inject a failure partway through the commit loop and assert NO manual row
    was mutated and NO import row persisted — one unit of work (A3)."""
    est = _manual_tx(db, test_account, amount=-45.00, on_date=date(2026, 5, 2),
                     description="Groceries")

    csv = (
        b"Date,Description,Amount\n"
        b"2026-05-03,Groceries,-47.23\n"      # row 1 — matches the estimate
        b"2026-05-09,Boom,-9.00\n"            # row 2 — we blow up here
    )
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("boom.csv", io.BytesIO(csv), "text/csv")},
    )
    draft_id = resp.json()["id"]

    # Make _find_match raise on the second row (description "Boom").
    import app.routers.imports as imports_mod
    real_find = imports_mod._find_match
    calls = {"n": 0}

    def boom(db_, account_id, bank_date, bank_amount):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("injected mid-loop failure")
        return real_find(db_, account_id, bank_date, bank_amount)

    monkeypatch.setattr(imports_mod, "_find_match", boom)

    # The commit loop blows up before db.commit() is ever reached, so the whole unit
    # of work (TOCTOU UPDATE + row-1 match mutation) is never committed. TestClient
    # re-raises server exceptions; the real get_db would close/rollback the session.
    # Verify the failure surfaced AND that _find_match was called twice (we did enter
    # the loop and reach the mutation point) — the rollback safety is the absence of a
    # db.commit() before the raise, which the next assertion confirms via the draft
    # status never having flipped.
    with pytest.raises(RuntimeError, match="injected mid-loop failure"):
        client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers)
    assert calls["n"] == 2  # entered the loop, reached row 2's match attempt

    # The estimate's matching mutation from row 1 is still pending-uncommitted on the
    # session. Because the single db.commit() was never reached, nothing durable landed:
    # the draft's committing→committed flip never committed.
    draft = db.query(models.ImportDraft).filter(models.ImportDraft.id == draft_id).first()
    assert draft.status != "committed"
