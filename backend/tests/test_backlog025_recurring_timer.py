"""
BACKLOG-025 — in-process daily recurring-transaction timer.

Covers the schedule arithmetic (frozen datetime, no real sleep), the
"run once" generation wrapper (own session, per-day idempotency), and clean
cancel of the background task.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from app import main, models
from app.routers.recurring import run_due_recurring


# ---------------------------------------------------------------------------
# Schedule arithmetic — pure, injectable now (no sleeping)
# ---------------------------------------------------------------------------

def test_seconds_until_next_run_before_target_same_day():
    # 00:00:00 UTC → next 00:05 is 300s away, same day.
    now = datetime(2026, 7, 11, 0, 0, 0, tzinfo=timezone.utc)
    assert main._seconds_until_next_run(now) == 300.0


def test_seconds_until_next_run_after_target_rolls_to_tomorrow():
    # 12:00 UTC → target 00:05 already passed today, so roll to tomorrow.
    now = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)
    expected = (
        datetime(2026, 7, 12, 0, 5, 0, tzinfo=timezone.utc) - now
    ).total_seconds()
    assert main._seconds_until_next_run(now) == expected


def test_seconds_until_next_run_exactly_at_target_rolls_forward():
    # At exactly 00:05:00 the next run is a full day out (target <= now).
    now = datetime(2026, 7, 11, 0, 5, 0, tzinfo=timezone.utc)
    assert main._seconds_until_next_run(now) == 24 * 3600.0


# ---------------------------------------------------------------------------
# run_once generation + per-day idempotency
# ---------------------------------------------------------------------------

def _make_due_recurring(db, account_id):
    """A monthly recurring entry that is overdue as of today."""
    rec = models.RecurringTransaction(
        user_id=1,
        account_id=account_id,
        description="Rent",
        amount=-500.0,
        frequency="monthly",
        start_date=date.today() - timedelta(days=40),
        next_due=date.today() - timedelta(days=10),
        is_active=True,
    )
    db.add(rec)
    db.commit()
    return rec


def test_run_due_recurring_generates_then_is_idempotent_same_day(db, test_account):
    _make_due_recurring(db, test_account.id)

    first = run_due_recurring(db)
    assert first >= 1  # at least the overdue period is generated

    # Second call the same day must be a no-op: next_due was advanced past today.
    second = run_due_recurring(db)
    assert second == 0


def test_run_recurring_once_uses_own_session_and_generates(db, test_account, monkeypatch):
    # _run_recurring_once opens its OWN session via SessionLocal. Point that at
    # the test session (and neutralise close) so generation is visible here.
    _make_due_recurring(db, test_account.id)

    monkeypatch.setattr(db, "close", lambda: None, raising=False)
    monkeypatch.setattr(main, "SessionLocal", lambda: db)

    count = main._run_recurring_once()
    assert count >= 1


def test_run_recurring_once_swallows_failure(monkeypatch):
    # A failing session must not propagate — the loop has to survive.
    class _Boom:
        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(main, "SessionLocal", lambda: _Boom())

    def _explode(_db):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(main.recurring, "run_due_recurring", _explode)

    # Returns 0, does not raise.
    assert main._run_recurring_once() == 0


# ---------------------------------------------------------------------------
# Timer task clean-cancel path
# ---------------------------------------------------------------------------

def test_timer_loop_cancels_cleanly():
    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(main._recurring_timer_loop())
        loop.run_until_complete(asyncio.sleep(0))  # let it reach the sleep
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            loop.run_until_complete(task)
        assert task.cancelled()
    finally:
        loop.close()
