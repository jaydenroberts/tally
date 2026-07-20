import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import engine, SessionLocal, Base
from . import models
from .auth import hash_password
from .routers import auth, users, accounts, transactions, categories, budgets, savings, debt, imports, recurring, chat, chat_sessions, dashboard


# ---------------------------------------------------------------------------
# Database initialisation and seeding
# ---------------------------------------------------------------------------

def seed_database(db: Session) -> None:
    """Seed personas, roles, and default categories on a fresh database."""

    # 1. Personas — must come before users due to users.persona_id FK
    if not db.query(models.Persona).first():
        db.add_all([
            models.Persona(
                name="analyst",
                description="Full access with permission to modify data. For household owners.",
                system_prompt=(
                    "You are a knowledgeable household finance assistant with full access to this household's financial data. "
                    "You can read accounts, transactions, budgets, savings goals, and debts — and suggest modifications where appropriate. "
                    "Be concise, data-driven, and proactive about surfacing insights. Use exact figures when available. "
                    "Always distinguish between observations (what the data shows) and recommendations (what you suggest the user consider). "
                    "Lead with the number and its implication."
                ),
                data_access_level="full",
                can_modify_data=True,
                tone_notes="Professional, direct, numbers-first.",
                is_system=True,
            ),
            models.Persona(
                name="family",
                description="Summary-only access. Safe for household members who should not see individual transactions or account details.",
                system_prompt=(
                    "You are a friendly household finance assistant. "
                    "You can see summaries of the household's financial data but cannot make changes. "
                    "Keep explanations simple and encouraging. Avoid jargon."
                ),
                data_access_level="summary",
                can_modify_data=False,
                tone_notes="Warm, encouraging, plain language.",
                is_system=True,
            ),
        ])
        db.commit()

    # 2. Roles
    if not db.query(models.Role).first():
        db.add_all([
            models.Role(
                name="owner",
                display_name="Owner",
                description="Full access — manage users, accounts, and all household data.",
                is_system=True,
            ),
            models.Role(
                name="viewer",
                display_name="Viewer",
                description="Read-only access to shared household financial data.",
                is_system=True,
            ),
        ])
        db.commit()

    # 3. Default system categories
    if not db.query(models.Category).filter(models.Category.is_system == True).first():
        defaults = [
            ("Housing",       "#a1efe4", "home"),
            ("Food & Dining", "#00f769", "utensils"),
            ("Transport",     "#ea51b2", "car"),
            ("Health",        "#f7f7fb", "heart"),
            ("Entertainment", "#a1efe4", "tv"),
            ("Shopping",      "#ea51b2", "shopping-bag"),
            ("Savings",       "#00f769", "piggy-bank"),
            ("Income",        "#00f769", "trending-up"),
            ("Utilities",     "#a1efe4", "zap"),
            ("Insurance",     "#f7f7fb", "shield"),
            ("Debt Payment",  "#ea51b2", "credit-card"),
            ("Other",         "#f7f7fb", "more-horizontal"),
        ]
        db.add_all([
            models.Category(name=name, color=color, icon=icon, is_system=True)
            for name, color, icon in defaults
        ])
        db.commit()

    # 4. Auto-create first owner from environment variables if set
    owner_username = os.getenv("FIRST_RUN_OWNER_USERNAME")
    owner_password = os.getenv("FIRST_RUN_OWNER_PASSWORD")
    if owner_username and owner_password and not db.query(models.User).first():
        owner_role    = db.query(models.Role).filter(models.Role.name == "owner").first()
        analyst_persona = db.query(models.Persona).filter(models.Persona.name == "analyst").first()
        db.add(models.User(
            username=owner_username,
            hashed_password=hash_password(owner_password),
            role_id=owner_role.id,
            persona_id=analyst_persona.id if analyst_persona else None,
        ))
        db.commit()


# ---------------------------------------------------------------------------
# Startup migration runner
# ---------------------------------------------------------------------------
# Pattern: add one idempotent fix per issue below. Each fix checks whether
# it is needed before applying so it is safe to run on every container boot.
# Do NOT use Alembic for these — they are data fixes, not schema changes.
# ---------------------------------------------------------------------------

def run_startup_migrations(db: Session) -> None:
    """Run idempotent data fixes on every startup. Safe to re-run indefinitely."""
    import logging
    log = logging.getLogger("tally.migrations")

    # [M-001] Fix family persona data_access_level seeded as "readonly" in v1.1.0.
    # The correct value is "summary". Databases upgraded from v1.1.0 will have the
    # wrong value because the seed block only runs on empty databases.
    family_persona = (
        db.query(models.Persona)
        .filter(
            models.Persona.name == "family",
            models.Persona.is_system == True,
            models.Persona.data_access_level == "readonly",
        )
        .first()
    )
    if family_persona:
        family_persona.data_access_level = "summary"
        db.commit()
        log.info("[M-001] Fixed family persona data_access_level: readonly → summary")

    # [M-002] Retired in v1.3.0.
    # This migration detected and removed a contaminated analyst persona prompt that
    # was accidentally seeded with private household data in v1.1.1. The detector
    # relied on a personal name string which cannot be shipped in a public repository.
    # Any install that reached v1.3.0 without having passed through M-002 is
    # considered out of the supported upgrade path — manual persona reset via Settings
    # is required in that unlikely case.

    # [M-004] Add savings_goal_id and debt_id to transactions table.
    # Must run before M-003 because M-003 uses ORM queries on Transaction which
    # now includes these columns in the model definition.
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(transactions)")).fetchall()]
    if "savings_goal_id" not in cols:
        db.execute(text("ALTER TABLE transactions ADD COLUMN savings_goal_id INTEGER REFERENCES savings_goals(id)"))
        db.commit()
        log.info("[M-004] Added savings_goal_id column to transactions")
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(transactions)")).fetchall()]
    if "debt_id" not in cols:
        db.execute(text("ALTER TABLE transactions ADD COLUMN debt_id INTEGER REFERENCES debts(id)"))
        db.commit()
        log.info("[M-004] Added debt_id column to transactions")

    # [M-005] Add status column to accounts table (active/closed lifecycle).
    acct_cols = [row[1] for row in db.execute(text("PRAGMA table_info(accounts)")).fetchall()]
    if "status" not in acct_cols:
        db.execute(text("ALTER TABLE accounts ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"))
        db.commit()
        log.info("[M-005] Added status column to accounts")

    # [M-006] Add transaction_type to transactions and transaction_id to debt_payments.
    # transaction_type classifies transactions for budget exclusion and import matching.
    # Values: expense (default), income, transfer, debt_payment.
    # transaction_id on DebtPayment links a payment record to its originating transaction.
    tx_cols = [row[1] for row in db.execute(text("PRAGMA table_info(transactions)")).fetchall()]
    if "transaction_type" not in tx_cols:
        try:
            db.execute(text("ALTER TABLE transactions ADD COLUMN transaction_type TEXT NOT NULL DEFAULT 'expense'"))
            db.commit()
            log.info("[M-006] Added transaction_type column to transactions")
        except Exception as e:
            if "duplicate column name" not in str(e).lower():
                raise
    db.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_transactions_transaction_type "
        "ON transactions(transaction_type)"
    ))
    db.commit()

    dp_cols = [row[1] for row in db.execute(text("PRAGMA table_info(debt_payments)")).fetchall()]
    if "transaction_id" not in dp_cols:
        try:
            db.execute(text("ALTER TABLE debt_payments ADD COLUMN transaction_id INTEGER REFERENCES transactions(id)"))
            db.commit()
            log.info("[M-006] Added transaction_id column to debt_payments")
        except Exception as e:
            if "duplicate column name" not in str(e).lower():
                raise

    # Backfill: any transaction already linked to a debt that is still typed as
    # 'expense' should be reclassified as 'debt_payment' for consistency.
    result = db.execute(text(
        "UPDATE transactions SET transaction_type = 'debt_payment' "
        "WHERE debt_id IS NOT NULL AND transaction_type = 'expense'"
    ))
    if result.rowcount:
        db.commit()
        log.info("[M-006] Backfilled %d transaction(s) to transaction_type='debt_payment'", result.rowcount)

    # [M-007] Add transfer_pair_id to transactions table.
    # Plain integer grouping key (not a FK) — both sides of a transfer share the
    # same value, set to the id of the debit (outgoing) transaction created first.
    tx_cols_m007 = [row[1] for row in db.execute(text("PRAGMA table_info(transactions)")).fetchall()]
    if "transfer_pair_id" not in tx_cols_m007:
        try:
            db.execute(text("ALTER TABLE transactions ADD COLUMN transfer_pair_id INTEGER"))
            db.commit()
            log.info("[M-007] Added transfer_pair_id column to transactions")
        except Exception as e:
            if "duplicate column name" not in str(e).lower():
                raise
    db.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_transactions_transfer_pair_id "
        "ON transactions(transfer_pair_id)"
    ))
    db.commit()

    # [M-008] Add transaction_id to savings_contributions.
    # Links a contribution record back to the source transaction when money is
    # allocated to savings goals via POST /api/transactions/{id}/link-savings.
    sc_cols = [row[1] for row in db.execute(text("PRAGMA table_info(savings_contributions)")).fetchall()]
    if "transaction_id" not in sc_cols:
        try:
            db.execute(text("ALTER TABLE savings_contributions ADD COLUMN transaction_id INTEGER REFERENCES transactions(id)"))
            db.commit()
            log.info("[M-008] Added transaction_id column to savings_contributions")
        except Exception as e:
            if "duplicate column name" not in str(e).lower():
                raise

    # [M-010] Add token_version to users (AUDIT-29 — JWT invalidation on password change).
    # Safe on existing DBs: existing rows default to 0, matching the default claim minted
    # for pre-migration tokens.
    user_cols = [row[1] for row in db.execute(text("PRAGMA table_info(users)")).fetchall()]
    if "token_version" not in user_cols:
        try:
            db.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))
            db.commit()
            log.info("[M-010] Added token_version column to users")
        except Exception as e:
            if "duplicate column name" not in str(e).lower():
                raise

    # [M-009] Add import_id column to transactions (staged-import wizard — v1.4.0).
    # New tables (import_drafts, import_draft_rows) are created by Base.metadata.create_all()
    # in lifespan — this migration only handles the ALTER on the existing transactions table.
    # MASON-1: guard with PRAGMA table_info(import_drafts) to ensure the FK target exists first.
    id_tbl = [row[1] for row in db.execute(text("PRAGMA table_info(import_drafts)")).fetchall()]
    if id_tbl:  # import_drafts table exists — safe to add FK column
        tx_cols_m009 = [row[1] for row in db.execute(text("PRAGMA table_info(transactions)")).fetchall()]
        if "import_id" not in tx_cols_m009:
            db.execute(text(
                "ALTER TABLE transactions ADD COLUMN import_id INTEGER REFERENCES import_drafts(id)"
            ))
            db.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_transactions_import_id "
                "ON transactions(import_id) WHERE import_id IS NOT NULL"
            ))
            db.commit()
            log.info("[M-009] Added import_id column + partial index to transactions")

    # [M-011] Chat session persistence (BACKLOG-016, v1.4.4).
    # The chat_sessions / chat_messages tables are created by Base.metadata.create_all()
    # in lifespan (before this runner). This migration only ensures the supporting
    # indexes exist on databases upgraded from earlier versions, plus a defensive
    # sanity check that create_all actually saw the new models (a missed model
    # import in models.py would silently no-op table creation).
    # NOTE: the BACKLOG-016 spec labels this "M-009"; renumbered to M-011 because
    # M-009/M-009b/M-010 were consumed by v1.4.0/v1.4.2.
    try:
        db.execute(text("SELECT 1 FROM chat_sessions LIMIT 0"))
        db.execute(text("SELECT 1 FROM chat_messages LIMIT 0"))
    except Exception:
        db.rollback()
        log.warning(
            "[M-011] chat_sessions/chat_messages tables missing after create_all — "
            "chat persistence will not work. Check model imports in models.py."
        )
    else:
        db.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_persona_updated "
            "ON chat_sessions(user_id, persona_id, updated_at DESC)"
        ))
        db.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_chat_messages_session_id "
            "ON chat_messages(session_id, id)"
        ))
        db.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_chat_messages_tool_use_id "
            "ON chat_messages(tool_use_id)"
        ))
        db.commit()

    # [M-009b] Auto-cancel expired import drafts (runs every boot — no scheduler needed for homelab).
    result = db.execute(text(
        "UPDATE import_drafts SET status = 'cancelled' "
        "WHERE status = 'preview_ready' AND expires_at < datetime('now')"
    ))
    if result.rowcount:
        db.commit()
        log.info("[M-009b] Cancelled %d expired draft(s)", result.rowcount)

    # [BASTION-8] Recover drafts stuck in 'committing' from a prior crash mid-commit.
    # 'committing' is never a stable resting state — reset to 'preview_ready' so user can retry.
    result = db.execute(text(
        "UPDATE import_drafts SET status = 'preview_ready' WHERE status = 'committing'"
    ))
    if result.rowcount:
        db.commit()
        log.info("[BASTION-8] Recovered %d draft(s) from stuck 'committing' state", result.rowcount)

    # [M-003] Remove duplicate imported transactions created by re-importing the same file.
    # Introduced in v1.1.5 alongside duplicate detection. This one-time cleanup removes
    # exact duplicates (same account_id, date, amount, description, source='import'),
    # keeping only the earliest row (lowest id) per group.
    #
    # AUDIT-02/BACKLOG-041 (v1.4.1.1): this cleanup is destructive, so — unlike the
    # idempotent column/data fixes above — it must run EXACTLY ONCE. We gate it behind
    # a persisted marker row in schema_migrations. We also never delete a transaction
    # that is still referenced by a child row (debt_payments, savings_contributions,
    # import_draft_rows), which would raise IntegrityError under PRAGMA foreign_keys=ON.
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "id TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    ))
    db.commit()

    already_applied = db.execute(text(
        "SELECT 1 FROM schema_migrations WHERE id = 'M-003'"
    )).first()

    if not already_applied:
        # Find all import transactions grouped by the four dedup fields.
        # Identify groups that have more than one row (i.e. have duplicates).
        # For each such group, delete all rows except the one with the minimum id.
        # We do this in Python to stay compatible with SQLite (no DELETE...JOIN syntax).
        dupes_removed = 0
        import_txs = (
            db.query(models.Transaction)
            .filter(models.Transaction.source == "import")
            .order_by(models.Transaction.account_id, models.Transaction.date, models.Transaction.amount, models.Transaction.description, models.Transaction.id)
            .all()
        )

        # Collect transaction ids that are still referenced by a child row. Deleting
        # any of these would violate a foreign key, so we skip them entirely.
        referenced_ids = set()
        for table, col in (
            ("debt_payments", "transaction_id"),
            ("savings_contributions", "transaction_id"),
            ("import_draft_rows", "duplicate_of"),
        ):
            rows = db.execute(text(
                f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL"
            )).fetchall()
            referenced_ids.update(r[0] for r in rows)

        # Group by (account_id, date, amount, description); keep the earliest id.
        seen = {}
        to_delete = []
        for tx in import_txs:
            key = (tx.account_id, tx.date, tx.amount, tx.description)
            if key in seen:
                # Never delete a transaction another table still points at.
                if tx.id in referenced_ids:
                    continue
                to_delete.append(tx)
            else:
                seen[key] = tx.id

        for tx in to_delete:
            db.delete(tx)
            dupes_removed += 1

        # Record the marker in the same transaction as the deletes so the cleanup
        # and its completion marker commit atomically — it can never run twice.
        db.execute(text("INSERT INTO schema_migrations (id) VALUES ('M-003')"))
        db.commit()
        if dupes_removed:
            log.info("[M-003] Removed %d duplicate imported transaction(s)", dupes_removed)
        log.info("[M-003] One-time dedup cleanup complete; marker recorded")


# ---------------------------------------------------------------------------
# In-process daily recurring-transaction trigger (BACKLOG-025)
# ---------------------------------------------------------------------------
# A dependency-free asyncio task started in the lifespan. It wakes shortly
# after local-midnight-UTC (00:05) each day and generates any due recurring
# transactions, mirroring the startup run. No APScheduler / external scheduler.
#
# Idempotency: run_due_recurring() only processes rows with next_due <= today
# and advances next_due past today after generating, so a same-day second run
# (e.g. startup run + first timer run coinciding) generates nothing. The
# next_due advancement IS the double-generation guard — no extra guard needed.
# ---------------------------------------------------------------------------

RECURRING_RUN_HOUR_UTC = 0
RECURRING_RUN_MINUTE_UTC = 5


def _seconds_until_next_run(now: datetime) -> float:
    """
    Seconds from ``now`` until the next 00:05 UTC. Pure and injectable so the
    scheduling arithmetic is unit-testable without sleeping. ``now`` must be a
    timezone-aware UTC datetime.
    """
    target = now.replace(
        hour=RECURRING_RUN_HOUR_UTC,
        minute=RECURRING_RUN_MINUTE_UTC,
        second=0,
        microsecond=0,
    )
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


def _run_recurring_once() -> int:
    """
    Open a fresh DB session and generate any due recurring transactions.
    Never reuses a request session. Returns the number generated. Any failure
    is logged (message only — no data-bearing stack trace) and does not
    propagate, so the timer loop survives one bad run.
    """
    log = logging.getLogger("tally")
    db = SessionLocal()
    try:
        count = recurring.run_due_recurring(db)
        if count:
            log.info("Generated %d recurring transaction(s) on daily timer", count)
        return count
    except Exception as exc:  # noqa: BLE001 — loop must survive any single failure
        db.rollback()
        log.error("Recurring timer run failed: %s", type(exc).__name__)
        return 0
    finally:
        db.close()


async def _recurring_timer_loop() -> None:
    """
    Sleep until the next 00:05 UTC, run generation off the event loop (the DB
    layer is sync SQLAlchemy), then repeat. Cancelled cleanly on shutdown.
    """
    log = logging.getLogger("tally")
    try:
        while True:
            delay = _seconds_until_next_run(datetime.now(timezone.utc))
            await asyncio.sleep(delay)
            await run_in_threadpool(_run_recurring_once)
    except asyncio.CancelledError:
        log.info("Recurring timer stopped")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_database(db)
        run_startup_migrations(db)
        # Generate any overdue recurring transactions on startup
        count = recurring.run_due_recurring(db)
        if count:
            logging.getLogger("tally").info("Generated %d recurring transaction(s) on startup", count)
    finally:
        db.close()

    # Warn operators that the recovery endpoint is live if the token is set.
    if os.getenv("RECOVERY_TOKEN"):
        logging.getLogger("tally").warning(
            "WARNING: RECOVERY_TOKEN is set — password recovery endpoint is active. Remove after use. "
            "Use a token of at least 32 random characters (e.g. openssl rand -hex 32)."
        )

    # Start the daily in-process recurring-transaction timer (BACKLOG-025).
    recurring_task = asyncio.create_task(_recurring_timer_loop())

    try:
        yield
    finally:
        recurring_task.cancel()
        try:
            await recurring_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Tally",
    description="Self-hosted personal finance for households",
    version="1.4.3",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS — Tally is served same-origin (SPA bundled into the app), so the browser
# does not normally issue cross-origin requests. Auth is a Bearer header, not a
# cookie, so credentialed CORS is unnecessary (and `allow_origins=["*"]` with
# `allow_credentials=True` is rejected by the spec anyway). Operators who front
# Tally with a separate origin list those origins explicitly via ALLOWED_ORIGINS.
_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8091").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(budgets.router)
app.include_router(savings.router)
app.include_router(debt.router)
app.include_router(imports.router, prefix="/api")
app.include_router(recurring.router)
app.include_router(chat_sessions.router)
app.include_router(chat.router)
app.include_router(dashboard.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "tally"}


# ---------------------------------------------------------------------------
# Serve React SPA (must come after API routes)
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Catch-all: serve static files if they exist, otherwise serve index.html.

        AUDIT-01/BACKLOG-040 (v1.4.1.1): this route is unauthenticated, so the
        requested path MUST be confined to STATIC_DIR. Without containment,
        GET /../../data/tally.db escapes the static root and leaks the database.
        We resolve the path and confirm it stays inside STATIC_DIR before serving;
        anything outside falls through to the SPA index.
        """
        static_root = STATIC_DIR.resolve()
        requested = (STATIC_DIR / full_path).resolve(strict=False)
        if (
            requested.is_file()
            and requested.is_relative_to(static_root)
        ):
            return FileResponse(requested)
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"detail": "Frontend not built"}
