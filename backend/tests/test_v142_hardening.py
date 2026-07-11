"""
Regression tests for the v1.4.2 hardening fixes owned by MASON:
  AUDIT-19  dashboard 12-month history real-month arithmetic
  AUDIT-20  recurring month-end anchor + reactivation fast-forward
  AUDIT-21  budget period pro-rating + threshold alignment
  AUDIT-22  dashboard canonical income/expense exclusion set
  BACKLOG-029  category delete succeeds after it had a budget
"""
from datetime import date

import pytest

from app import models
from app.routers.recurring import _advance_date, _fast_forward_next_due
from app.routers.budgets import _period_month_amount


# ---------------------------------------------------------------------------
# AUDIT-20 — recurring month-end anchor drift
# ---------------------------------------------------------------------------

def test_monthly_anchor_no_month_end_drift():
    anchor_day = 31
    d = date(2026, 1, 31)
    d = _advance_date(d, "monthly", anchor_day)
    assert d == date(2026, 2, 28)
    d = _advance_date(d, "monthly", anchor_day)
    assert d == date(2026, 3, 31)
    d = _advance_date(d, "monthly", anchor_day)
    assert d == date(2026, 4, 30)
    d = _advance_date(d, "monthly", anchor_day)
    assert d == date(2026, 5, 31)


def test_monthly_anchor_day_30_february_leap():
    anchor_day = 30
    d = _advance_date(date(2024, 1, 30), "monthly", anchor_day)
    assert d == date(2024, 2, 29)
    d = _advance_date(d, "monthly", anchor_day)
    assert d == date(2024, 3, 30)


def test_simple_frequencies_unchanged():
    assert _advance_date(date(2026, 5, 1), "daily") == date(2026, 5, 2)
    assert _advance_date(date(2026, 5, 1), "weekly") == date(2026, 5, 8)
    assert _advance_date(date(2026, 5, 1), "fortnightly") == date(2026, 5, 15)


def test_fast_forward_advances_stale_next_due():
    rec = models.RecurringTransaction(
        user_id=1, account_id=1, description="Rent",
        amount=-500.0, frequency="monthly",
        start_date=date(2025, 1, 15), next_due=date(2025, 1, 15),
        is_active=True,
    )
    _fast_forward_next_due(rec, today=date(2026, 7, 10))
    assert rec.next_due == date(2026, 7, 15)


def test_fast_forward_noop_when_already_future():
    rec = models.RecurringTransaction(
        user_id=1, account_id=1, description="Sub",
        amount=-9.0, frequency="monthly",
        start_date=date(2026, 8, 1), next_due=date(2026, 8, 1),
        is_active=True,
    )
    _fast_forward_next_due(rec, today=date(2026, 7, 10))
    assert rec.next_due == date(2026, 8, 1)


def test_fast_forward_respects_end_date():
    rec = models.RecurringTransaction(
        user_id=1, account_id=1, description="Expired plan",
        amount=-9.0, frequency="monthly",
        start_date=date(2025, 1, 1), next_due=date(2025, 1, 1),
        end_date=date(2025, 6, 1), is_active=True,
    )
    _fast_forward_next_due(rec, today=date(2026, 7, 10))
    assert rec.next_due <= date(2025, 6, 1)
    # A fully-elapsed schedule must not linger active with a stale past next_due.
    assert rec.is_active is False


# ---------------------------------------------------------------------------
# AUDIT-21 — budget period pro-rating
# ---------------------------------------------------------------------------

def test_period_month_amount_monthly_unchanged():
    assert _period_month_amount(500.0, "monthly", 2026, 7) == 500.0


def test_period_month_amount_weekly_scales_up():
    got = _period_month_amount(100.0, "weekly", 2026, 7)
    assert got == pytest.approx(100.0 * (31 / 7))


def test_period_month_amount_yearly_scales_down():
    assert _period_month_amount(1200.0, "yearly", 2026, 7) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# BACKLOG-029 — category delete succeeds after it had a budget
# ---------------------------------------------------------------------------

def test_delete_category_with_budget_succeeds(client, db, auth_headers):
    user = db.query(models.User).filter(models.User.username == "testowner").first()

    cat = models.Category(user_id=user.id, name="Groceries", color="#00f769", icon="cart")
    db.add(cat)
    db.commit()
    db.refresh(cat)

    budget = models.Budget(
        user_id=user.id, category_id=cat.id, amount=400.0,
        period="monthly", start_date=date(2026, 7, 1),
    )
    db.add(budget)
    db.commit()
    budget_id = budget.id

    resp = client.delete(f"/api/categories/{cat.id}", headers=auth_headers)
    assert resp.status_code == 204, resp.text

    assert db.query(models.Category).filter(models.Category.id == cat.id).first() is None
    assert db.query(models.Budget).filter(models.Budget.id == budget_id).first() is None


# ---------------------------------------------------------------------------
# AUDIT-21 — status thresholds through the API (over at >100, not 90)
# ---------------------------------------------------------------------------

def test_budget_status_thresholds(client, db, auth_headers, test_account):
    user = db.query(models.User).filter(models.User.username == "testowner").first()
    cat = models.Category(user_id=user.id, name="Dining", color="#ea51b2", icon="utensils")
    db.add(cat)
    db.commit()
    db.refresh(cat)

    budget = models.Budget(
        user_id=user.id, category_id=cat.id, amount=100.0,
        period="monthly", start_date=date(2026, 7, 1),
    )
    db.add(budget)

    db.add(models.Transaction(
        account_id=test_account.id, date=date(2026, 7, 5),
        description="meal", amount=-95.0, category_id=cat.id,
        transaction_type="expense", is_verified=True, source="import",
    ))
    db.commit()

    resp = client.get("/api/budgets/summary?year=2026&month=7", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["budget"]["category_id"] == cat.id)
    assert row["status"] == "warning"
    assert row["pct_total"] == pytest.approx(95.0)


def test_budget_over_only_above_100(client, db, auth_headers, test_account):
    user = db.query(models.User).filter(models.User.username == "testowner").first()
    cat = models.Category(user_id=user.id, name="Fuel", color="#a1efe4", icon="car")
    db.add(cat)
    db.commit()
    db.refresh(cat)

    db.add(models.Budget(
        user_id=user.id, category_id=cat.id, amount=100.0,
        period="monthly", start_date=date(2026, 7, 1),
    ))
    db.add(models.Transaction(
        account_id=test_account.id, date=date(2026, 7, 5),
        description="fill up", amount=-120.0, category_id=cat.id,
        transaction_type="expense", is_verified=True, source="import",
    ))
    db.commit()

    resp = client.get("/api/budgets/summary?year=2026&month=7", headers=auth_headers)
    row = next(r for r in resp.json() if r["budget"]["category_id"] == cat.id)
    assert row["status"] == "over"


def test_budget_excludes_debt_payment(client, db, auth_headers, test_account):
    user = db.query(models.User).filter(models.User.username == "testowner").first()
    cat = models.Category(user_id=user.id, name="Debt Payment", color="#ea51b2", icon="credit-card")
    db.add(cat)
    db.commit()
    db.refresh(cat)

    db.add(models.Budget(
        user_id=user.id, category_id=cat.id, amount=100.0,
        period="monthly", start_date=date(2026, 7, 1),
    ))
    db.add(models.Transaction(
        account_id=test_account.id, date=date(2026, 7, 5),
        description="card payment", amount=-80.0, category_id=cat.id,
        transaction_type="debt_payment", is_verified=True, source="import",
    ))
    db.commit()

    resp = client.get("/api/budgets/summary?year=2026&month=7", headers=auth_headers)
    row = next(r for r in resp.json() if r["budget"]["category_id"] == cat.id)
    assert row["total_spend"] == 0.0
    assert row["status"] == "healthy"


# ---------------------------------------------------------------------------
# AUDIT-19 + AUDIT-22 — dashboard summary income/expense exclusion set
# ---------------------------------------------------------------------------

def test_dashboard_excludes_transfers_and_debt_from_spend(client, db, auth_headers, test_account):
    today = date.today()
    d = today.replace(day=1)

    rows = [
        ("salary",        2000.0, "income"),
        ("groceries",     -150.0, "expense"),
        ("card payment",  -100.0, "debt_payment"),
        ("to savings",    -500.0, "savings_transfer"),
        ("acct transfer", -300.0, "transfer"),
    ]
    for desc, amt, ttype in rows:
        db.add(models.Transaction(
            account_id=test_account.id, date=d, description=desc,
            amount=amt, transaction_type=ttype, is_verified=True, source="import",
        ))
    db.commit()

    resp = client.get("/api/dashboard/summary", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["monthIncome"] == pytest.approx(2000.0)
    assert body["monthSpent"] == pytest.approx(150.0)
    assert body["netWorthMixedCurrency"] is False
    assert len(body["netWorthHistory"]) == 12
