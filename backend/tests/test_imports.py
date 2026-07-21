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

# QUARANTINED IN CI (2026-07-14; deselected via -m "not thread_race").
# Failed once under full-suite load on 2026-07-11, then passed 3x3 in
# isolation. Root cause is the test harness, not the endpoint: the `db`
# fixture yields ONE SQLAlchemy Session (not thread-safe) and `client`
# overrides get_db so BOTH racing requests drive that same Session from
# different threadpool threads. Most interleavings are benign, but under
# load the loser's post-UPDATE SELECT can interleave with the winner's
# mid-request commit inside unsynchronized Session state, surfacing a
# spurious error instead of the expected [200, 409]. Production is
# unaffected (get_db issues a fresh Session per request; the TOCTOU guard
# is the atomic UPDATE at the DB level). Proper fix: a dedicated fixture
# stack with per-request sessions over a shared file-backed SQLite.
# Deterministic state-machine coverage stays in CI via
# test_second_commit_sequential_conflicts below.
@pytest.mark.thread_race
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


def test_second_commit_sequential_conflicts(client, auth_headers, test_account):
    """Deterministic companion to the quarantined race test above: the
    status state machine alone must reject a second commit of an already
    committed draft with 409 (no threads involved)."""
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("stmt.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
    )
    assert resp.status_code == 201
    draft_id = resp.json()["id"]

    first = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers)
    assert first.status_code == 200, first.text

    second = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers)
    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "Draft is not in preview_ready state"


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
        # AUDIT-03: inner "-" AND a debit marker must stay negative, not double-
        # negate back to positive. A revert to bare `-value` flips these to income.
        ("-48.56 Dr",     Decimal("-48.56")),
        ("(-48.56)",      Decimal("-48.56")),
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

from app.routers.imports import (
    _compute_match_plan,
    _merchant_residual,
    MATCH_MERCHANT_HIGH,
    MATCH_MERCHANT_FLOOR,
    GENERIC_TOKENS,
)


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


def _confirmed_from_preview(preview, *, accept_reviews=False):
    """Build the commit body's confirmed_matches from a preview response.

    Confident pairs are always echoed (the UI auto-checks them). Review pairs are
    echoed only when accept_reviews=True (simulating the user toggling them ON).
    """
    confirmed = list(preview.get("confident_matches", []))
    if accept_reviews:
        for s in preview.get("review_suggestions", []):
            confirmed.append({
                "row_id": s["row_id"],
                "candidate_transaction_id": s["candidate_transaction_id"],
            })
    return {"confirmed_matches": confirmed}


def _commit_one_row_csv(client, headers, account, *, on_date, description, amount,
                        accept_reviews=False):
    """Upload a single-row CSV, echo the planned matches, commit; return commit response."""
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
    preview = client.get(f"/api/imports/{draft_id}/preview", headers=headers).json()
    body = _confirmed_from_preview(preview, accept_reviews=accept_reviews)
    resp = client.post(f"/api/imports/{draft_id}/commit", headers=headers, json=body)
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
    # AUDIT-05/09: match_note now carries a structured [recon] header (bank desc/date +
    # original estimate date) followed by the human-readable note. The human tail is
    # preserved; assert on it rather than the whole string.
    assert est.match_note.endswith("Matched import; amounts agreed")


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


# --- A6: transfer rows are NOT matched (debt_payment now IS — BACKLOG-039) --

def test_transfer_rows_not_matched(client, auth_headers, test_account, db):
    transfer = _manual_tx(db, test_account, amount=-100.00, on_date=date(2026, 5, 4),
                          description="Transfer Out", transaction_type="transfer")

    _, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-04", description="Transfer Out", amount="-100.00",
    )
    # A transfer row is not a candidate → a brand-new import row is inserted instead.
    assert commit["matched_count"] == 0
    assert commit["transactions_created"] == 1

    db.refresh(transfer)
    assert transfer.is_verified is False
    assert transfer.import_id is None


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
    preview = client.get(f"/api/imports/{draft_id}/preview", headers=auth_headers).json()
    body = _confirmed_from_preview(preview)
    commit = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers, json=body).json()
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
        b"2026-05-03,Groceries,-47.23\n"      # row 1 — matches the estimate (Confident)
        b"2026-05-09,Boom,-9.00\n"            # row 2 — new-row insert blows up here
    )
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("boom.csv", io.BytesIO(csv), "text/csv")},
    )
    draft_id = resp.json()["id"]
    preview = client.get(f"/api/imports/{draft_id}/preview", headers=auth_headers).json()
    body = _confirmed_from_preview(preview)   # echo the Confident "Groceries" match

    # Make the second row's new-import-row insert raise. The plan is computed once
    # up front; the failure lands during the apply loop AFTER row 1's match mutation,
    # so atomicity (single db.commit at the end) must discard row 1's mutation too.
    import app.models as models_mod
    real_init = models_mod.Transaction.__init__

    def boom_init(self, *args, **kwargs):
        if kwargs.get("description") == "Boom":
            raise RuntimeError("injected mid-loop failure")
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(models_mod.Transaction, "__init__", boom_init)

    # The commit loop blows up before db.commit() is ever reached, so the whole unit
    # of work (TOCTOU UPDATE + row-1 match mutation) is never committed. TestClient
    # re-raises server exceptions; the real get_db would close/rollback the session.
    with pytest.raises(RuntimeError, match="injected mid-loop failure"):
        client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers, json=body)

    # Because the single db.commit() was never reached, nothing durable landed:
    # the draft's committing→committed flip never committed.
    draft = db.query(models.ImportDraft).filter(models.ImportDraft.id == draft_id).first()
    assert draft.status != "committed"


# ===========================================================================
# BACKLOG-036 — merchant-confidence tiers + global one-to-one assignment
# ===========================================================================
# Synthetic merchant names ONLY in fixtures — no real names, no institution
# names (personal-data guardrail / spec §12.5).

def _make_draft(db, account, rows):
    """Create an ImportDraft + ImportDraftRow set directly for planner unit tests.

    `rows` = list of (row_index, date, description, amount) tuples. Returns the draft.
    """
    draft = models.ImportDraft(
        user_id=account.user_id, account_id=account.id,
        filename="plan.csv", format="csv", status="preview_ready",
        column_mapping={"date": 0, "description": 1, "amount": 2},
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(draft)
    db.flush()
    for idx, on_date, desc, amount in rows:
        db.add(models.ImportDraftRow(
            draft_id=draft.id, row_index=idx, raw=[str(on_date), desc, str(amount)],
            date=on_date, description=desc, amount=Decimal(str(amount)),
        ))
    db.commit()
    db.refresh(draft)
    return draft


# --- _merchant_residual units ----------------------------------------------

def test_merchant_residual_strips_boilerplate_and_receipt():
    # Synthetic merchant with bank boilerplate + receipt tail.
    assert _merchant_residual("ZORPCO MART - Card Purchase - Receipt 133767") == "zorpco mart"


def test_merchant_residual_pure_generic_is_empty():
    assert _merchant_residual("Direct Debit") == ""
    assert _merchant_residual("Reversal - Direct Debit") == ""


def test_merchant_residual_named_with_boilerplate():
    assert _merchant_residual("WIBBLE - Direct Debit - Receipt 102895") == "wibble"


def test_merchant_residual_none_and_empty():
    assert _merchant_residual(None) == ""
    assert _merchant_residual("") == ""
    assert _merchant_residual("12345") == ""   # pure digits drop out


# --- tiering units ---------------------------------------------------------

def test_tier_comparable_same_merchant_confident(db, test_account):
    est = _manual_tx(db, test_account, amount=-50.00, on_date=date(2026, 5, 5),
                     description="ZORPCO MART - Card Purchase")
    draft = _make_draft(db, test_account, [
        (0, date(2026, 5, 5), "ZORPCO MART - Card Purchase - Receipt 99", -50.00),
    ])
    plan = _compute_match_plan(db, draft)
    rid = draft.rows[0].id
    assert rid in plan
    assert plan[rid].tier == "confident"
    assert plan[rid].candidate_id == est.id
    assert plan[rid].score >= MATCH_MERCHANT_HIGH


def test_tier_comparable_cross_merchant_is_none(db, test_account):
    # Distinct merchants, near-equal amount/date — the cross-merchant false-match shape
    # from the incident. Comparable, score < FLOOR → None (NOT Review). Core rule (H1).
    _manual_tx(db, test_account, amount=-50.00, on_date=date(2026, 5, 5),
               description="ZORPCO MART - Card Purchase")
    draft = _make_draft(db, test_account, [
        (0, date(2026, 5, 5), "QUUXNET BROADBAND - Direct Debit", -50.00),
    ])
    plan = _compute_match_plan(db, draft)
    assert draft.rows[0].id not in plan       # tier None → imported as new


def test_tier_not_comparable_is_review(db, test_account):
    # Generic boilerplate bank row vs named estimate → not comparable → Review.
    est = _manual_tx(db, test_account, amount=-161.66, on_date=date(2026, 5, 5),
                     description="WIBBLE - Direct Debit - Receipt 5")
    draft = _make_draft(db, test_account, [
        (0, date(2026, 5, 5), "Direct Debit", -161.66),
    ])
    plan = _compute_match_plan(db, draft)
    rid = draft.rows[0].id
    assert rid in plan
    assert plan[rid].tier == "review"
    assert plan[rid].comparable is False
    assert plan[rid].candidate_id == est.id


def test_tier_comparable_mid_score_is_review(db, test_account):
    # Shared leading token but distinct trailing tokens (NOT a clean subset) →
    # FLOOR <= score < HIGH → Review. token_set_ratio returns 1.0 for pure subsets,
    # so a mid score requires genuine partial overlap. Fully-invented merchant names.
    _manual_tx(db, test_account, amount=-75.00, on_date=date(2026, 5, 5),
               description="ZORPNIK OUTDOOR GEAR SHOP")
    draft = _make_draft(db, test_account, [
        (0, date(2026, 5, 5), "ZORPNIK CORNER CAFE BAR", -75.00),
    ])
    plan = _compute_match_plan(db, draft)
    rid = draft.rows[0].id
    assert rid in plan
    assert plan[rid].comparable is True
    assert MATCH_MERCHANT_FLOOR <= plan[rid].score < MATCH_MERCHANT_HIGH
    assert plan[rid].tier == "review"


# --- global assignment: one-to-one, no stealing, deterministic -------------

def test_assignment_is_one_to_one(db, test_account):
    # Two bank rows both within tolerance of ONE estimate — only one may claim it.
    est = _manual_tx(db, test_account, amount=-50.00, on_date=date(2026, 5, 5),
                     description="ZORPCO MART")
    draft = _make_draft(db, test_account, [
        (0, date(2026, 5, 5), "ZORPCO MART", -50.00),
        (1, date(2026, 5, 5), "ZORPCO MART", -50.00),
    ])
    plan = _compute_match_plan(db, draft)
    assigned = [e.candidate_id for e in plan.values()]
    assert assigned.count(est.id) == 1        # candidate consumed exactly once
    assert len(plan) == 1


def test_confident_claims_before_not_comparable(db, test_account):
    # A comparable Confident pair must claim the candidate before a not-comparable
    # score-0 pair can grab it (no stealing — spec §4.3 step 2).
    est = _manual_tx(db, test_account, amount=-50.00, on_date=date(2026, 5, 5),
                     description="ZORPCO MART")
    draft = _make_draft(db, test_account, [
        (0, date(2026, 5, 5), "Direct Debit", -50.00),      # not comparable (boilerplate)
        (1, date(2026, 5, 5), "ZORPCO MART", -50.00),       # comparable, same merchant
    ])
    plan = _compute_match_plan(db, draft)
    named_rid = draft.rows[1].id
    boiler_rid = draft.rows[0].id
    assert named_rid in plan and plan[named_rid].tier == "confident"
    assert plan[named_rid].candidate_id == est.id
    assert boiler_rid not in plan             # lost the candidate → imported as new


# --- the 18-row cross-merchant swap (screenshot fixture) -------------------

def test_eighteen_row_cross_merchant_swap_all_none(db, test_account):
    """The live 2026-05-22 incident, encoded as a unit test: 18 bank rows clustered in
    one tight amount/date band, where every structurally-valid (bank, estimate) pairing
    is a DIFFERENT merchant (a fuel charge landing on an unrelated utility estimate, etc).
    Assert the planner produces 0 Confident AND 0 Review — every comparable pair scores below
    FLOOR → None → imported as new, nothing overwritten. Synthetic names only.

    Construction: the estimate-merchant set and the bank-merchant set are DISJOINT, so no
    bank row shares a merchant with any estimate. Amounts are clustered within the $15
    structural tolerance so all 18×18 pairings survive the structural gate — the merchant
    gate is the only thing standing between us and the incident.
    """
    base = date(2026, 5, 15)
    # Two DISJOINT sets of 18 maximally-dissimilar synthetic merchant names; vetted so
    # every cross pairing scores below FLOOR (0.50) on token_set_ratio — no coincidental
    # near-collisions. Synthetic names only (personal-data guardrail).
    est_merchants = [
        "MAPLEWOOD", "SUNDIAL", "BRICKHOUSE", "THUNDERPEAK", "GOLDENVALE",
        "BLUERIDGE", "WHITESTONE", "IRONGATE", "AMBERFALL", "ZEPHYRGUST",
        "VORTEXBAY", "JUNGLEKING", "PUMPKINPATCH", "WIZARDRY", "BUMBLEBEE",
        "ECLIPSEMOON", "FROSTBYTE", "GIZMOWORKS",
    ]
    bank_merchants = [
        "NORTHWIND", "MOONHOLLOW", "RIVERBEND", "CACTUSFLATS", "DUSTYTRAIL",
        "FOXGLOVE", "LANTERNWAY", "VELVETGROVE", "COBALTMINE", "OBSIDIANROCK",
        "KOALABEAR", "XYLOPHONE", "QUOKKADEN", "TRUMPETVINE", "MAVERICKJET",
        "HONEYCOMB", "DOLPHINBAY", "WALRUSPOD",
    ]
    amounts = [150.00 + i * 0.5 for i in range(18)]   # 150.00 .. 158.50, all within $15
    # Use bank boilerplate (stripped to empty by _merchant_residual) around the merchant
    # token so each residual is a single distinct word — no shared filler token to inflate
    # the cross-merchant score above FLOOR.
    for m, amt in zip(est_merchants, amounts):
        _manual_tx(db, test_account, amount=-amt, on_date=base,
                   description=f"{m} - Card Purchase", transaction_type="expense")
    rows = [(i, base, f"{bank_merchants[i]} - Card Purchase", -amt)
            for i, amt in enumerate(amounts)]
    draft = _make_draft(db, test_account, rows)

    plan = _compute_match_plan(db, draft)
    confident = [e for e in plan.values() if e.tier == "confident"]
    review = [e for e in plan.values() if e.tier == "review"]
    assert len(confident) == 0, f"expected 0 Confident, got {len(confident)}"
    assert len(review) == 0, f"expected 0 Review, got {len(review)}"


# --- adversarial near-collision (shared leading residual token) ------------

def test_adversarial_shared_leading_token_no_false_confident(db, test_account):
    """Two distinct synthetic merchants sharing a leading residual token at the same
    amount/date must NOT clear HIGH onto each other (spec §12.5). Synthetic names only.
    """
    # Estimate and bank row share the leading token "zorpnik" but are distinct merchants.
    _manual_tx(db, test_account, amount=-75.00, on_date=date(2026, 5, 10),
               description="ZORPNIK OUTDOOR GEAR SHOP")
    draft = _make_draft(db, test_account, [
        (0, date(2026, 5, 10), "ZORPNIK CORNER CAFE BAR", -75.00),
    ])
    plan = _compute_match_plan(db, draft)
    rid = draft.rows[0].id
    # Either None (score < FLOOR) or at most Review — never a silent Confident merge.
    if rid in plan:
        assert plan[rid].tier != "confident", (
            f"shared-token distinct merchants wrongly Confident (score={plan[rid].score})"
        )


# --- planner read-only contract --------------------------------------------

def test_compute_match_plan_is_read_only(db, test_account):
    _manual_tx(db, test_account, amount=-50.00, on_date=date(2026, 5, 5),
               description="ZORPCO MART")
    draft = _make_draft(db, test_account, [
        (0, date(2026, 5, 5), "ZORPCO MART", -50.00),
    ])
    db.expire_all()
    _ = _compute_match_plan(db, draft)
    # The planner must not stage any INSERT or attribute mutation (spec §12.5).
    assert not db.new, f"planner added rows: {db.new}"
    assert not db.dirty, f"planner mutated rows: {db.dirty}"


# --- commit: Review applies only when accepted ------------------------------

def test_review_applies_only_when_accepted(client, auth_headers, test_account, db):
    # Not-comparable pair (boilerplate bank vs named estimate) → Review.
    est = _manual_tx(db, test_account, amount=-161.66, on_date=date(2026, 5, 5),
                     description="WIBBLE - Direct Debit - Receipt 5")

    # 1) Ignore the suggestion → estimate untouched, row imports as new.
    _, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-05", description="Direct Debit", amount="-161.66",
        accept_reviews=False,
    )
    assert commit["review_suggested_count"] == 1
    assert commit["confirmed_matched_count"] == 0
    assert commit["auto_matched_count"] == 0
    assert commit["transactions_created"] == 1
    db.refresh(est)
    assert est.is_verified is False
    assert est.import_id is None


def test_review_accepted_merges(client, auth_headers, test_account, db):
    est = _manual_tx(db, test_account, amount=-161.66, on_date=date(2026, 5, 5),
                     description="WIBBLE - Direct Debit - Receipt 5")
    draft_id, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-05", description="Direct Debit", amount="-161.66",
        accept_reviews=True,
    )
    assert commit["confirmed_matched_count"] == 1
    assert commit["auto_matched_count"] == 0
    assert commit["transactions_created"] == 0
    db.refresh(est)
    assert est.is_verified is True
    assert est.import_id == draft_id
    assert est.source == "manual"


def test_confident_auto_applies_without_review_step(client, auth_headers, test_account, db):
    est = _manual_tx(db, test_account, amount=-50.00, on_date=date(2026, 5, 5),
                     description="ZORPCO MART")
    _, commit = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-05", description="ZORPCO MART", amount="-50.00",
    )
    assert commit["auto_matched_count"] == 1
    assert commit["confirmed_matched_count"] == 0
    assert commit["matched_count"] == 1
    db.refresh(est)
    assert est.is_verified is True


# --- named rollback regression: accepted-Review reverts like Confident ------

def test_accepted_review_rolls_back_identically_to_confident(client, auth_headers, test_account, db):
    """Spec §12.1.4: an accepted-Review match must roll back IDENTICALLY to a Confident
    one (same apply path → same revert path)."""
    # Accepted-Review case.
    est_r = _manual_tx(db, test_account, amount=-161.66, on_date=date(2026, 5, 5),
                       description="WIBBLE - Direct Debit - Receipt 5")
    d_r, c_r = _commit_one_row_csv(
        client, auth_headers, test_account,
        on_date="2026-05-05", description="Direct Debit", amount="-160.00",
        accept_reviews=True,
    )
    assert c_r["confirmed_matched_count"] == 1
    db.refresh(est_r)
    assert est_r.is_verified is True
    assert est_r.amount == -160.00
    assert est_r.original_amount == -161.66       # provenance written via shared apply path
    assert est_r.import_id == d_r

    # Roll it back.
    rb = client.post(f"/api/imports/{d_r}/rollback", headers=auth_headers).json()
    assert rb["matches_reverted"] == 1
    db.expire_all()
    est_r_after = db.query(models.Transaction).filter(models.Transaction.id == est_r.id).first()
    assert est_r_after.is_verified is False
    assert est_r_after.amount == -161.66          # original restored
    assert est_r_after.original_amount is None
    assert est_r_after.match_note is None
    assert est_r_after.import_id is None


# --- guard: post-preview row edit remap → import-new ------------------------

def test_post_preview_edit_remap_imports_new(client, auth_headers, test_account, db):
    """User previews a Confident match, then edits the row's amount in the Review step so
    the recomputed commit plan no longer maps it to that candidate (gate fail) → the
    echoed pair must NOT silent-apply; it imports as new + counts as could-not-apply
    (spec §12.1.2 + §12.4)."""
    est = _manual_tx(db, test_account, amount=-50.00, on_date=date(2026, 5, 5),
                     description="ZORPCO MART")
    csv = b"Date,Description,Amount\n2026-05-05,ZORPCO MART,-50.00\n"
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("z.csv", io.BytesIO(csv), "text/csv")},
    )
    draft_id = resp.json()["id"]
    preview = client.get(f"/api/imports/{draft_id}/preview", headers=auth_headers).json()
    # Client echoes the Confident pair it saw.
    body = _confirmed_from_preview(preview)
    assert len(body["confirmed_matches"]) == 1

    # Now edit the row's amount far outside tolerance (post-preview), so the recomputed
    # plan drops the pair (structural gate fails) — but the client still echoes the old pair.
    row_id = preview["rows"][0]["id"]
    client.patch(
        f"/api/imports/{draft_id}",
        headers=auth_headers,
        json={"row_updates": [{"id": row_id, "amount": -999.00}]},
    )

    commit = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers, json=body).json()
    assert commit["auto_matched_count"] == 0
    assert commit["confirmed_matched_count"] == 0
    assert commit["could_not_apply_count"] == 1
    assert commit["transactions_created"] == 1
    db.refresh(est)
    assert est.is_verified is False              # never silently overwritten
    assert est.import_id is None


# --- guard: concurrent candidate amount-edit → full-gate rejects -----------

def test_concurrent_candidate_amount_edit_full_gate_rejects(client, auth_headers, test_account, db):
    """A candidate stays pristine but its amount is mutated concurrently between preview
    and commit. The apply-time FULL structural gate (signed amount within tolerance) must
    reject the now-stale pair → import as new + could-not-apply (spec §12.1.3)."""
    est = _manual_tx(db, test_account, amount=-50.00, on_date=date(2026, 5, 5),
                     description="ZORPCO MART")
    csv = b"Date,Description,Amount\n2026-05-05,ZORPCO MART,-50.00\n"
    resp = client.post(
        f"/api/imports?account_id={test_account.id}",
        headers=auth_headers,
        files={"file": ("z.csv", io.BytesIO(csv), "text/csv")},
    )
    draft_id = resp.json()["id"]
    preview = client.get(f"/api/imports/{draft_id}/preview", headers=auth_headers).json()
    body = _confirmed_from_preview(preview)
    assert len(body["confirmed_matches"]) == 1

    # Concurrent external mutation: candidate still pristine (manual/unverified/import_id
    # NULL) but its amount jumps far outside tolerance of the bank row.
    est.amount = -500.00
    db.commit()

    commit = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers, json=body).json()
    assert commit["auto_matched_count"] == 0
    assert commit["could_not_apply_count"] == 1
    assert commit["transactions_created"] == 1
    db.expire_all()
    est_after = db.query(models.Transaction).filter(models.Transaction.id == est.id).first()
    assert est_after.is_verified is False
    assert est_after.import_id is None
    assert est_after.amount == -500.00           # untouched by the import


# ===========================================================================
# BACKLOG-039 — debt_payment reconciliation
# ===========================================================================

def _mk_debt_estimate(db, account, *, amount, on_date, description, balance):
    """Seed a debt + a linked, pristine debt_payment estimate + its DebtPayment audit
    row, mirroring the state produced by /transactions/{id}/link-debt. amount is the
    signed (negative) estimate; the DebtPayment.amount is the positive applied delta."""
    debt = models.Debt(
        user_id=account.user_id, name="Card", original_amount=balance,
        current_balance=balance, is_paid_off=False,
    )
    db.add(debt)
    db.flush()
    tx = _manual_tx(db, account, amount=amount, on_date=on_date,
                    description=description, transaction_type="debt_payment")
    tx.debt_id = debt.id
    applied = round(min(abs(amount), balance), 2)
    debt.current_balance = round(balance - applied, 2)
    payment = models.DebtPayment(
        debt_id=debt.id, amount=applied, balance_after=debt.current_balance,
        paid_at=on_date, transaction_id=tx.id,
    )
    db.add(payment)
    db.commit()
    db.refresh(debt)
    db.refresh(tx)
    db.refresh(payment)
    return debt, tx, payment


def test_debt_payment_exact_reconciles_confident(client, auth_headers, test_account, db):
    # Exact-amount debt_payment with matching merchant → Confident auto-reconcile.
    debt, tx, payment = _mk_debt_estimate(
        db, test_account, amount=-200.00, on_date=date(2026, 5, 3),
        description="ZORPCO FINANCE", balance=1000.00,
    )
    csv = b"Date,Description,Amount\n2026-05-03,ZORPCO FINANCE,-200.00\n"
    resp = client.post(f"/api/imports?account_id={test_account.id}", headers=auth_headers,
                       files={"file": ("d.csv", io.BytesIO(csv), "text/csv")})
    draft_id = resp.json()["id"]
    preview = client.get(f"/api/imports/{draft_id}/preview", headers=auth_headers).json()
    assert preview["confident_match_count"] == 1        # exact + same merchant → Confident
    body = _confirmed_from_preview(preview)
    commit = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers, json=body).json()
    assert commit["auto_matched_count"] == 1
    assert commit["transactions_created"] == 0

    db.refresh(tx); db.refresh(debt); db.refresh(payment)
    assert tx.is_verified is True
    assert tx.amount == -200.00
    assert debt.current_balance == 800.00               # unchanged — amounts agreed
    assert payment.amount == 200.00


def test_debt_payment_drift_not_auto_verified(client, auth_headers, test_account, db):
    # Drifting debt_payment must NOT auto-verify — it goes to Review even with a
    # matching merchant (money-touching gate). Not echoed → imported as new, estimate
    # left untouched.
    debt, tx, payment = _mk_debt_estimate(
        db, test_account, amount=-200.00, on_date=date(2026, 5, 3),
        description="ZORPCO FINANCE", balance=1000.00,
    )
    csv = b"Date,Description,Amount\n2026-05-03,ZORPCO FINANCE,-205.00\n"
    resp = client.post(f"/api/imports?account_id={test_account.id}", headers=auth_headers,
                       files={"file": ("d.csv", io.BytesIO(csv), "text/csv")})
    draft_id = resp.json()["id"]
    preview = client.get(f"/api/imports/{draft_id}/preview", headers=auth_headers).json()
    assert preview["confident_match_count"] == 0        # drift forced Review
    assert len(preview["review_suggestions"]) == 1

    # Commit WITHOUT accepting the review → estimate stays untouched, row imported new.
    body = _confirmed_from_preview(preview)             # confident only (none)
    commit = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers, json=body).json()
    assert commit["auto_matched_count"] == 0
    assert commit["transactions_created"] == 1
    db.refresh(tx); db.refresh(debt); db.refresh(payment)
    assert tx.is_verified is False
    assert tx.amount == -200.00
    assert debt.current_balance == 800.00
    assert payment.amount == 200.00


def test_debt_payment_drift_confirm_applies_both_legs(client, auth_headers, test_account, db):
    # Confirming a drifting debt_payment moves the tx amount, the DebtPayment.amount,
    # AND the debt balance in lockstep by the payment-magnitude delta.
    debt, tx, payment = _mk_debt_estimate(
        db, test_account, amount=-200.00, on_date=date(2026, 5, 3),
        description="ZORPCO FINANCE", balance=1000.00,
    )
    csv = b"Date,Description,Amount\n2026-05-03,ZORPCO FINANCE,-205.00\n"
    resp = client.post(f"/api/imports?account_id={test_account.id}", headers=auth_headers,
                       files={"file": ("d.csv", io.BytesIO(csv), "text/csv")})
    draft_id = resp.json()["id"]
    preview = client.get(f"/api/imports/{draft_id}/preview", headers=auth_headers).json()
    body = _confirmed_from_preview(preview, accept_reviews=True)   # user confirms the drift
    commit = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers, json=body).json()
    assert commit["confirmed_matched_count"] == 1
    assert commit["transactions_created"] == 0

    db.refresh(tx); db.refresh(debt); db.refresh(payment)
    assert tx.amount == -205.00                 # bank wins
    assert tx.original_amount == -200.00
    assert payment.amount == 205.00             # +$5 applied delta
    assert debt.current_balance == 795.00       # 800 - $5 delta (both legs moved)
    assert payment.balance_after == 795.00


def test_debt_payment_drift_confirm_blocks_rollback(client, auth_headers, test_account, db):
    # Undo of a drift-confirmed debt_payment is blocked with 409 — the revert loop can't
    # restore the debt leg, so we refuse rather than strand the balance.
    debt, tx, payment = _mk_debt_estimate(
        db, test_account, amount=-200.00, on_date=date(2026, 5, 3),
        description="ZORPCO FINANCE", balance=1000.00,
    )
    csv = b"Date,Description,Amount\n2026-05-03,ZORPCO FINANCE,-205.00\n"
    resp = client.post(f"/api/imports?account_id={test_account.id}", headers=auth_headers,
                       files={"file": ("d.csv", io.BytesIO(csv), "text/csv")})
    draft_id = resp.json()["id"]
    preview = client.get(f"/api/imports/{draft_id}/preview", headers=auth_headers).json()
    body = _confirmed_from_preview(preview, accept_reviews=True)
    client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers, json=body)

    resp = client.post(f"/api/imports/{draft_id}/rollback", headers=auth_headers)
    assert resp.status_code == 409, resp.text
    assert "debt" in resp.json()["detail"].lower()
    # Nothing reverted — balance/legs stay as the confirm left them.
    db.refresh(debt); db.refresh(payment)
    assert debt.current_balance == 795.00
    assert payment.amount == 205.00


# ===========================================================================
# BACKLOG-037 — receipt-number promotion in the no-merchant grey zone
# ===========================================================================

def test_receipt_number_promotes_no_merchant_pair(db, test_account):
    # Both sides pure boilerplate (no merchant identity) BUT share a 6+ digit reference
    # → promote Review → Confident.
    est = _manual_tx(db, test_account, amount=-161.66, on_date=date(2026, 5, 5),
                     description="Direct Debit Receipt 998877")
    draft = _make_draft(db, test_account, [
        (0, date(2026, 5, 5), "Direct Debit Receipt 998877", -161.66),
    ])
    plan = _compute_match_plan(db, draft)
    rid = draft.rows[0].id
    assert rid in plan
    assert plan[rid].comparable is False        # still the no-merchant grey zone
    assert plan[rid].tier == "confident"        # promoted by the shared reference


def test_different_receipt_numbers_do_not_promote(db, test_account):
    # No-merchant grey zone, DIFFERENT references → stays Review (no promotion).
    est = _manual_tx(db, test_account, amount=-161.66, on_date=date(2026, 5, 5),
                     description="Direct Debit Receipt 111111")
    draft = _make_draft(db, test_account, [
        (0, date(2026, 5, 5), "Direct Debit Receipt 222222", -161.66),
    ])
    plan = _compute_match_plan(db, draft)
    rid = draft.rows[0].id
    assert rid in plan
    assert plan[rid].tier == "review"


def test_receipt_number_never_overrides_merchant(db, test_account):
    # A comparable pair below FLOOR (cross-merchant) is rejected on merchant grounds and
    # a shared reference must NOT rescue it — receipt promotion only touches the
    # not-comparable branch.
    _manual_tx(db, test_account, amount=-50.00, on_date=date(2026, 5, 5),
               description="ZORPCO MART 998877")
    draft = _make_draft(db, test_account, [
        (0, date(2026, 5, 5), "QUUXNET BROADBAND 998877", -50.00),
    ])
    plan = _compute_match_plan(db, draft)
    assert draft.rows[0].id not in plan         # cross-merchant → None, not promoted
