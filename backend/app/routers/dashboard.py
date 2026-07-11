from datetime import date, timedelta
from calendar import monthrange

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    last_day = monthrange(d.year, d.month)[1]
    return start, d.replace(day=last_day)


@router.get("/summary")
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    today = date.today()
    month_start, month_end = _month_bounds(today)
    days_left = (month_end - today).days

    # ── Net worth ────────────────────────────────────────────────────────────
    active_accounts = (
        db.query(models.Account)
        .filter(
            models.Account.is_active == True,
            models.Account.status == "active",
        )
        .all()
    )
    # NOTE (LOW / multi-currency): this sums raw balances across accounts
    # regardless of currency. It is correct only when all active accounts share
    # one currency. A proper fix groups per-currency like the Accounts page does
    # and returns a per-currency net-worth map — deferred to avoid changing the
    # dashboard response contract in a hardening release.
    # TODO(v1.5): return per-currency net worth (see BACKLOG net-worth track).
    net_worth = sum(a.balance for a in active_accounts)
    _currencies = {a.currency for a in active_accounts}
    net_worth_mixed_currency = len(_currencies) > 1

    # ── Monthly income / spend ───────────────────────────────────────────────
    # Canonical exclusion invariant (matches budgets.py + transactions.py):
    #   income/expense aggregates exclude transfer + savings_transfer legs, and
    #   debt_payment is excluded from the expense (spend) side (it reduces a
    #   liability, not a spending category).
    _EXCLUDED_TYPES = ("transfer", "savings_transfer")
    month_txs = (
        db.query(models.Transaction)
        .join(models.Account)
        .filter(
            models.Account.is_active == True,
            models.Transaction.date >= month_start,
            models.Transaction.date <= today,
            models.Transaction.transaction_type.notin_(_EXCLUDED_TYPES),
        )
        .all()
    )
    month_income = sum(t.amount for t in month_txs if t.amount > 0)
    month_spent = abs(
        sum(
            t.amount
            for t in month_txs
            if t.amount < 0 and t.transaction_type != "debt_payment"
        )
    )

    # Net worth change = this month's net (income minus expenses)
    net_worth_change = month_income - month_spent

    # ── Net worth history — last 12 monthly nets ─────────────────────────────
    # Use real calendar-month arithmetic (relativedelta) anchored on the first
    # of the current month. Fixed-width 28-day steps drift and double-count a
    # month when a reference lands on day 29–31 (AUDIT-19).
    this_month_first = date(today.year, today.month, 1)
    history = []
    for i in range(11, -1, -1):
        ref_start = this_month_first - relativedelta(months=i)
        ref_end = ref_start.replace(day=monthrange(ref_start.year, ref_start.month)[1])
        row = (
            db.query(func.coalesce(func.sum(models.Transaction.amount), 0))
            .join(models.Account)
            .filter(
                models.Account.is_active == True,
                models.Transaction.date >= ref_start,
                models.Transaction.date <= ref_end,
                models.Transaction.transaction_type.notin_(_EXCLUDED_TYPES),
            )
            .scalar()
        )
        history.append(float(row))

    # ── Budget total + categories ────────────────────────────────────────────
    active_budgets = (
        db.query(models.Budget)
        .filter(
            models.Budget.user_id == current_user.id,
            models.Budget.is_active == True,
            models.Budget.period == "monthly",
        )
        .all()
    )
    month_budget = sum(b.amount for b in active_budgets)

    budget_categories = []
    for b in active_budgets:
        spent_row = (
            db.query(func.coalesce(func.sum(func.abs(models.Transaction.amount)), 0))
            .join(models.Account)
            .filter(
                models.Account.is_active == True,
                models.Transaction.category_id == b.category_id,
                models.Transaction.date >= month_start,
                models.Transaction.date <= today,
                models.Transaction.amount < 0,
                models.Transaction.transaction_type == "expense",
            )
            .scalar()
        )
        budget_categories.append({
            "name": b.category.name if b.category else "Other",
            "spent": round(float(spent_row), 2),
            "budget": round(b.amount, 2),
            "color": b.category.color if b.category and b.category.color else "var(--chart-1)",
        })

    # ── Attention items ──────────────────────────────────────────────────────
    attention = []

    # Unverified transactions
    unverified_count = (
        db.query(func.count(models.Transaction.id))
        .join(models.Account)
        .filter(
            models.Account.is_active == True,
            models.Transaction.is_verified == False,
            models.Transaction.source == "import",
        )
        .scalar()
    )
    if unverified_count:
        attention.append({
            "tone": "warning",
            "icon": "warn",
            "title": f"{unverified_count} transaction{'s' if unverified_count != 1 else ''} unverified",
            "sub": "Imported — tap to review",
            "cta": "Review",
            "href": "/transactions?filter=unverified",
        })

    # Budget overruns
    for cat in budget_categories:
        if cat["budget"] > 0 and cat["spent"] > cat["budget"]:
            over = cat["spent"] - cat["budget"]
            pct = round((cat["spent"] / cat["budget"]) * 100)
            attention.append({
                "tone": "brand",
                "icon": "target",
                "title": f"{cat['name']} over budget by {round(over)}",
                "sub": f"{pct}% of {round(cat['budget'])} — {days_left} days left",
                "cta": "Adjust",
                "href": "/budgets",
            })

    # Upcoming recurring within 3 days
    upcoming_cutoff = today + timedelta(days=3)
    upcoming = (
        db.query(models.RecurringTransaction)
        .filter(
            models.RecurringTransaction.user_id == current_user.id,
            models.RecurringTransaction.is_active == True,
            models.RecurringTransaction.next_due >= today,
            models.RecurringTransaction.next_due <= upcoming_cutoff,
        )
        .order_by(models.RecurringTransaction.next_due)
        .limit(2)
        .all()
    )
    for rec in upcoming:
        days_until = (rec.next_due - today).days
        when = "today" if days_until == 0 else ("tomorrow" if days_until == 1 else f"in {days_until} days")
        attention.append({
            "tone": "info",
            "icon": "repeat",
            "title": f"{rec.description} charges {when}",
            "sub": f"${abs(rec.amount):.2f}",
            "cta": "See details",
            "href": "/recurring",
        })

    return {
        "netWorth": round(net_worth, 2),
        "netWorthMixedCurrency": net_worth_mixed_currency,
        "netWorthChange": round(net_worth_change, 2),
        "netWorthHistory": [round(v, 2) for v in history],
        "monthIncome": round(month_income, 2),
        "monthSpent": round(month_spent, 2),
        "monthBudget": round(month_budget, 2),
        "daysLeft": days_left,
        "attention": attention[:4],
        "budgetCategories": budget_categories,
    }
