"""
M-012 — the v1.4.7 transaction-type repair (BASTION conditions 1-6, 8).

Every test here runs against its own file-backed SQLite database, created the
way a real install creates it, because the properties under test are about
real transactions: a rollback must undo everything, and a marker must survive
to the next start. The shared in-memory session in conftest.py is bound to an
outer transaction that a rollback would take with it, which would make the
failure-injection test pass for the wrong reason.
"""
import logging
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app import main, models, type_repair
from app.database import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def file_db(tmp_path):
    """A fresh file-backed database with the production pragmas."""
    engine = create_engine(f"sqlite:///{tmp_path / 'tally.db'}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _user_and_accounts(db):
    role = models.Role(name="owner", display_name="Owner", is_system=True)
    persona = models.Persona(name="p", description="", data_access_level="full",
                             can_modify_data=True, is_system=True)
    db.add_all([role, persona])
    db.flush()
    user = models.User(username="u", hashed_password="x", role_id=role.id, persona_id=persona.id)
    db.add(user)
    db.flush()
    a = models.Account(user_id=user.id, name="Everyday", account_type="checking", balance=0)
    b = models.Account(user_id=user.id, name="Card", account_type="credit", balance=0)
    db.add_all([a, b])
    db.commit()
    return user, a, b


def _tx(db, account, amount, ttype="expense", source="import", notes=None, **kw):
    tx = models.Transaction(
        account_id=account.id, date=kw.pop("ddate", date(2026, 10, 5)), description="t",
        amount=amount, source=source, is_verified=source == "import",
        transaction_type=ttype, notes=notes, **kw,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def _seed_every_group(db):
    """One row per group M-012 must take or leave. Returns {name: tx}."""
    user, acct, card = _user_and_accounts(db)
    debt = models.Debt(user_id=user.id, name="Loan", original_amount=500,
                       current_balance=500, is_paid_off=False)
    goal = models.SavingsGoal(user_id=user.id, name="Goal", target_amount=500,
                              current_amount=0, is_completed=False)
    db.add_all([debt, goal])
    db.commit()

    rows = {
        # --- taken ---
        "import_credit": _tx(db, acct, 50.0),
        "recurring_credit": _tx(db, acct, 1200.0, source="manual",
                                notes="Auto-generated from recurring: Pay"),
        "other_credit": _tx(db, acct, 30.0, source="manual"),   # coach flip / unlinked leg / raw API
        # --- left alone ---
        "import_debit": _tx(db, acct, -20.0),
        "already_income": _tx(db, acct, 900.0, ttype="income"),
        "zero": _tx(db, acct, 0.0),
        "transfer_leg": _tx(db, card, 75.0, ttype="transfer"),
        "paired_expense": _tx(db, card, 76.0),                  # pair id set, type still expense
        "debt_linked": _tx(db, acct, 40.0, debt_id=debt.id),
        "goal_linked": _tx(db, acct, 45.0, savings_goal_id=goal.id),
        "debt_child": _tx(db, acct, 41.0),                      # referenced by a DebtPayment only
        "goal_child": _tx(db, acct, 46.0),                      # referenced by a contribution only
    }
    rows["paired_expense"].transfer_pair_id = rows["transfer_leg"].id
    db.add_all([
        models.DebtPayment(debt_id=debt.id, amount=41.0, balance_after=459.0,
                           transaction_id=rows["debt_child"].id),
        # Condition 3: a debt payment recorded with NO transaction. Without the
        # IS NOT NULL filter this NULL makes every NOT IN unknown → 0 rows taken.
        models.DebtPayment(debt_id=debt.id, amount=10.0, balance_after=449.0, transaction_id=None),
        models.SavingsContribution(goal_id=goal.id, amount=46.0, balance_after=46.0,
                                   transaction_id=rows["goal_child"].id),
        models.SavingsContribution(goal_id=goal.id, amount=5.0, balance_after=51.0,
                                   transaction_id=None),
    ])
    db.commit()
    return rows


def _types(db):
    return dict(db.execute(text("SELECT id, transaction_type FROM transactions")).fetchall())


def _marker(db):
    return db.execute(text("SELECT 1 FROM schema_migrations WHERE id='M-012'")).first() is not None


def _ledger(db, reason_like="M-012/%"):
    return db.execute(text(
        "SELECT transaction_id, from_type, to_type, reason FROM transaction_type_changes "
        "WHERE reason LIKE :r ORDER BY transaction_id"), {"r": reason_like}).fetchall()


# ---------------------------------------------------------------------------
# Condition 1 — runs last; fresh and old databases both migrate
# ---------------------------------------------------------------------------

def test_m012_fresh_empty_database_starts_and_records_marker(file_db):
    main.seed_database(file_db)
    main.run_startup_migrations(file_db)
    assert _marker(file_db)
    assert _ledger(file_db) == []


def test_m012_old_database_without_schema_migrations_or_pair_column(file_db):
    """An install that predates M-003 and M-007: no schema_migrations table and no
    transfer_pair_id column. M-012 reads both, so it only works if it runs after
    the migrations that create them."""
    rows = {"credit": _tx(file_db, _user_and_accounts(file_db)[1], 60.0)}
    file_db.execute(text("DROP TABLE IF EXISTS schema_migrations"))
    file_db.execute(text("DROP INDEX IF EXISTS ix_transactions_transfer_pair_id"))
    file_db.execute(text("ALTER TABLE transactions DROP COLUMN transfer_pair_id"))
    file_db.commit()

    main.run_startup_migrations(file_db)

    cols = [r[1] for r in file_db.execute(text("PRAGMA table_info(transactions)")).fetchall()]
    assert "transfer_pair_id" in cols
    assert _marker(file_db)
    assert _types(file_db)[rows["credit"].id] == "income"


def test_m012_is_the_last_startup_migration():
    """Guard against someone appending a migration after it."""
    import inspect
    body = inspect.getsource(main.run_startup_migrations).rstrip().splitlines()
    tail = [line.strip() for line in body if line.strip() and not line.strip().startswith("#")][-2:]
    assert tail == ["type_repair.run_m012(db)", "type_repair.check_untyped_credits(db)"]


# ---------------------------------------------------------------------------
# The predicate (widened) + condition 3 + condition 4 (change log)
# ---------------------------------------------------------------------------

def test_m012_retypes_exactly_the_unlinked_credits_by_reason(file_db):
    rows = _seed_every_group(file_db)
    before = _types(file_db)

    stats = type_repair.run_m012(file_db)

    after = _types(file_db)
    taken = {"import_credit", "recurring_credit", "other_credit"}
    for name, tx in rows.items():
        expected = "income" if name in taken else before[tx.id]
        assert after[tx.id] == expected, name

    assert stats["M-012/import"]["count"] == 1
    assert stats["M-012/recurring"]["count"] == 1
    assert stats["M-012/other"]["count"] == 1   # condition 3: NULL child rows did not zero it

    ledger = _ledger(file_db)
    changed_ids = sorted(tx_id for tx_id in after if after[tx_id] != before[tx_id])
    assert [r[0] for r in ledger] == changed_ids
    assert {(r[0], r[3]) for r in ledger} == {
        (rows["import_credit"].id, "M-012/import"),
        (rows["recurring_credit"].id, "M-012/recurring"),
        (rows["other_credit"].id, "M-012/other"),
    }
    assert all(r[1] == "expense" and r[2] == "income" for r in ledger)
    assert _marker(file_db)


def test_m012_reverse_sql_restores_every_row(file_db):
    """The one-line reverse documented in type_repair.py works."""
    _seed_every_group(file_db)
    before = _types(file_db)
    type_repair.run_m012(file_db)
    file_db.execute(text(
        "UPDATE transactions SET transaction_type = 'expense' WHERE transaction_type = 'income' "
        "AND id IN (SELECT transaction_id FROM transaction_type_changes WHERE reason LIKE 'M-012/%')"
    ))
    file_db.commit()
    assert _types(file_db) == before


def test_m012_marker_makes_a_second_run_a_noop(file_db):
    rows = _seed_every_group(file_db)
    type_repair.run_m012(file_db)
    late = _tx(file_db, rows["import_credit"].account, 99.0)   # e.g. written by an older image

    assert type_repair.run_m012(file_db) is None
    assert _types(file_db)[late.id] == "expense"
    assert len(_ledger(file_db)) == 3


# ---------------------------------------------------------------------------
# Condition 2 — one transaction; any failure changes nothing and stops start-up
# ---------------------------------------------------------------------------

def test_m012_failure_after_update_rolls_everything_back(file_db, monkeypatch):
    _seed_every_group(file_db)
    before = _types(file_db)

    def boom(_db):
        raise RuntimeError("simulated failure after the UPDATE")

    monkeypatch.setattr(type_repair, "_before_commit", boom)
    with pytest.raises(RuntimeError):
        type_repair.run_m012(file_db)

    assert _types(file_db) == before
    assert not _marker(file_db)
    assert _ledger(file_db) == []

    # The next start applies it cleanly.
    monkeypatch.undo()
    stats = type_repair.run_m012(file_db)
    assert sum(s["count"] for s in stats.values()) == 3
    assert _marker(file_db)


def test_m012_failure_stops_the_app_from_starting(monkeypatch):
    def boom(_db):
        raise type_repair.TypeRepairError("simulated")

    monkeypatch.setattr(main.type_repair, "run_m012", boom)
    with pytest.raises(type_repair.TypeRepairError):
        with TestClient(main.app):
            pass


def test_backup_is_taken_before_the_migrations_run(monkeypatch):
    """Condition 8: the pre-1.4.7 snapshot exists before M-012 touches a row."""
    calls = []
    monkeypatch.setattr(main.backup, "pre_migration_backup",
                        lambda *a, **k: calls.append("backup") or "created")
    monkeypatch.setattr(main, "run_startup_migrations", lambda db: calls.append("migrations"))
    with TestClient(main.app):
        pass
    assert calls == ["backup", "migrations"]


# ---------------------------------------------------------------------------
# Condition 5 — the log line, including the zero case
# ---------------------------------------------------------------------------

def test_m012_logs_count_ids_and_sum(file_db, caplog):
    rows = _seed_every_group(file_db)
    with caplog.at_level(logging.INFO, logger="tally.migrations"):
        type_repair.run_m012(file_db)
    text_ = caplog.text
    ids = sorted(rows[n].id for n in ("import_credit", "recurring_credit", "other_credit"))
    assert f"Re-typed 3 unlinked positive transaction(s)" in text_
    assert f"min id {ids[0]}, max id {ids[-1]}, total 1280.00" in text_
    assert "M-012/import: 1 row(s)" in text_
    assert "M-012/recurring: 1 row(s)" in text_
    assert "M-012/other: 1 row(s)" in text_


def test_m012_logs_the_zero_case(file_db, caplog):
    _user_and_accounts(file_db)
    with caplog.at_level(logging.INFO, logger="tally.migrations"):
        type_repair.run_m012(file_db)
    assert "Re-typed 0 unlinked positive transaction(s)" in caplog.text
    assert "M-012/import: 0 row(s)" in caplog.text


# ---------------------------------------------------------------------------
# Condition 6 — every-boot diagnostic
# ---------------------------------------------------------------------------

def test_diagnostic_warns_on_a_post_marker_credit_and_leaves_it(file_db, caplog):
    rows = _seed_every_group(file_db)
    type_repair.run_m012(file_db)

    with caplog.at_level(logging.WARNING, logger="tally.migrations"):
        assert type_repair.check_untyped_credits(file_db)["total"] == 0
    assert "M-012 check" not in caplog.text

    late = _tx(file_db, rows["import_credit"].account, 99.0)   # a 1.4.6 round trip
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="tally.migrations"):
        result = type_repair.check_untyped_credits(file_db)
    assert result["total"] == 1 and result["import"] == 1 and result["ids"] == [late.id]
    assert f"ids: {late.id}" in caplog.text
    assert _types(file_db)[late.id] == "expense"   # never changed


def test_diagnostic_ignores_a_refund_a_person_set(file_db, caplog):
    rows = _seed_every_group(file_db)
    type_repair.run_m012(file_db)
    refund = _tx(file_db, rows["import_credit"].account, 25.0, ttype="income")
    file_db.add(models.TransactionTypeChange(transaction_id=refund.id, from_type="income",
                                             to_type="expense", reason="user",
                                             changed_at=datetime.utcnow()))
    refund.transaction_type = "expense"
    file_db.commit()

    with caplog.at_level(logging.WARNING, logger="tally.migrations"):
        assert type_repair.check_untyped_credits(file_db)["total"] == 0
    assert "M-012 check" not in caplog.text
