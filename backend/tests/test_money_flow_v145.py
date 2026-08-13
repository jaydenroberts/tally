"""
Flow-whitelist regression tests for v1.4.5 (Phase 0).

The money aggregates used to filter by listing the transaction types to leave
out. That fails open: a type nobody had taught an aggregate about was counted as
ordinary spend or income. ``app/money.py`` replaces that with one shared
whitelist, and these tests pin the two properties that matter:

  * a transaction type the aggregates have never seen is excluded from every
    money figure, structurally rather than site by site, and
  * the dashboard's 12-month series applies the same exclusions as the monthly
    income and spend figures shown above it, so the chart and the headline
    numbers agree.
"""
from datetime import date

import pytest

from app import models, money


def _owner(db):
    return db.query(models.User).filter(models.User.username == "testowner").first()


def _mk_tx(db, account, amount, ttype="expense", ddate=None, category_id=None):
    tx = models.Transaction(
        account_id=account.id,
        date=ddate or date.today().replace(day=1),
        description="t",
        amount=amount,
        category_id=category_id,
        source="manual",
        is_verified=True,
        transaction_type=ttype,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


# ---------------------------------------------------------------------------
# The vocabulary itself
# ---------------------------------------------------------------------------

def test_flow_and_balance_sheet_types_partition_the_vocabulary():
    """Every known type is either flow or balance-sheet — never both, never neither.

    This is the test that fails when someone adds a transaction type and only
    half-declares it.
    """
    assert money.FLOW_TYPES & money.BALANCE_SHEET_TYPES == frozenset()
    assert money.FLOW_TYPES | money.BALANCE_SHEET_TYPES == money.ALL_TYPES
    assert money.TRANSFER_LEG_TYPES <= money.BALANCE_SHEET_TYPES


def test_unknown_type_is_not_flow():
    assert money.is_flow("expense") is True
    assert money.is_flow("income") is True
    assert money.is_flow(None) is True
    assert money.is_flow("transfer") is False
    assert money.is_flow("card_payment") is False


# ---------------------------------------------------------------------------
# The fail-safe property, end to end
# ---------------------------------------------------------------------------

def test_unknown_transaction_type_excluded_from_every_money_aggregate(
    client, db, auth_headers, test_account
):
    """A type no aggregate has been taught about must count nowhere.

    Written against a synthetic type rather than a real one on purpose: it
    proves the whitelist structurally, so it keeps passing for types that do
    not exist yet.
    """
    today = date.today()
    month_start = today.replace(day=1)

    baseline_dash = client.get("/api/dashboard/summary", headers=auth_headers).json()
    baseline_tx = client.get(
        f"/api/transactions/summary?date_from={month_start.isoformat()}",
        headers=auth_headers,
    ).json()

    _mk_tx(db, test_account, -500.0, ttype="not_a_real_type_yet", ddate=month_start)
    _mk_tx(db, test_account, 900.0, ttype="not_a_real_type_yet", ddate=month_start)

    dash = client.get("/api/dashboard/summary", headers=auth_headers).json()
    assert dash["monthSpent"] == baseline_dash["monthSpent"]
    assert dash["monthIncome"] == baseline_dash["monthIncome"]
    assert dash["netWorthHistory"] == baseline_dash["netWorthHistory"]

    tx_summary = client.get(
        f"/api/transactions/summary?date_from={month_start.isoformat()}",
        headers=auth_headers,
    ).json()
    assert tx_summary["income"] == baseline_tx["income"]
    assert tx_summary["expenses"] == baseline_tx["expenses"]


@pytest.mark.parametrize("ttype", sorted(money.BALANCE_SHEET_TYPES))
def test_balance_sheet_types_excluded_from_dashboard_month_figures(
    client, db, auth_headers, test_account, ttype
):
    """Transfers, savings transfers and debt payments move money between the
    household's own accounts — none of them is spend or income."""
    month_start = date.today().replace(day=1)

    baseline = client.get("/api/dashboard/summary", headers=auth_headers).json()
    _mk_tx(db, test_account, -250.0, ttype=ttype, ddate=month_start)

    after = client.get("/api/dashboard/summary", headers=auth_headers).json()
    assert after["monthSpent"] == baseline["monthSpent"]
    assert after["monthIncome"] == baseline["monthIncome"]


# ---------------------------------------------------------------------------
# The dashboard history series must agree with the monthly figures
# ---------------------------------------------------------------------------

def test_history_series_excludes_debt_payments_like_month_spent(
    client, db, auth_headers, test_account
):
    """The 12-month series used to keep debt payments that monthSpent dropped,
    so the chart contradicted the numbers printed above it."""
    month_start = date.today().replace(day=1)

    baseline = client.get("/api/dashboard/summary", headers=auth_headers).json()
    _mk_tx(db, test_account, -300.0, ttype="debt_payment", ddate=month_start)

    after = client.get("/api/dashboard/summary", headers=auth_headers).json()
    assert after["monthSpent"] == baseline["monthSpent"]
    assert after["netWorthHistory"][-1] == baseline["netWorthHistory"][-1]


def test_history_current_month_equals_month_income_minus_month_spent(
    client, db, auth_headers, test_account
):
    """The last point of the series is the current month, so it must equal the
    month's net exactly — the invariant that broke when the two filters drifted."""
    month_start = date.today().replace(day=1)

    _mk_tx(db, test_account, -120.0, ttype="expense", ddate=month_start)
    _mk_tx(db, test_account, 400.0, ttype="income", ddate=month_start)
    _mk_tx(db, test_account, -75.0, ttype="debt_payment", ddate=month_start)
    _mk_tx(db, test_account, -60.0, ttype="transfer", ddate=month_start)

    dash = client.get("/api/dashboard/summary", headers=auth_headers).json()
    expected = round(dash["monthIncome"] - dash["monthSpent"], 2)
    assert dash["netWorthHistory"][-1] == expected
    assert dash["netWorthChange"] == expected


# ---------------------------------------------------------------------------
# Budget spend keeps its existing whitelist behaviour through the shared module
# ---------------------------------------------------------------------------

def test_budget_spend_ignores_non_spend_types(client, db, auth_headers, test_account):
    today = date.today()
    category = models.Category(name="Flow Test Category")
    db.add(category)
    db.commit()
    db.refresh(category)

    budget = models.Budget(
        user_id=_owner(db).id,
        category_id=category.id,
        amount=500.0,
        period="monthly",
        start_date=today.replace(day=1),
        is_active=True,
    )
    db.add(budget)
    db.commit()

    _mk_tx(db, test_account, -100.0, ttype="expense", ddate=today.replace(day=1),
           category_id=category.id)
    _mk_tx(db, test_account, -400.0, ttype="debt_payment", ddate=today.replace(day=1),
           category_id=category.id)
    _mk_tx(db, test_account, -50.0, ttype="future_type", ddate=today.replace(day=1),
           category_id=category.id)

    resp = client.get(
        f"/api/budgets/summary?year={today.year}&month={today.month}",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["budget"]["category_id"] == category.id)
    assert row["total_spend"] == 100.0
