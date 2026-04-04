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
from .routers import auth, users, accounts, transactions, categories, budgets, savings, debt, imports, recurring


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
                    "You are a precise financial analyst assistant for a household budget app. "
                    "You have full read access to all financial data and may suggest modifications. "
                    "Be concise, data-driven, and proactive about surfacing insights. "
                    "Use exact figures when available."
                ),
                data_access_level="full",
                can_modify_data=True,
                tone_notes="Professional, direct, numbers-first.",
                is_system=True,
            ),
            models.Persona(
                name="family",
                description="Read-only access. Safe for household members who should not modify data.",
                system_prompt=(
                    "You are a friendly household finance assistant. "
                    "You can see summaries of the household's financial data but cannot make changes. "
                    "Keep explanations simple and encouraging. Avoid jargon."
                ),
                data_access_level="readonly",
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_database(db)
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
    version="0.1.0",
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
