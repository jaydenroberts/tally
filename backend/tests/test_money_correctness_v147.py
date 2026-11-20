"""
v1.4.7 money-correctness tests.

  * Condition 7: every code path that creates a plain row, or returns a row to a
    plain state, sets the type by sign — one parametrised test over all of them.
  * Item 3 / condition 8: the dashboard and the Transactions summary split income
    from spending by type, as signed sums; the chart agrees with the headline;
    a refund on a budgeted category reduces that category's spend everywhere.
  * Item 4: pairing two rows as a transfer, the 409 on linked rows, unlinking.
  * The Income/Expense toggle (POST /api/transactions/{id}/retype).
  * Item 5: a non-finite amount cannot be stored, by API or by import.
  * Item 6: the coach is told the account balances are hand-entered.
"""
import io
import math
from datetime import date, timedelta

import pytest

from app import models, type_repair
from app.routers import chat as chat_router
from app.routers import recurring as recurring_router
from app.routers.imports import _normalise_amount


TODAY = date.today()
MONTH_START = TODAY.replace(day=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _owner(db):
    return db.query(models.User).filter(models.User.username == "testowner").first()


def _account(db, name="Card"):
    acct = models.Account(user_id=_owner(db).id, name=name, account_type="credit", balance=0)
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct


def _tx(db, account, amount, ttype="expense", source="manual", ddate=None, category_id=None, **kw):
    tx = models.Transaction(
        account_id=account.id, date=ddate or MONTH_START, description="t", amount=amount,
        source=source, is_verified=source == "import", transaction_type=ttype,
        category_id=category_id, **kw,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def _import_rows(client, headers, account, rows):
    body = "Date,Description,Amount\n" + "".join(
        f"{d.isoformat()},{desc},{amt}\n" for d, desc, amt in rows)
    r = client.post(f"/api/imports?account_id={account.id}", headers=headers,
                    files={"file": ("s.csv", io.BytesIO(body.encode()), "text/csv")})
    assert r.status_code == 201, r.text
    draft_id = r.json()["id"]
    r = client.post(f"/api/imports/{draft_id}/commit", headers=headers)
    assert r.status_code == 200, r.text
    return draft_id


def _dashboard(client, headers):
    r = client.get("/api/dashboard/summary", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _summary(client, headers):
    r = client.get("/api/transactions/summary", headers=headers,
                   params={"date_from": MONTH_START.isoformat(), "date_to": TODAY.isoformat()})
    assert r.status_code == 200, r.text
    return r.json()


def _budget_spend(client, headers, category_id):
    r = client.get("/api/budgets/summary", headers=headers,
                   params={"year": TODAY.year, "month": TODAY.month})
    assert r.status_code == 200, r.text
    return next(b["total_spend"] for b in r.json() if b["budget"]["category_id"] == category_id)


def _category_and_budget(db, amount=200.0):
    cat = models.Category(name="Groceries-v147", user_id=_owner(db).id, is_system=False)
    db.add(cat)
    db.commit()
    db.add(models.Budget(user_id=_owner(db).id, category_id=cat.id, amount=amount,
                         period="monthly", start_date=MONTH_START, is_active=True))
    db.commit()
    return cat


# ---------------------------------------------------------------------------
# Condition 7 — every producer sets the type by sign
# ---------------------------------------------------------------------------

def _p_importer(client, db, headers, acct, amount):
    _import_rows(client, headers, acct, [(MONTH_START, "row", amount)])
    return db.query(models.Transaction).filter(models.Transaction.source == "import").one()


def _p_recurring(client, db, headers, acct, amount):
    db.add(models.RecurringTransaction(
        user_id=_owner(db).id, account_id=acct.id, description="Pay", amount=amount,
        frequency="monthly", start_date=TODAY, next_due=TODAY, is_active=True))
    db.commit()
    assert recurring_router.run_due_recurring(db) == 1
    return db.query(models.Transaction).filter(
        models.Transaction.notes.like("Auto-generated from recurring:%")).one()


def _make_transfer(client, db, headers, acct, amount):
    other = _account(db, "Other")
    r = client.post("/api/transactions/transfer", headers=headers, json={
        "source_account_id": acct.id, "destination_account_id": other.id,
        "amount": abs(amount), "date": MONTH_START.isoformat(), "description": "move"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["debit_transaction"]["id"], body["credit_transaction"]["id"]


def _p_transfer_unlink(client, db, headers, acct, amount):
    debit_id, credit_id = _make_transfer(client, db, headers, acct, amount)
    r = client.delete(f"/api/transactions/{debit_id}/link-transfer-pair", headers=headers)
    assert r.status_code == 204, r.text
    return db.get(models.Transaction, credit_id if amount > 0 else debit_id)


def _p_transfer_delete(client, db, headers, acct, amount):
    debit_id, credit_id = _make_transfer(client, db, headers, acct, amount)
    keep, drop = (credit_id, debit_id) if amount > 0 else (debit_id, credit_id)
    r = client.delete(f"/api/transactions/{drop}", headers=headers)
    assert r.status_code == 204, r.text
    return db.get(models.Transaction, keep)


def _p_debt_delete(client, db, headers, acct, amount):
    debt = models.Debt(user_id=_owner(db).id, name="Loan", original_amount=500,
                       current_balance=500, is_paid_off=False)
    db.add(debt)
    db.commit()
    tx = _tx(db, acct, amount, ttype="debt_payment", debt_id=debt.id)
    db.add(models.DebtPayment(debt_id=debt.id, amount=abs(amount), balance_after=400,
                              transaction_id=tx.id))
    db.commit()
    assert client.delete(f"/api/debt/{debt.id}", headers=headers).status_code == 204
    return tx


def _p_debt_unlink(client, db, headers, acct, amount):
    debt = models.Debt(user_id=_owner(db).id, name="Loan", original_amount=500,
                       current_balance=500, is_paid_off=False)
    db.add(debt)
    db.commit()
    tx = _tx(db, acct, amount)
    r = client.post(f"/api/transactions/{tx.id}/link-debt", headers=headers, json={"debt_id": debt.id})
    assert r.status_code == 200, r.text
    assert client.delete(f"/api/transactions/{tx.id}/link-debt", headers=headers).status_code == 204
    return tx


def _p_goal_delete(client, db, headers, acct, amount):
    goal = models.SavingsGoal(user_id=_owner(db).id, name="Goal", target_amount=1000,
                              current_amount=100, is_completed=False)
    db.add(goal)
    db.commit()
    tx = _tx(db, acct, amount, ttype="savings_transfer")
    db.add(models.SavingsContribution(goal_id=goal.id, amount=amount, balance_after=100,
                                      transaction_id=tx.id))
    db.commit()
    assert client.delete(f"/api/savings/{goal.id}", headers=headers).status_code == 204
    return tx


def _p_withdrawal_unlink(client, db, headers, acct, amount):
    goal = models.SavingsGoal(user_id=_owner(db).id, name="Goal", target_amount=1000,
                              current_amount=500, is_completed=False)
    db.add(goal)
    db.commit()
    tx = _tx(db, acct, amount)
    r = client.post(f"/api/transactions/{tx.id}/link-savings-withdrawal", headers=headers,
                    json={"goal_id": goal.id})
    assert r.status_code == 200, r.text
    r = client.delete(f"/api/transactions/{tx.id}/link-savings-withdrawal", headers=headers)
    assert r.status_code == 204, r.text
    return tx


def _p_coach_add(client, db, headers, acct, amount):
    user = _owner(db)
    result = chat_router._execute_tool(
        "add_transaction",
        {"account_id": acct.id, "date": MONTH_START.isoformat(), "description": "coach", "amount": amount},
        db, user, user.persona, MONTH_START)
    assert result.get("success"), result
    return db.get(models.Transaction, result["transaction_id"])


def _p_api_create_without_type(client, db, headers, acct, amount):
    r = client.post("/api/transactions", headers=headers, json={
        "account_id": acct.id, "date": MONTH_START.isoformat(), "amount": amount})
    assert r.status_code == 201, r.text
    return db.get(models.Transaction, r.json()["id"])


def _e_patch(client, db, headers, acct, amount):
    """Edit path: the general PATCH moves a plain row to the other sign."""
    tx = _tx(db, acct, -amount, ttype="income" if -amount > 0 else "expense")
    r = client.patch(f"/api/transactions/{tx.id}", headers=headers, json={"amount": amount})
    assert r.status_code == 200, r.text
    return tx


def _e_coach_update(client, db, headers, acct, amount):
    """Edit path: the coach's update_transaction tool."""
    tx = _tx(db, acct, -amount, ttype="income" if -amount > 0 else "expense")
    user = _owner(db)
    result = chat_router._execute_tool(
        "update_transaction", {"transaction_id": tx.id, "amount": amount},
        db, user, user.persona, MONTH_START)
    assert result.get("success"), result
    return tx


PRODUCERS = [
    ("edit_patch", _e_patch, (1, -1)),
    ("edit_coach_update", _e_coach_update, (1, -1)),
    ("importer", _p_importer, (1, -1)),
    ("recurring", _p_recurring, (1, -1)),
    ("transfer_unlink", _p_transfer_unlink, (1, -1)),
    ("transfer_delete", _p_transfer_delete, (1, -1)),
    ("debt_delete", _p_debt_delete, (1, -1)),
    ("debt_unlink", _p_debt_unlink, (-1,)),            # link-debt accepts debits only
    ("goal_delete", _p_goal_delete, (1, -1)),
    ("withdrawal_unlink", _p_withdrawal_unlink, (-1,)),  # withdrawals are debits only
    ("coach_add", _p_coach_add, (1, -1)),
    ("api_create_without_type", _p_api_create_without_type, (1, -1)),
]


@pytest.mark.parametrize(
    "producer,sign",
    [(fn, s) for _, fn, signs in PRODUCERS for s in signs],
    ids=[f"{name}-{'credit' if s > 0 else 'debit'}" for name, _, signs in PRODUCERS for s in signs],
)
def test_every_producer_sets_type_by_sign(client, db, auth_headers, test_account, producer, sign):
    tx = producer(client, db, auth_headers, test_account, 37.5 * sign)
    db.refresh(tx)
    assert tx.transaction_type == ("income" if sign > 0 else "expense")


def test_api_create_honours_an_explicit_refund(client, db, auth_headers, test_account):
    r = client.post("/api/transactions", headers=auth_headers, json={
        "account_id": test_account.id, "date": MONTH_START.isoformat(),
        "amount": 12.0, "transaction_type": "expense"})
    assert r.status_code == 201
    assert r.json()["transaction_type"] == "expense"


# ---------------------------------------------------------------------------
# Sign-flip edits
# ---------------------------------------------------------------------------

def _changes(db, tx_id, reason=None):
    q = db.query(models.TransactionTypeChange).filter_by(transaction_id=tx_id)
    if reason:
        q = q.filter_by(reason=reason)
    return [(c.from_type, c.to_type, c.reason) for c in q.order_by(models.TransactionTypeChange.id)]


@pytest.mark.parametrize("start,end,expected", [(-40.0, 40.0, "income"), (40.0, -40.0, "expense")])
def test_sign_flip_is_logged_as_sign_flip(client, db, auth_headers, test_account, start, end, expected):
    tx = _tx(db, test_account, start, ttype="income" if start > 0 else "expense")
    r = client.patch(f"/api/transactions/{tx.id}", headers=auth_headers, json={"amount": end})
    assert r.status_code == 200 and r.json()["transaction_type"] == expected
    assert _changes(db, tx.id) == [("income" if start > 0 else "expense", expected, "sign-flip")]


@pytest.mark.parametrize("start,end,ttype", [(-40.0, -55.0, "expense"), (40.0, 55.0, "income")])
def test_no_sign_change_means_no_reset(client, db, auth_headers, test_account, start, end, ttype):
    tx = _tx(db, test_account, start, ttype=ttype)
    r = client.patch(f"/api/transactions/{tx.id}", headers=auth_headers,
                     json={"amount": end, "description": "edited"})
    assert r.status_code == 200 and r.json()["transaction_type"] == ttype
    assert _changes(db, tx.id) == []


@pytest.mark.parametrize("kind", ["transfer", "debt_payment", "savings_transfer", "goal_linked", "debt_child"])
def test_sign_flip_leaves_linked_and_balance_sheet_rows_alone(client, db, auth_headers, test_account, kind):
    debt = models.Debt(user_id=_owner(db).id, name="L", original_amount=1, current_balance=1, is_paid_off=False)
    goal = models.SavingsGoal(user_id=_owner(db).id, name="G", target_amount=1, current_amount=0, is_completed=False)
    db.add_all([debt, goal])
    db.commit()
    kw, ttype = {}, "expense"
    if kind in ("transfer", "debt_payment", "savings_transfer"):
        ttype = kind
    elif kind == "goal_linked":
        kw = {"savings_goal_id": goal.id}
    tx = _tx(db, test_account, -30.0, ttype=ttype, **kw)
    if kind == "debt_child":
        db.add(models.DebtPayment(debt_id=debt.id, amount=30, balance_after=0, transaction_id=tx.id))
        db.commit()
    r = client.patch(f"/api/transactions/{tx.id}", headers=auth_headers, json={"amount": 30.0})
    assert r.status_code == 200, r.text
    db.refresh(tx)
    assert tx.transaction_type == ttype
    assert _changes(db, tx.id) == []


def test_toggled_refund_survives_an_amount_edit(client, db, auth_headers, test_account):
    refund = _tx(db, test_account, 25.0, ttype="income")
    assert client.post(f"/api/transactions/{refund.id}/retype", headers=auth_headers,
                       json={"transaction_type": "expense"}).status_code == 200
    r = client.patch(f"/api/transactions/{refund.id}", headers=auth_headers, json={"amount": 27.5})
    assert r.status_code == 200 and r.json()["transaction_type"] == "expense"
    user = _owner(db)
    chat_router._execute_tool("update_transaction", {"transaction_id": refund.id, "amount": 26.0},
                              db, user, user.persona, MONTH_START)
    db.refresh(refund)
    assert refund.transaction_type == "expense"
    assert _changes(db, refund.id) == [("income", "expense", "user")]
    # ...and the start-up check still treats it as a deliberate refund.
    assert type_repair.check_untyped_credits(db)["total"] == 0


def test_start_up_check_stays_clean_after_sign_flips(client, db, auth_headers, test_account):
    a = _tx(db, test_account, -10.0)
    b = _tx(db, test_account, 10.0, ttype="income")
    client.patch(f"/api/transactions/{a.id}", headers=auth_headers, json={"amount": 10.0})
    client.patch(f"/api/transactions/{b.id}", headers=auth_headers, json={"amount": -10.0})
    result = type_repair.check_untyped_credits(db)
    assert result["total"] == 0, result


def test_reconciling_a_zero_estimate_with_a_credit_re_types_it_and_rollback_reverses(
        client, db, auth_headers, test_account):
    """The matcher treats a $0 estimate as compatible with either sign, so a
    reconcile is an edit that can cross from money out to money in."""
    est = _tx(db, test_account, 0.0, ddate=MONTH_START)
    est.description = "Example Market"
    db.commit()
    csv = f"Date,Description,Amount\n{MONTH_START},Example Market,0.80\n".encode()
    r = client.post(f"/api/imports?account_id={test_account.id}", headers=auth_headers,
                    files={"file": ("s.csv", io.BytesIO(csv), "text/csv")})
    draft_id = r.json()["id"]
    preview = client.get(f"/api/imports/{draft_id}/preview", headers=auth_headers).json()
    confirmed = list(preview.get("confident_matches", [])) + [
        {"row_id": s["row_id"], "candidate_transaction_id": s["candidate_transaction_id"]}
        for s in preview.get("review_suggestions", [])]
    assert [c["candidate_transaction_id"] for c in confirmed] == [est.id], preview
    r = client.post(f"/api/imports/{draft_id}/commit", headers=auth_headers,
                    json={"confirmed_matches": confirmed})
    assert r.status_code == 200 and r.json()["matched_count"] == 1, r.text
    db.refresh(est)
    assert (est.amount, est.transaction_type) == (0.80, "income")

    assert client.post(f"/api/imports/{draft_id}/rollback", headers=auth_headers).status_code == 200
    db.refresh(est)
    assert (est.amount, est.transaction_type) == (0.0, "expense")
    assert _changes(db, est.id) == [("expense", "income", "sign-flip"), ("income", "expense", "sign-flip")]


# ---------------------------------------------------------------------------
# Item 3 — aggregates by type, signed sums (dashboard AND summary)
# ---------------------------------------------------------------------------

def test_import_credit_counts_as_income_on_both_pages(client, db, auth_headers, test_account):
    _import_rows(client, auth_headers, test_account,
                 [(MONTH_START, "Salary", "2000.00"), (MONTH_START, "Shop", "-80.00")])
    d, s = _dashboard(client, auth_headers), _summary(client, auth_headers)
    assert (d["monthIncome"], d["monthSpent"]) == (2000.0, 80.0)
    assert (s["income"], s["expenses"]) == (2000.0, 80.0)


def test_refund_reduces_spend_and_is_not_income(client, db, auth_headers, test_account):
    _tx(db, test_account, -100.0)
    _tx(db, test_account, 30.0, ttype="expense")      # a refund
    d, s = _dashboard(client, auth_headers), _summary(client, auth_headers)
    assert (d["monthIncome"], d["monthSpent"]) == (0.0, 70.0)
    assert (s["income"], s["expenses"]) == (0.0, 70.0)


def test_negative_income_reduces_income(client, db, auth_headers, test_account):
    _tx(db, test_account, 1000.0, ttype="income")
    _tx(db, test_account, -200.0, ttype="income")     # a reversed salary
    d, s = _dashboard(client, auth_headers), _summary(client, auth_headers)
    assert d["monthIncome"] == 800.0 and s["income"] == 800.0
    assert d["monthSpent"] == 0.0 and s["expenses"] == 0.0


def test_chart_point_equals_income_minus_spend(client, db, auth_headers, test_account):
    _tx(db, test_account, 1000.0, ttype="income")
    _tx(db, test_account, -300.0)
    _tx(db, test_account, 50.0)                       # refund
    _tx(db, test_account, -40.0, ttype="income")
    d = _dashboard(client, auth_headers)
    assert d["netWorthHistory"][-1] == pytest.approx(d["monthIncome"] - d["monthSpent"])
    assert d["netWorthChange"] == pytest.approx(d["monthIncome"] - d["monthSpent"])


def test_no_negative_zero_reaches_the_pages(client, db, auth_headers, test_account):
    d, s = _dashboard(client, auth_headers), _summary(client, auth_headers)
    for v in (d["monthIncome"], d["monthSpent"], s["income"], s["expenses"]):
        assert math.copysign(1.0, v) == 1.0


def test_refund_reduces_its_budget_category_everywhere(client, db, auth_headers, test_account):
    cat = _category_and_budget(db)
    _tx(db, test_account, -120.0, category_id=cat.id)
    _tx(db, test_account, 20.0, category_id=cat.id)   # refund, typed expense
    tile = next(c for c in _dashboard(client, auth_headers)["budgetCategories"]
                if c["name"] == cat.name)
    assert tile["spent"] == 100.0
    assert _budget_spend(client, auth_headers, cat.id) == 100.0


def test_retyping_a_credit_to_income_raises_budget_spend(client, db, auth_headers, test_account):
    """What M-012 does to a positive 'expense' row on a budgeted category: the
    dashboard headline is unchanged, the category's Budgets spend rises."""
    cat = _category_and_budget(db)
    _tx(db, test_account, -120.0, category_id=cat.id)
    credit = _tx(db, test_account, 20.0, category_id=cat.id)
    before = (_dashboard(client, auth_headers), _budget_spend(client, auth_headers, cat.id))
    credit.transaction_type = "income"
    db.commit()
    after = (_dashboard(client, auth_headers), _budget_spend(client, auth_headers, cat.id))
    assert before[1] == 100.0 and after[1] == 120.0
    # The headline changes here because the row was a refund under the new rule
    # before re-typing; the M-012 rehearsal checks headline stability against
    # the 1.4.6 sign rule, which is the comparison that matters for upgraders.
    assert after[0]["monthIncome"] == 20.0


# ---------------------------------------------------------------------------
# Item 4 — transfer pairing, hardened
# ---------------------------------------------------------------------------

def test_pairing_two_imported_rows_removes_both_from_every_figure(client, db, auth_headers, test_account):
    card = _account(db)
    out = _tx(db, test_account, -400.0, source="import")
    into = _tx(db, card, 400.0, ttype="income", source="import")
    r = client.post("/api/transactions/link-transfer-pair", headers=auth_headers,
                    json={"transaction_a_id": out.id, "transaction_b_id": into.id})
    assert r.status_code == 200, r.text
    db.refresh(out), db.refresh(into)
    assert out.transaction_type == into.transaction_type == "transfer"
    d, s = _dashboard(client, auth_headers), _summary(client, auth_headers)
    assert (d["monthIncome"], d["monthSpent"], s["income"], s["expenses"]) == (0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize("link", ["debt_id", "goal_id", "debt_payment_type", "savings_transfer_type", "debt_child"])
def test_pairing_refuses_a_linked_row_and_changes_nothing(client, db, auth_headers, test_account, link):
    card = _account(db)
    out = _tx(db, test_account, -50.0)
    into_kw, into_type = {}, "income"
    debt = models.Debt(user_id=_owner(db).id, name="L", original_amount=1, current_balance=1, is_paid_off=False)
    goal = models.SavingsGoal(user_id=_owner(db).id, name="G", target_amount=1, current_amount=0, is_completed=False)
    db.add_all([debt, goal])
    db.commit()
    if link == "debt_id":
        into_kw = {"debt_id": debt.id}
    elif link == "goal_id":
        into_kw = {"savings_goal_id": goal.id}
    elif link == "debt_payment_type":
        into_type = "debt_payment"
    elif link == "savings_transfer_type":
        into_type = "savings_transfer"
    into = _tx(db, card, 50.0, ttype=into_type, **into_kw)
    if link == "debt_child":
        db.add(models.DebtPayment(debt_id=debt.id, amount=50, balance_after=0, transaction_id=into.id))
        db.commit()

    r = client.post("/api/transactions/link-transfer-pair", headers=auth_headers,
                    json={"transaction_a_id": out.id, "transaction_b_id": into.id})
    assert r.status_code == 409, r.text
    assert "Unlink it first" in r.json()["detail"]
    db.refresh(out), db.refresh(into)
    assert (out.transaction_type, into.transaction_type) == ("expense", into_type)
    assert out.transfer_pair_id is None and into.transfer_pair_id is None


def test_unpairing_restores_each_leg_by_sign(client, db, auth_headers, test_account):
    card = _account(db)
    out = _tx(db, test_account, -60.0, source="import")
    into = _tx(db, card, 60.0, ttype="income", source="import")
    client.post("/api/transactions/link-transfer-pair", headers=auth_headers,
                json={"transaction_a_id": out.id, "transaction_b_id": into.id})
    assert client.delete(f"/api/transactions/{into.id}/link-transfer-pair",
                         headers=auth_headers).status_code == 204
    db.refresh(out), db.refresh(into)
    assert (out.transaction_type, into.transaction_type) == ("expense", "income")


# ---------------------------------------------------------------------------
# The Income/Expense toggle
# ---------------------------------------------------------------------------

def _retype(client, headers, tx_id, ttype):
    return client.post(f"/api/transactions/{tx_id}/retype", headers=headers,
                       json={"transaction_type": ttype})


def test_toggle_records_a_refund_and_logs_it_as_user(client, db, auth_headers, test_account):
    _tx(db, test_account, -100.0)
    credit = _tx(db, test_account, 25.0, ttype="income", source="import")
    r = _retype(client, auth_headers, credit.id, "expense")
    assert r.status_code == 200, r.text
    assert r.json()["transaction_type"] == "expense"
    log = db.query(models.TransactionTypeChange).filter_by(transaction_id=credit.id).all()
    assert [(l.from_type, l.to_type, l.reason) for l in log] == [("income", "expense", "user")]
    d = _dashboard(client, auth_headers)
    assert (d["monthIncome"], d["monthSpent"]) == (0.0, 75.0)


def test_toggle_to_the_same_type_writes_nothing(client, db, auth_headers, test_account):
    tx = _tx(db, test_account, 10.0, ttype="income")
    assert _retype(client, auth_headers, tx.id, "income").status_code == 200
    assert db.query(models.TransactionTypeChange).filter_by(transaction_id=tx.id).count() == 0


def test_toggle_refuses_linked_rows(client, db, auth_headers, test_account):
    card = _account(db)
    out = _tx(db, test_account, -60.0)
    into = _tx(db, card, 60.0, ttype="income")
    client.post("/api/transactions/link-transfer-pair", headers=auth_headers,
                json={"transaction_a_id": out.id, "transaction_b_id": into.id})
    r = _retype(client, auth_headers, into.id, "expense")
    assert r.status_code == 409
    db.refresh(into)
    assert into.transaction_type == "transfer"
    debt_row = _tx(db, test_account, -5.0, ttype="debt_payment")
    assert _retype(client, auth_headers, debt_row.id, "income").status_code == 409


def test_toggle_only_accepts_income_or_expense(client, db, auth_headers, test_account):
    tx = _tx(db, test_account, 10.0, ttype="income")
    assert _retype(client, auth_headers, tx.id, "transfer").status_code == 422
    assert _retype(client, auth_headers, 999999, "income").status_code == 404


def test_general_patch_still_cannot_change_the_type(client, db, auth_headers, test_account):
    tx = _tx(db, test_account, 10.0, ttype="income")
    r = client.patch(f"/api/transactions/{tx.id}", headers=auth_headers,
                     json={"transaction_type": "expense"})
    assert r.status_code == 200
    db.refresh(tx)
    assert tx.transaction_type == "income"


# ---------------------------------------------------------------------------
# Item 5 — non-finite amounts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["Infinity", "inf", "-Infinity", "NaN", "1e999"])
def test_api_rejects_non_finite_amount_strings(client, auth_headers, test_account, bad):
    r = client.post("/api/transactions", headers=auth_headers, json={
        "account_id": test_account.id, "date": MONTH_START.isoformat(), "amount": bad})
    assert r.status_code == 422, r.text


def test_api_rejects_an_integer_too_large_for_a_float(client, auth_headers, test_account):
    r = client.post("/api/transactions", headers=auth_headers, json={
        "account_id": test_account.id, "date": MONTH_START.isoformat(), "amount": 10 ** 400})
    assert r.status_code == 422, r.text


def test_api_still_accepts_numeric_strings(client, auth_headers, test_account):
    r = client.post("/api/transactions", headers=auth_headers, json={
        "account_id": test_account.id, "date": MONTH_START.isoformat(), "amount": "-12.50"})
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("bad", ["Infinity", "inf", "NaN", "-Infinity Dr", "(Infinity)"])
def test_import_parser_treats_non_finite_as_unparseable(bad):
    assert _normalise_amount(bad) is None


def test_import_of_an_infinity_cell_stores_no_non_finite_row(client, db, auth_headers, test_account):
    """The cell is treated like any unparseable amount: the commit is refused with
    the existing "no parseable amount" message until the row is excluded."""
    body = f"Date,Description,Amount\n{MONTH_START},bad,Infinity\n{MONTH_START},ok,-5.00\n"
    r = client.post(f"/api/imports?account_id={test_account.id}", headers=auth_headers,
                    files={"file": ("s.csv", io.BytesIO(body.encode()), "text/csv")})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/imports/{r.json()['id']}/commit", headers=auth_headers)
    assert r.status_code == 409
    assert r.json()["detail"]["kind"] == "invalid_rows"
    amounts = [t.amount for t in db.query(models.Transaction).all()]
    assert all(math.isfinite(a) for a in amounts)


# ---------------------------------------------------------------------------
# Item 6 — the coach is told balances are hand-entered
# ---------------------------------------------------------------------------

def test_coach_snapshot_labels_balances_as_entered(db, auth_headers, test_account):
    user = _owner(db)
    for level in ("full", "summary"):
        user.persona.data_access_level = level
        db.commit()
        prompt = chat_router._build_system_prompt(user.persona, MONTH_START, db, user)
        assert "not derived from transactions" in prompt, level


def test_coach_account_tool_labels_balances_as_entered(db, auth_headers, test_account):
    user = _owner(db)
    result = chat_router._execute_tool("get_accounts", {}, db, user, user.persona, MONTH_START)
    assert result and all("not derived from transactions" in a["balance_note"] for a in result)
