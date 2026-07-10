"""
Money-semantics regression tests for v1.4.2 (MASON-owned routers).

Covers AUDIT-06/07/08/22/23 + LOWs. The conftest in-memory engine does not
register PRAGMA foreign_keys=ON, so the AUDIT-08 tests would pass vacuously; we
register the pragma on that engine here so delete-cascade is genuinely exercised.
"""
from datetime import date

import pytest
from sqlalchemy import event

from app import models
from tests.conftest import engine as test_engine


@pytest.fixture(autouse=True, scope="module")
def _enforce_sqlite_fks():
    def _fk_on(dbapi_connection, connection_record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    event.listen(test_engine, "connect", _fk_on)
    yield
    event.remove(test_engine, "connect", _fk_on)


def _mk_account(db, user, name="Acct", balance=1000.0):
    acct = models.Account(user_id=user.id, name=name, account_type="checking", balance=balance)
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct


def _mk_debt(db, user, balance=100.0):
    debt = models.Debt(
        user_id=user.id, name="Card", original_amount=balance,
        current_balance=balance, is_paid_off=False,
    )
    db.add(debt)
    db.commit()
    db.refresh(debt)
    return debt


def _mk_goal(db, user, current=100.0, target=500.0, account_id=None, completed=False):
    goal = models.SavingsGoal(
        user_id=user.id, name="Holiday", target_amount=target,
        current_amount=current, is_completed=completed, linked_account_id=account_id,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def _mk_tx(db, account, amount, ttype="expense", ddate=None):
    tx = models.Transaction(
        account_id=account.id, date=ddate or date(2026, 5, 1),
        description="t", amount=amount, source="manual", is_verified=False,
        transaction_type=ttype,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def _owner(db):
    return db.query(models.User).filter(models.User.username == "testowner").first()


# --- AUDIT-07 — link/unlink symmetry (effective applied delta) -------------

def test_audit07_debt_overpayment_records_effective_delta(client, db, auth_headers, test_account):
    debt = _mk_debt(db, _owner(db), balance=60.0)
    tx = _mk_tx(db, test_account, -100.0)

    r = client.post(f"/api/transactions/{tx.id}/link-debt",
                    json={"debt_id": debt.id}, headers=auth_headers)
    assert r.status_code == 200, r.text
    db.refresh(debt)
    assert debt.current_balance == 0.0
    assert debt.is_paid_off is True

    payment = db.query(models.DebtPayment).filter(
        models.DebtPayment.transaction_id == tx.id).first()
    assert payment.amount == 60.0

    r = client.delete(f"/api/transactions/{tx.id}/link-debt", headers=auth_headers)
    assert r.status_code == 204
    db.refresh(debt)
    assert debt.current_balance == 60.0
    assert debt.is_paid_off is False


def test_audit07_savings_overwithdrawal_records_effective_delta(client, db, auth_headers, test_account):
    goal = _mk_goal(db, _owner(db), current=40.0, target=500.0)
    tx = _mk_tx(db, test_account, -100.0)

    r = client.post(f"/api/transactions/{tx.id}/link-savings-withdrawal",
                    json={"goal_id": goal.id}, headers=auth_headers)
    assert r.status_code == 200, r.text
    db.refresh(goal)
    assert goal.current_amount == 0.0
    assert goal.is_completed is False

    contrib = db.query(models.SavingsContribution).filter(
        models.SavingsContribution.transaction_id == tx.id).first()
    assert contrib.amount == -40.0

    r = client.delete(f"/api/transactions/{tx.id}/link-savings-withdrawal", headers=auth_headers)
    assert r.status_code == 204
    db.refresh(goal)
    assert goal.current_amount == 40.0


# --- AUDIT-06 — delete reverses linked balance + un-strands transfer sibling

def test_audit06_delete_linked_debt_tx_restores_balance(client, db, auth_headers, test_account):
    debt = _mk_debt(db, _owner(db), balance=100.0)
    tx = _mk_tx(db, test_account, -30.0)
    client.post(f"/api/transactions/{tx.id}/link-debt",
                json={"debt_id": debt.id}, headers=auth_headers)
    db.refresh(debt)
    assert debt.current_balance == 70.0

    r = client.delete(f"/api/transactions/{tx.id}", headers=auth_headers)
    assert r.status_code == 204
    db.refresh(debt)
    assert debt.current_balance == 100.0
    assert db.query(models.DebtPayment).filter(
        models.DebtPayment.transaction_id == tx.id).count() == 0


# --- AUDIT-08 — delete debt/goal with history does not 500 -----------------

def test_audit08_delete_debt_with_history(client, db, auth_headers, test_account):
    debt = _mk_debt(db, _owner(db), balance=100.0)
    tx = _mk_tx(db, test_account, -30.0)
    client.post(f"/api/transactions/{tx.id}/link-debt",
                json={"debt_id": debt.id}, headers=auth_headers)

    r = client.delete(f"/api/debt/{debt.id}", headers=auth_headers)
    assert r.status_code == 204, r.text
    assert db.query(models.DebtPayment).filter(
        models.DebtPayment.debt_id == debt.id).count() == 0
    db.refresh(tx)
    assert tx.debt_id is None
    assert tx.transaction_type == "expense"


# --- AUDIT-22 — aggregate exclusion set ------------------------------------

def test_audit22_savings_transfer_excluded_from_summary(client, db, auth_headers, test_account):
    _mk_tx(db, test_account, 1000.0, ttype="income", ddate=date(2026, 5, 1))
    _mk_tx(db, test_account, -200.0, ttype="expense", ddate=date(2026, 5, 2))
    _mk_tx(db, test_account, 300.0, ttype="savings_transfer", ddate=date(2026, 5, 3))
    _mk_tx(db, test_account, -150.0, ttype="savings_transfer", ddate=date(2026, 5, 4))

    r = client.get("/api/transactions/summary",
                   params={"date_from": "2026-05-01", "date_to": "2026-05-31"},
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["income"] == 1000.0
    assert body["expenses"] == 200.0


def test_audit22_debt_payment_excluded_from_expenses(client, db, auth_headers, test_account):
    _mk_tx(db, test_account, -200.0, ttype="expense", ddate=date(2026, 5, 1))
    _mk_tx(db, test_account, -500.0, ttype="debt_payment", ddate=date(2026, 5, 2))

    r = client.get("/api/transactions/summary",
                   params={"date_from": "2026-05-01", "date_to": "2026-05-31"},
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["expenses"] == 200.0


# --- AUDIT-23 — two-way flags ----------------------------------------------

def test_audit23_debt_upward_correction_reopens(client, db, auth_headers):
    debt = _mk_debt(db, _owner(db), balance=0.0)
    debt.is_paid_off = True
    db.commit()

    r = client.patch(f"/api/debt/{debt.id}",
                     json={"current_balance": 250.0}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_paid_off"] is False


def test_audit23_goal_target_zero_does_not_lock(client, db, auth_headers):
    goal = _mk_goal(db, _owner(db), current=0.0, target=100.0)
    r = client.patch(f"/api/savings/{goal.id}",
                     json={"target_amount": 0.0}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_completed"] is False


def test_audit23_goal_lower_balance_reopens(client, db, auth_headers):
    goal = _mk_goal(db, _owner(db), current=500.0, target=500.0, completed=True)
    r = client.patch(f"/api/savings/{goal.id}",
                     json={"current_amount": 100.0}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_completed"] is False


# --- LOW — transfer-pair sign guard + withdraw audit row -------------------

def test_low_withdraw_goal_writes_audit_row_and_zeroes(client, db, auth_headers):
    owner = _owner(db)
    acct = _mk_account(db, owner, name="Sav", balance=500.0)
    goal = _mk_goal(db, owner, current=300.0, target=500.0, account_id=acct.id)

    r = client.post(f"/api/savings/{goal.id}/withdraw", headers=auth_headers)
    assert r.status_code == 200, r.text
    db.refresh(goal)
    assert goal.current_amount == 0.0
    assert goal.is_completed is False
    contrib = db.query(models.SavingsContribution).filter(
        models.SavingsContribution.goal_id == goal.id,
        models.SavingsContribution.amount < 0,
    ).first()
    assert contrib is not None
    assert contrib.amount == -300.0
    assert contrib.balance_after == 0.0
