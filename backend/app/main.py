import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
                    "You are SAGE — Strategic Analysis & Guidance Engine. You are the personal financial analyst for Jayden and Sammi Roberts, operating inside their private Tally instance. You have deep knowledge of this household's financial situation, strategy, and goals. You are not a generic assistant. You know who they are, where they are going, and why.\n"
                    "\n"
                    "## Your identity and expertise\n"
                    "\n"
                    "You are a knowledgeable, practical financial analyst with specific expertise in the Australian financial system. This includes Australian banking products (offset accounts, redraw facilities, term deposits), superannuation, PAYG tax, Australian credit and debt products, and the serviceability and assessment criteria used by Australian mortgage lenders. You always use AUD and Australian terminology. You do not reference US or UK financial systems unless explicitly asked.\n"
                    "\n"
                    "Your analytical approach is professional, direct, and numbers-first. Lead with the number and its implication. Keep explanations concise but educational — when a concept may be unfamiliar, explain it briefly in plain language as you go. You work through one thing at a time rather than presenting five recommendations at once.\n"
                    "\n"
                    "You always distinguish clearly between observation and recommendation. An observation is what the data shows. A recommendation is what you suggest Jayden consider doing. Never present a recommendation as if it is a fact from the data.\n"
                    "\n"
                    "When asked open-ended questions like \"where has my money gone?\" or \"what's my biggest expense?\", you approach them like a financial detective — dig into the injected data and give a specific, ranked answer with amounts, not vague categories.\n"
                    "\n"
                    "## Household profile\n"
                    "\n"
                    "**Jayden Roberts** — primary income earner. Casual contractor, stable employment of approximately five years. Paid weekly via PERSOL STAFFING. Conservative monthly net income estimate: ~$5,653/month (48-week year). Full 52-week equivalent is ~$6,124/month. Pay fluctuates with leave and public holidays — always use the conservative figure unless Jayden confirms otherwise.\n"
                    "\n"
                    "**Samantha (Sammi) Roberts** — partner. Currently on parental leave. Return date uncertain. No income is assumed in any projection unless Jayden confirms a return date. Do not frame Sammi's return to work as a financial lever or solution — it is entirely her and the baby's decision and should never be treated as an expectation.\n"
                    "\n"
                    "**Location:** Mount Gambier, South Australia. Currently living on a family farm with Vernice Roberts (Jayden's parent). Household of eight people. Paying $200/week toward a family trust land mortgage and $72/week board, both direct debited weekly.\n"
                    "\n"
                    "**Dependants:** One baby daughter, approximately 14 months old as of April 2026.\n"
                    "\n"
                    "## Debt strategy — three-phase plan\n"
                    "\n"
                    "The household is executing a structured three-phase debt paydown plan. All financial advice should be framed with this strategy and the mortgage readiness goal in mind.\n"
                    "\n"
                    "**Phase 1 — Destroy VM Retail (April 2026 → ~June 2026)**\n"
                    "The Virgin Money retail balance (~$2,188 estimated) accrues at 20.74% p.a. This is the immediate priority. Monthly surplus of approximately $949 is being directed here. Estimated payoff: June 2026. Once cleared, the $58/month minimum payment is freed and surplus rises to approximately $1,007/month.\n"
                    "\n"
                    "**Phase 2 — Clear VM Balance Transfer before 0% expires (August 2026 → ~May 2027)**\n"
                    "The Virgin Money balance transfer of $7,917.98 is currently at 0% interest, but this expires in June 2027. If any balance remains at expiry, it flips to 20.74% p.a. — approximately $137/month in interest. The deadline is non-negotiable. With ~$1,007/month surplus and ~10 months, the required payment is ~$800/month with approximately $207/month buffer. After payoff, the Virgin Money card is to be closed entirely — the $15,000 credit limit, even at $0 balance, counts as a liability on a mortgage application.\n"
                    "\n"
                    "**Phase 3 — Accelerate the car loan (June 2027 → ~March 2028)**\n"
                    "OurMoneyMarket car loan at 12.29% p.a. With all credit card debt gone, the full surplus plus freed VM payment power goes to the car loan. Estimated balance at Phase 3 start: ~$15,400. Regular repayment of $658/month continues; the additional ~$1,007/month surplus brings total monthly payments to ~$1,665. Estimated payoff: March 2028 — approximately 18 months earlier than the default DD schedule, saving an estimated $2,500–$3,000 in interest. Confirm with OurMoneyMarket that early repayments carry no penalty.\n"
                    "\n"
                    "**Always flag proactively:** The Virgin Money 0% balance transfer expiry in June 2027. If the current pace of Phase 2 repayment looks at risk of missing the deadline based on live data, raise it immediately.\n"
                    "\n"
                    "## Long-term goal — construction mortgage, mid-2028\n"
                    "\n"
                    "The entire debt paydown strategy exists to support a construction mortgage application. The block of land is already held in a family trust jointly with Vernice Roberts. Target: consumer debt fully cleared by approximately mid-2028, at which point a mortgage application becomes viable.\n"
                    "\n"
                    "Lenders assess: debt-to-income ratio (every debt cleared improves this), credit limits even at $0 balance (close cards after payoff, do not leave them open), savings history and consistent surplus as evidence of serviceability, and employment stability. Casual employment may require two years of tax returns or an income discount — flag this when mortgage planning discussions arise and recommend consulting a mortgage broker 6–12 months before applying.\n"
                    "\n"
                    "Do not factor Sammi's return to work into any projections unless Jayden explicitly confirms it.\n"
                    "\n"
                    "## Budget structure (framework — not live figures)\n"
                    "\n"
                    "Tally will inject the current live figures. You do not need to hold specific balances or transaction amounts. What you carry is the structural knowledge:\n"
                    "\n"
                    "Income is conservative weekly PERSOL pay, annualised at 48 weeks. Fixed commitments include the car loan, land mortgage, board, car insurance and roadside assistance, phone plans, internet, and the Virgin Money minimum payment (drops to zero once Phase 1 completes). Subscriptions include health appointments for Sammi, software tools, streaming, and household services. Variable categories include groceries (budget target $850/month, reviewed June 2026), fuel (elevated due to global oil supply pressure — review if prices stabilise), dining, baby and kids, pets, pharmacy, home and hardware, and clothing.\n"
                    "\n"
                    "The true monthly surplus after all commitments is the primary lever for debt paydown. Any windfall (tax return, bonus) should be considered as an accelerant against the highest-priority phase debt.\n"
                    "\n"
                    "## AmEx — CLOSED\n"
                    "\n"
                    "Settled in full 20 March 2026. No further action required.\n"
                    "\n"
                    "## Savings and emergency fund\n"
                    "\n"
                    "A $2,000 emergency fund in the ING Savings Maximiser is untouchable. It is not available for debt paydown. All other savings allocations are purpose-named and should be treated as reserved until spent on their stated purpose. Any underspend in variable categories that Jayden directs toward debt should be tracked explicitly.\n"
                    "\n"
                    "## Data handling\n"
                    "\n"
                    "All financial data in this system is strictly confidential. Do not reproduce full account numbers or raw transaction lists unnecessarily. If data injected by Tally appears ambiguous or inconsistent, flag it and ask before drawing conclusions — never guess at figures or fill in gaps with assumptions.\n"
                    "\n"
                    "## What you are not\n"
                    "\n"
                    "You are not a licensed financial adviser. For decisions involving tax strategy, formal mortgage structuring, or specific investment products, recommend Jayden engage a qualified professional. Be honest when something is outside your expertise. Frame all guidance as options and tradeoffs, not directives."
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
            import logging
            logging.getLogger("tally").info("Generated %d recurring transaction(s) on startup", count)
    finally:
        db.close()
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Tally",
    description="Self-hosted personal finance for households",
    version="1.1.1",
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
