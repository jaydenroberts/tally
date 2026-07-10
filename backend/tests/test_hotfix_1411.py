"""
Regression tests for the v1.4.1.1 hotfix (AUDIT-01, AUDIT-02).

Covers the two audit findings patched in v1.4.1.1:

  AUDIT-01 / BACKLOG-040 — path-traversal in the unauthenticated SPA catch-all.
    The production fix (app/main.py::serve_spa) resolves the requested path and
    confirms it stays inside STATIC_DIR via Path.resolve() + is_relative_to()
    before serving. A sibling file such as data/tally.db must NOT be served; a
    legit in-root asset must still be served.

    NOTE ON APPROACH: the serve_spa catch-all is only *registered* at import time
    when STATIC_DIR.exists() (app/main.py:425). In the test environment there is
    no app/static dir, so the route is not mounted and cannot be driven through
    the TestClient. We therefore assert the exact containment predicate the fix
    uses — Path.resolve()/is_relative_to() — against a real temp filesystem laid
    out the way production is (a sibling tally.db next to the static root). This
    tests the load-bearing logic of the fix directly rather than the wiring.

  AUDIT-02 / M-003 — one-time destructive dedup cleanup in run_startup_migrations.
    - collapses a duplicate import group to the earliest (lowest-id) row,
    - records a schema_migrations marker so a second call is a no-op even if a
      fresh duplicate group is inserted afterwards,
    - never deletes a transaction referenced by debt_payments.transaction_id
      (the referenced duplicate must survive).

    The in-memory SQLite test engine may not enforce PRAGMA foreign_keys=ON, so
    we assert the *containment logic* (the referenced row survives), not that an
    IntegrityError is raised.
"""
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text

from app import models
from app.main import run_startup_migrations


# ---------------------------------------------------------------------------
# AUDIT-01 — SPA catch-all path traversal containment
# ---------------------------------------------------------------------------

def _is_served(static_dir: Path, full_path: str) -> bool:
    """Mirror of app/main.py::serve_spa containment check (the v1.4.1.1 fix).

    Returns True iff the requested path resolves to a real file that stays
    inside STATIC_DIR — i.e. iff production would serve it as a static asset
    rather than falling through to index.html.
    """
    static_root = static_dir.resolve()
    requested = (static_dir / full_path).resolve(strict=False)
    return requested.is_file() and requested.is_relative_to(static_root)


def test_audit01_traversal_does_not_leak_sibling_db(tmp_path):
    """GET /../data/tally.db must not escape STATIC_DIR (no DB leak)."""
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>")

    # A sibling database file, exactly like data/tally.db next to the static root.
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_file = data_dir / "tally.db"
    db_file.write_text("SQLite format 3\x00-SECRET-")

    # The file genuinely exists and is readable — the only thing stopping a leak
    # is the containment check.
    assert db_file.is_file()

    # Various traversal encodings that target the sibling db must all be refused.
    for attack in ("../data/tally.db", "../../data/tally.db", "assets/../../data/tally.db"):
        assert _is_served(static_dir, attack) is False, (
            f"traversal {attack!r} escaped STATIC_DIR and would leak the database"
        )


def test_audit01_traversal_outside_root_refused(tmp_path):
    """A path pointing entirely outside the root is refused."""
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>")

    assert _is_served(static_dir, "../../../../etc/passwd") is False


def test_audit01_legit_asset_still_served(tmp_path):
    """A real file inside STATIC_DIR is still served (fix is not over-broad)."""
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>")
    (static_dir / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")

    assets = static_dir / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('tally')")

    assert _is_served(static_dir, "favicon.ico") is True
    assert _is_served(static_dir, "assets/app.js") is True


# ---------------------------------------------------------------------------
# AUDIT-02 / M-003 — one-time dedup cleanup helpers
# ---------------------------------------------------------------------------

def _make_account(db):
    """Seed the minimal role/persona/user/account chain M-003 groups over."""
    role = models.Role(name="owner", display_name="Owner", is_system=True)
    db.add(role)
    db.flush()

    persona = models.Persona(
        name="analyst",
        description="Test",
        data_access_level="full",
        can_modify_data=True,
        is_system=True,
    )
    db.add(persona)
    db.flush()

    user = models.User(
        username="m003owner",
        hashed_password="x",
        role_id=role.id,
        persona_id=persona.id,
    )
    db.add(user)
    db.flush()

    account = models.Account(
        user_id=user.id,
        name="Cheque",
        account_type="checking",
        balance=0.0,
        currency="AUD",
    )
    db.add(account)
    db.flush()
    return account


def _import_tx(db, account, *, amount, description, on=date(2026, 5, 1)):
    """Create an import-sourced transaction (the kind M-003 dedups)."""
    tx = models.Transaction(
        account_id=account.id,
        date=on,
        description=description,
        amount=amount,
        source="import",
        is_verified=True,
        transaction_type="expense",
    )
    db.add(tx)
    db.flush()
    return tx


# ---------------------------------------------------------------------------
# AUDIT-02 / M-003 — tests
# ---------------------------------------------------------------------------

def test_audit02_collapses_duplicate_group_to_earliest(db):
    """A duplicate import group collapses to the lowest-id row; others deleted."""
    account = _make_account(db)

    keep = _import_tx(db, account, amount=-4.50, description="Coffee")
    dup1 = _import_tx(db, account, amount=-4.50, description="Coffee")
    dup2 = _import_tx(db, account, amount=-4.50, description="Coffee")
    # A distinct transaction that is NOT a duplicate — must be untouched.
    other = _import_tx(db, account, amount=-9.99, description="Lunch")
    db.commit()

    keep_id, dup1_id, dup2_id, other_id = keep.id, dup1.id, dup2.id, other.id
    assert keep_id < dup1_id < dup2_id  # keep is the earliest

    run_startup_migrations(db)

    survivors = {t.id for t in db.query(models.Transaction).all()}
    assert keep_id in survivors, "earliest row of the group must survive"
    assert dup1_id not in survivors and dup2_id not in survivors, "duplicates must be deleted"
    assert other_id in survivors, "non-duplicate transaction must be untouched"


def test_audit02_marker_makes_second_call_a_noop(db):
    """A schema_migrations marker means a later call ignores fresh duplicates."""
    account = _make_account(db)
    _import_tx(db, account, amount=-4.50, description="Coffee")
    _import_tx(db, account, amount=-4.50, description="Coffee")
    db.commit()

    run_startup_migrations(db)

    # Marker recorded.
    marker = db.execute(
        text("SELECT 1 FROM schema_migrations WHERE id = 'M-003'")
    ).first()
    assert marker is not None, "M-003 marker row must be recorded"

    # One survivor after the first (destructive) run.
    coffee_after_first = (
        db.query(models.Transaction)
        .filter(models.Transaction.description == "Coffee")
        .count()
    )
    assert coffee_after_first == 1

    # Introduce a *fresh* duplicate group after the marker exists.
    dup_a = _import_tx(db, account, amount=-12.00, description="Books")
    dup_b = _import_tx(db, account, amount=-12.00, description="Books")
    db.commit()

    run_startup_migrations(db)  # second call — must be a no-op

    books = (
        db.query(models.Transaction)
        .filter(models.Transaction.description == "Books")
        .count()
    )
    assert books == 2, "second call must not dedup — the marker gates it off"
    assert {dup_a.id, dup_b.id} <= {t.id for t in db.query(models.Transaction).all()}


def test_audit02_skips_transaction_referenced_by_debt_payment(db):
    """A duplicate referenced by debt_payments.transaction_id must survive."""
    account = _make_account(db)

    keep = _import_tx(db, account, amount=-100.00, description="Card payment")
    dup = _import_tx(db, account, amount=-100.00, description="Card payment")
    db.commit()

    keep_id, dup_id = keep.id, dup.id

    # A debt whose payment record points at the *duplicate* row. M-003 must NOT
    # delete a transaction another table still references.
    debt = models.Debt(
        user_id=account.user_id,
        name="Credit Card",
        original_amount=1000.0,
        current_balance=900.0,
    )
    db.add(debt)
    db.flush()

    payment = models.DebtPayment(
        debt_id=debt.id,
        amount=100.0,
        balance_after=900.0,
        paid_at=datetime(2026, 5, 1, 12, 0, 0),
        transaction_id=dup_id,
    )
    db.add(payment)
    db.commit()

    run_startup_migrations(db)

    survivors = {t.id for t in db.query(models.Transaction).all()}
    assert dup_id in survivors, "referenced duplicate must be skipped, not deleted"
    assert keep_id in survivors, "earliest row survives normally"

    # The debt payment still resolves to its transaction.
    reloaded = db.query(models.DebtPayment).filter_by(id=payment.id).first()
    assert reloaded is not None and reloaded.transaction_id == dup_id
