import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import engine, SessionLocal, Base
from . import models
from .auth import hash_password
from .routers import auth, users, accounts, transactions, categories, budgets, savings, debt, imports, recurring, chat


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

    # [M-002] Remediate analyst persona contaminated with personal data in v1.1.1.
    # A private SAGE system prompt containing real names, income, debt strategy, and
    # location data was accidentally used as the analyst persona seed in v1.1.1.
    # v1.1.2 corrected the seed, but existing installs still carry the contaminated
    # prompt in their database. This fix detects the contaminated prompt by its unique
    # identifier string and resets both system_prompt and tone_notes to the clean
    # generic defaults. If the prompt has been user-customised (no identifier present),
    # it is left entirely untouched.
    analyst_persona = (
        db.query(models.Persona)
        .filter(
            models.Persona.name == "analyst",
            models.Persona.is_system == True,
        )
        .first()
    )
    if analyst_persona and analyst_persona.system_prompt and "Jayden and Sammi Roberts" in analyst_persona.system_prompt:
        analyst_persona.system_prompt = (
            "You are a knowledgeable household finance assistant with full access to this household's financial data. "
            "You can read accounts, transactions, budgets, savings goals, and debts — and suggest modifications where appropriate. "
            "Be concise, data-driven, and proactive about surfacing insights. Use exact figures when available. "
            "Always distinguish between observations (what the data shows) and recommendations (what you suggest the user consider). "
            "Lead with the number and its implication."
        )
        analyst_persona.tone_notes = "Professional, direct, numbers-first."
        db.commit()
        log.info("[M-002] Remediated analyst persona: removed contaminated v1.1.1 personal data seed, restored generic defaults")

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

    # [M-003] Remove duplicate imported transactions created by re-importing the same file.
    # Introduced in v1.1.5 alongside duplicate detection. This one-time cleanup removes
    # exact duplicates (same account_id, date, amount, description, source='import'),
    # keeping only the earliest row (lowest id) per group.

    # Find all import transactions grouped by the four dedup fields
    # Identify groups that have more than one row (i.e. have duplicates)
    # For each such group, delete all rows except the one with the minimum id.
    # We do this in Python to stay compatible with SQLite (no DELETE...JOIN syntax).

    dupes_removed = 0
    import_txs = (
        db.query(models.Transaction)
        .filter(models.Transaction.source == "import")
        .order_by(models.Transaction.account_id, models.Transaction.date, models.Transaction.amount, models.Transaction.description, models.Transaction.id)
        .all()
    )

    # Group by (account_id, date, amount, description)
    seen = {}
    to_delete = []
    for tx in import_txs:
        key = (tx.account_id, tx.date, tx.amount, tx.description)
        if key in seen:
            to_delete.append(tx)
        else:
            seen[key] = tx.id

    for tx in to_delete:
        db.delete(tx)
        dupes_removed += 1

    if dupes_removed:
        db.commit()
        log.info("[M-003] Removed %d duplicate imported transaction(s)", dupes_removed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
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

    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Tally",
    description="Self-hosted personal finance for households",
    version="1.2.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
app.include_router(imports.router)
app.include_router(recurring.router)
app.include_router(chat.router)


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
        """Catch-all: serve static files if they exist, otherwise serve index.html."""
        requested = STATIC_DIR / full_path
        if requested.exists() and requested.is_file():
            return FileResponse(requested)
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"detail": "Frontend not built"}
