"""M-012 — the v1.4.7 transaction-type repair, and its every-boot check.

Why this exists
---------------
Before v1.4.7 the importer stored every row it created with the column default
``transaction_type = 'expense'``, whatever its sign, and a few other code paths
did the same (the recurring generator, unlinking a transfer pair, the raw API).
That was invisible while the dashboard split income from spending by sign. From
v1.4.7 the aggregates split by type, so those rows have to be repaired first or
every credit already in the database would flip from income to spending.

What M-012 does
---------------
Exactly once per database (gated by a ``schema_migrations`` marker), it re-types
every *unlinked positive* row still typed ``'expense'`` to ``'income'``:

  * positive amount, still typed ``expense``;
  * not a transfer leg, not linked to a debt or a savings goal, and not
    referenced by any debt-payment or savings-contribution record.

It does not look at ``source``: no screen in Tally before v1.4.7 let a person
store a positive ``expense`` on purpose, so every such row is one of the defects
above, whichever path produced it.

Each re-typed row is written to ``transaction_type_changes`` with a reason:
``M-012/import``, ``M-012/recurring`` (notes start with "Auto-generated from
recurring:") or ``M-012/other``. The count, the change log, the update and the
marker are one database transaction. If the counts disagree, or anything at all
fails, the whole thing is rolled back, no marker is written, and the app refuses
to start — the next start tries again from the same state. The automatic
``pre-<version>.db`` snapshot is always taken before this runs.

Reversing it
------------
Row by row, from the change log, with Tally stopped::

    UPDATE transactions SET transaction_type = 'expense' WHERE transaction_type = 'income' AND id IN (SELECT transaction_id FROM transaction_type_changes WHERE reason LIKE 'M-012/%');

Leave the ``M-012`` marker in ``schema_migrations`` in place, or the next start
will apply the repair again. Restoring ``pre-1.4.7.db`` is the other way back.

The every-boot check
--------------------
After the marker exists, nothing should create a new unlinked positive
``expense`` except a person using the Income/Expense toggle (logged with reason
``user``). So every start counts the rows that match the repair predicate and
were not set by a person, and logs a WARNING if there are any. It never changes
them. That catches running an older image against this database and back again,
and any future code path that forgets to set the type.
"""

from __future__ import annotations

import logging
import sys

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import models, money

MARKER = "M-012"
RECURRING_NOTES_PREFIX = "Auto-generated from recurring:"
REASON_USER = "user"
REASON_SIGN_FLIP = "sign-flip"
M012_REASONS = ("M-012/import", "M-012/recurring", "M-012/other")

log = logging.getLogger("tally.migrations")

# The rows the repair applies to. Both NOT IN subqueries filter NULLs: a single
# NULL inside a NOT IN list makes the whole test unknown and matches nothing
# (a debt payment recorded without a transaction would silently cancel the
# repair for every row).
PREDICATE = """
    t.transaction_type = 'expense'
    AND t.amount > 0
    AND t.transfer_pair_id IS NULL
    AND t.debt_id IS NULL
    AND t.savings_goal_id IS NULL
    AND t.id NOT IN (SELECT transaction_id FROM debt_payments WHERE transaction_id IS NOT NULL)
    AND t.id NOT IN (SELECT transaction_id FROM savings_contributions WHERE transaction_id IS NOT NULL)
"""

REASON_SQL = f"""
    CASE
        WHEN t.source = 'import' THEN 'M-012/import'
        WHEN t.notes LIKE '{RECURRING_NOTES_PREFIX}%' THEN 'M-012/recurring'
        ELSE 'M-012/other'
    END
"""


def plain_row_blocker(tx: models.Transaction, db: Session) -> Optional[str]:
    """Why ``tx`` is not a plain income/expense row, or None if it is.

    Pairing a transfer or re-typing a row overwrites ``transaction_type``. On a
    row linked to a debt or a savings goal that strands the link (the debt
    balance or goal balance stays moved while the row stops saying why), so both
    actions refuse anything that is not a plain, unlinked income/expense row
    (v1.4.7, BACKLOG-053 warning). The person unlinks it first, then retries.
    """
    if tx.transfer_pair_id is not None or tx.transaction_type in money.TRANSFER_LEG_TYPES:
        return "already part of a transfer"
    if tx.debt_id is not None or tx.transaction_type == "debt_payment" or (
        db.query(models.DebtPayment.id)
        .filter(models.DebtPayment.transaction_id == tx.id)
        .first() is not None
    ):
        return "linked to a debt"
    if tx.savings_goal_id is not None or (
        db.query(models.SavingsContribution.id)
        .filter(models.SavingsContribution.transaction_id == tx.id)
        .first() is not None
    ):
        return "linked to a savings goal"
    if tx.transaction_type not in money.FLOW_TYPES:
        return f"typed '{tx.transaction_type}', not income or expense"
    return None


def retype_on_sign_flip(db: Session, tx: models.Transaction, old_amount: Optional[float]) -> bool:
    """Re-type a plain row whose amount an edit just moved between money in and
    money out. Returns True if the type changed.

    "Money in" and "money out" are the two sides of ``money.type_for_amount``:
    positive is money in; negative and zero are money out. Only a plain, unlinked
    income/expense row is touched (``plain_row_blocker``): a transfer leg, a debt
    payment, a savings movement or any row linked to a debt or goal keeps its type,
    because that type comes from the link. An edit that stays on the same side
    never re-types, so a refund a person set with the toggle (a positive
    'expense') keeps its type when its amount is corrected.

    Each change is logged in ``transaction_type_changes`` with reason
    ``sign-flip``. The start-up check only skips reason ``user``, so a sign-flip
    can never hide a row from it; and a sign-flip always lands on the type that
    matches the sign, so it never creates a row that check would report.
    The caller commits.
    """
    if old_amount is None or tx.amount is None:
        return False
    target = money.type_for_amount(tx.amount)
    if money.type_for_amount(old_amount) == target:
        return False
    if plain_row_blocker(tx, db) is not None or tx.transaction_type == target:
        return False
    db.add(models.TransactionTypeChange(
        transaction_id=tx.id,
        from_type=tx.transaction_type,
        to_type=target,
        reason=REASON_SIGN_FLIP,
    ))
    tx.transaction_type = target
    return True



class TypeRepairError(RuntimeError):
    """M-012 could not be applied exactly. Raised so the app does not start."""


def ensure_log_visible() -> None:
    """Make the migration log reach ``docker logs`` (same reasoning as
    ``backup.ensure_log_visible``: uvicorn leaves the root logger bare, and the
    repair count is the one line an operator needs to see)."""
    if log.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s:     [migrations] %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def _marker_present(db: Session) -> bool:
    return db.execute(
        text("SELECT 1 FROM schema_migrations WHERE id = :id"), {"id": MARKER}
    ).first() is not None


def _before_commit(db: Session) -> None:
    """Seam for the failure-injection test. Does nothing in production."""


def run_m012(db: Session) -> dict | None:
    """Apply the repair once. Returns per-reason stats, or None if already applied.

    Must run LAST in ``run_startup_migrations``: it reads columns and tables that
    earlier migrations add to old databases (``transfer_pair_id``,
    ``schema_migrations``).
    """
    ensure_log_visible()
    # Close whatever an earlier migration left open, so a rollback here can only
    # ever undo M-012's own work.
    db.commit()
    # M-003 normally creates this first; repeated here (same statement) so the
    # function never depends on being called from run_startup_migrations.
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "id TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    ))
    db.commit()

    if _marker_present(db):
        return None

    try:
        # 1. Change log first, while the rows are still typed 'expense'. This is
        #    the first write, so it opens the transaction everything below joins.
        logged = db.execute(text(f"""
            INSERT INTO transaction_type_changes
                (transaction_id, from_type, to_type, reason, changed_at)
            SELECT t.id, 'expense', 'income', {REASON_SQL}, datetime('now')
            FROM transactions t
            WHERE {PREDICATE}
        """)).rowcount

        # 2. Count, inside the same transaction.
        counted = db.execute(text(
            f"SELECT COUNT(*) FROM transactions t WHERE {PREDICATE}"
        )).scalar()

        # 3. The update itself.
        updated = db.execute(text(f"""
            UPDATE transactions SET transaction_type = 'income'
            WHERE id IN (SELECT t.id FROM transactions t WHERE {PREDICATE})
        """)).rowcount

        if not (logged == counted == updated):
            raise TypeRepairError(
                f"[M-012] counts disagree (logged={logged}, counted={counted}, "
                f"updated={updated}); nothing was changed"
            )

        # 4. Per-reason stats from the log rows written above.
        rows = db.execute(text("""
            SELECT c.reason, COUNT(*), MIN(c.transaction_id), MAX(c.transaction_id),
                   COALESCE(SUM(t.amount), 0)
            FROM transaction_type_changes c
            JOIN transactions t ON t.id = c.transaction_id
            WHERE c.reason LIKE 'M-012/%'
            GROUP BY c.reason
        """)).fetchall()
        stats = {reason: {"count": 0, "min_id": None, "max_id": None, "sum": 0.0}
                 for reason in M012_REASONS}
        for reason, count, min_id, max_id, total in rows:
            stats[reason] = {"count": count, "min_id": min_id, "max_id": max_id,
                             "sum": round(float(total), 2)}
        if sum(s["count"] for s in stats.values()) != updated:
            raise TypeRepairError("[M-012] change log does not match the update; nothing was changed")

        # 5. Marker, same transaction.
        db.execute(text("INSERT INTO schema_migrations (id) VALUES (:id)"), {"id": MARKER})
        _before_commit(db)
        db.commit()
    except Exception:
        db.rollback()
        log.error(
            "[M-012] The transaction-type repair failed and was rolled back; nothing "
            "was changed. Tally will not start. Your pre-upgrade snapshot is in the "
            "backups folder beside the database."
        )
        raise

    all_ids = [s for s in stats.values() if s["count"]]
    log.info(
        "[M-012] Re-typed %d unlinked positive transaction(s) from 'expense' to "
        "'income' (min id %s, max id %s, total %.2f). Each one is listed in the "
        "transaction_type_changes table.",
        updated,
        min((s["min_id"] for s in all_ids), default=None),
        max((s["max_id"] for s in all_ids), default=None),
        sum(s["sum"] for s in stats.values()),
    )
    for reason in M012_REASONS:
        s = stats[reason]
        log.info(
            "[M-012]   %s: %d row(s), min id %s, max id %s, total %.2f",
            reason, s["count"], s["min_id"], s["max_id"], s["sum"],
        )
    return stats


def check_untyped_credits(db: Session) -> dict:
    """Every-boot diagnostic. Counts unlinked positive 'expense' rows that a
    person did not set (reason 'user'), grouped like M-012. Logs a WARNING if
    there are any. Never changes a row."""
    ensure_log_visible()
    rows = db.execute(text(f"""
        SELECT {REASON_SQL} AS reason, COUNT(*), GROUP_CONCAT(t.id)
        FROM transactions t
        WHERE {PREDICATE}
          AND t.id NOT IN (
              SELECT transaction_id FROM transaction_type_changes
              WHERE reason = :user AND transaction_id IS NOT NULL
          )
        GROUP BY reason
    """), {"user": REASON_USER}).fetchall()
    counts = {reason.replace("M-012/", ""): 0 for reason in M012_REASONS}
    ids: list[int] = []
    for reason, count, id_list in rows:
        counts[reason.replace("M-012/", "")] = count
        ids.extend(int(i) for i in str(id_list).split(",") if i)
    total = sum(counts.values())
    if total:
        ids.sort()
        shown = ", ".join(str(i) for i in ids[:20]) + (" …" if len(ids) > 20 else "")
        log.warning(
            "[M-012 check] %d positive transaction(s) are typed as spending, so they "
            "reduce spending instead of counting as income: import=%d, recurring=%d, "
            "other=%d (ids: %s). This happens if an older Tally ran against this "
            "database after v1.4.7. Nothing was changed. Open each one on the "
            "Transactions page and choose Income, or choose Expense if it really is "
            "a refund; either choice stops this warning for that row.",
            total, counts["import"], counts["recurring"], counts["other"], shown,
        )
    return {"total": total, **counts, "ids": ids}
