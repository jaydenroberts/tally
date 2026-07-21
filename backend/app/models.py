from datetime import datetime, date as date_type
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Index, Integer, JSON, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from .database import Base


# ---------------------------------------------------------------------------
# Personas  (AI role system — UI built in Phase 4)
# ---------------------------------------------------------------------------

class Persona(Base):
    """
    Defines how an AI assistant should behave for a given user.
    data_access_level and can_modify_data are enforced by the AI layer;
    the rest is prompt engineering context.

    Slugs: "analyst" and "family" are the system defaults.
    """
    __tablename__ = "personas"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    system_prompt = Column(Text)
    # "full" | "summary" | "readonly"
    data_access_level = Column(String(20), nullable=False, default="full")
    can_modify_data = Column(Boolean, default=False, nullable=False)
    data_window_days = Column(Integer, default=90, nullable=False)
    tone_notes = Column(Text)
    is_system = Column(Boolean, default=True, nullable=False)   # prevents deletion
    # use_alter breaks the circular FK cycle with users.persona_id so create_all succeeds
    created_by = Column(Integer, ForeignKey("users.id", use_alter=True, name="fk_persona_created_by"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    users = relationship("User", foreign_keys="User.persona_id", back_populates="persona")
    memory_files = relationship("PersonaMemoryFile", back_populates="persona", order_by="PersonaMemoryFile.display_order")


# ---------------------------------------------------------------------------
# Persona Memory Files  (persistent AI context files — BACKLOG-009)
# ---------------------------------------------------------------------------

class PersonaMemoryFile(Base):
    """
    A persistent markdown context file attached to a persona.
    Active files are loaded into the system prompt at chat time,
    ordered by display_order.
    """
    __tablename__ = "persona_memory_files"

    id = Column(Integer, primary_key=True, index=True)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False, index=True)
    filename = Column(String(200), nullable=False)
    content = Column(Text, nullable=False, default="")
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    persona = relationship("Persona", back_populates="memory_files")


# ---------------------------------------------------------------------------
# Chat Sessions  (persistent chat history — BACKLOG-016, v1.4.4)
# ---------------------------------------------------------------------------

class ChatSession(Base):
    """
    A persisted chat conversation, scoped to (user, persona).

    persona_id is immutable after creation — a session never follows a user
    across persona switches (prevents cross-persona context bleed).
    provider stamps AI_PROVIDER at creation; resume is refused if the active
    provider differs (tool_use ids are provider-opaque — no cross-provider replay).
    """
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False)
    title = Column(String(200), nullable=True)
    provider = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    # Reserved for v1.1 soft-delete/archive — unused in v1.
    is_archived = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index(
            "ix_chat_sessions_user_persona_updated",
            "user_id", "persona_id", updated_at.desc(),
        ),
    )

    user = relationship("User")
    persona = relationship("Persona")
    # ORM-level cascade (children deleted explicitly) — the FK's ON DELETE
    # CASCADE remains as belt-and-braces for raw-SQL deletes. No passive_deletes:
    # SQLite only honours the DB cascade with PRAGMA foreign_keys=ON, which the
    # in-memory test engine does not set.
    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )


class ChatMessage(Base):
    """
    One row per chat turn fragment. `id` is the ordering key — SQLite rowids
    are monotonic per table, so ordering by (session_id, id ASC) has no
    MAX()+1 race window under streaming commits (no seq column by design).

    role: "user" | "assistant" | "tool_call" | "tool_result"
    content: text for user/assistant rows; JSON string for tool rows.
    """
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(20), nullable=False)
    # Mirrors the ChatRequest ChatMessage.content cap (4000 chars per row).
    content = Column(Text, nullable=False, default="")
    tool_use_id = Column(String(200), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_chat_messages_session_id", "session_id", "id"),
    )

    session = relationship("ChatSession", back_populates="messages")


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class Role(Base):
    """
    Role slugs ("owner", "viewer") are used in permission logic.
    display_name is editable and shown in the UI — renaming it never
    breaks access control.
    """
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)          # slug — do not change
    display_name = Column(String(100), nullable=False)              # editable label
    description = Column(Text)
    is_system = Column(Boolean, default=True, nullable=False)       # prevents deletion

    users = relationship("User", back_populates="role")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    # AUDIT-29: bumped on password change to invalidate outstanding JWTs (the token
    # carries a matching "ver" claim; a mismatch is rejected).
    token_version = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    role = relationship("Role", back_populates="users")
    persona = relationship("Persona", foreign_keys=[persona_id], back_populates="users")
    accounts = relationship("Account", back_populates="owner")
    budgets = relationship("Budget", back_populates="user")
    savings_goals = relationship("SavingsGoal", back_populates="user")
    debts = relationship("Debt", back_populates="user")
    import_logs = relationship("ImportLog", back_populates="user")


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    account_type = Column(String(50))      # checking, savings, credit, investment, loan, other
    institution = Column(String(200))
    balance = Column(Float, default=0.0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    status = Column(String(20), default="active", nullable=False)  # active | closed
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account")
    savings_goals = relationship("SavingsGoal", back_populates="linked_account")
    debts = relationship("Debt", back_populates="linked_account")


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    color = Column(String(7))              # hex: "#ea51b2"
    icon = Column(String(50))              # icon name/slug for frontend
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # NULL = system/shared
    is_system = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "user_id", name="uq_category_name_user"),
    )

    parent = relationship("Category", remote_side="Category.id", back_populates="children")
    children = relationship("Category", back_populates="parent")
    transactions = relationship("Transaction", back_populates="category")
    budgets = relationship("Budget", back_populates="category")


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    date = Column(Date, nullable=False, index=True)
    description = Column(String(500))
    amount = Column(Float, nullable=False)         # current authoritative amount
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    # Verification — automatic only, never set by user directly
    #   'manual'  → user-entered estimate, unverified
    #   'import'  → came from a bank statement, always verified
    source = Column(String(20), default="manual", nullable=False, index=True)
    is_verified = Column(Boolean, default=False, nullable=False, index=True)

    # Set when a bank import matches and overwrites a manual estimate
    original_amount = Column(Float, nullable=True)   # manual amount before bank overwrote it
    match_note = Column(Text, nullable=True)          # e.g. "Matched import; amount updated -45.00→-47.23"

    notes = Column(Text)
    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)
    savings_goal_id = Column(Integer, ForeignKey("savings_goals.id"), nullable=True, index=True)
    debt_id = Column(Integer, ForeignKey("debts.id"), nullable=True, index=True)
    # Classifies the transaction's role — used for budget exclusion and import matching.
    # Values: expense (default), income, transfer, debt_payment
    transaction_type = Column(String(20), default="expense", nullable=False, index=True)
    # Groups a transfer pair: both debit and credit transactions share the same value
    # (set to the debit transaction's id). Plain integer — not a FK.
    transfer_pair_id = Column(Integer, nullable=True, index=True)
    # Set when this transaction was created by the staged-import wizard (import_drafts).
    import_id = Column(Integer, ForeignKey("import_drafts.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    import_log = relationship("ImportLog", back_populates="transactions")
    import_draft = relationship("ImportDraft", back_populates="transactions", foreign_keys=[import_id])
    savings_goal = relationship("SavingsGoal", backref="withdrawal_transactions")
    debt = relationship("Debt", backref="payment_transactions")


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

class Budget(Base):
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    amount = Column(Float, nullable=False)
    period = Column(String(20), nullable=False)  # monthly, weekly, yearly
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="budgets")
    category = relationship("Category", back_populates="budgets")


# ---------------------------------------------------------------------------
# Savings Goals
# ---------------------------------------------------------------------------

class SavingsGoal(Base):
    __tablename__ = "savings_goals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    target_amount = Column(Float, nullable=False)
    current_amount = Column(Float, default=0.0, nullable=False)
    deadline = Column(Date, nullable=True)
    linked_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    monthly_contribution = Column(Float, nullable=True)  # advisory; used for projection
    is_completed = Column(Boolean, default=False, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="savings_goals")
    linked_account = relationship("Account", back_populates="savings_goals")
    contributions = relationship("SavingsContribution", back_populates="goal", order_by="SavingsContribution.contributed_at.desc()")


# ---------------------------------------------------------------------------
# Debts
# ---------------------------------------------------------------------------

class Debt(Base):
    __tablename__ = "debts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    creditor = Column(String(200))
    # Debt classification
    # credit_card | personal_loan | car_loan | mortgage | bnpl | other
    debt_type = Column(String(30), nullable=True)
    original_amount = Column(Float, nullable=False)
    current_balance = Column(Float, nullable=False)
    interest_rate = Column(Float)              # annual percentage
    # For 0% BT cards and BNPL — rate reverts to standard once this passes
    interest_free_end_date = Column(Date, nullable=True)
    minimum_payment = Column(Float)
    due_day = Column(Integer)                  # day of month (1-31)
    # avalanche | snowball | fixed
    paydown_strategy = Column(String(20), nullable=True)
    linked_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    is_paid_off = Column(Boolean, default=False, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="debts")
    linked_account = relationship("Account", back_populates="debts")
    payments = relationship("DebtPayment", back_populates="debt", order_by="DebtPayment.paid_at.desc()")


# ---------------------------------------------------------------------------
# Debt Payments  (audit trail for /api/debt/{id}/payment)
# ---------------------------------------------------------------------------

class DebtPayment(Base):
    """
    One record per payment logged against a debt.
    Provides a full audit trail independent of the current_balance figure.
    """
    __tablename__ = "debt_payments"

    id = Column(Integer, primary_key=True, index=True)
    debt_id = Column(Integer, ForeignKey("debts.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)   # current_balance after this payment
    notes = Column(Text, nullable=True)
    paid_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Optional FK to the transaction that represents this payment (set when linked or
    # auto-created by the log_payment endpoint with source_account_id).
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True, unique=True)

    debt = relationship("Debt", back_populates="payments")
    transaction = relationship("Transaction", foreign_keys=[transaction_id])


# ---------------------------------------------------------------------------
# Savings Contributions  (audit trail for /api/savings/{id}/contribute)
# ---------------------------------------------------------------------------

class SavingsContribution(Base):
    """
    One record per contribution logged against a savings goal.
    Provides a full audit trail independent of the current_amount figure.
    """
    __tablename__ = "savings_contributions"

    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("savings_goals.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)   # current_amount after this contribution
    notes = Column(Text, nullable=True)
    contributed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Optional FK to the source transaction (set when allocated via link-savings endpoint)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)

    goal = relationship("SavingsGoal", back_populates="contributions")
    transaction = relationship("Transaction", foreign_keys=[transaction_id])


# ---------------------------------------------------------------------------
# Recurring Transactions
# ---------------------------------------------------------------------------

class RecurringTransaction(Base):
    """
    A scheduled transaction that auto-generates a real Transaction on each
    due date. The scheduler runs on startup and checks for overdue entries.

    frequency values: daily | weekly | fortnightly | monthly | yearly
    """
    __tablename__ = "recurring_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    description = Column(String(500), nullable=False)
    amount = Column(Float, nullable=False)
    frequency = Column(String(20), nullable=False)   # daily | weekly | fortnightly | monthly | yearly
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)            # NULL = runs indefinitely
    next_due = Column(Date, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", backref="recurring_transactions")
    account = relationship("Account")
    category = relationship("Category")


# ---------------------------------------------------------------------------
# Import Logs
# ---------------------------------------------------------------------------

class ImportLog(Base):
    __tablename__ = "import_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_type = Column(String(10))             # csv, pdf
    imported_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    transaction_count = Column(Integer, default=0)
    status = Column(String(20))                # success, partial, failed
    error_detail = Column(Text)

    user = relationship("User", back_populates="import_logs")
    transactions = relationship("Transaction", back_populates="import_log")


# ---------------------------------------------------------------------------
# Import Drafts  (staged-import wizard — v1.4.0)
# ---------------------------------------------------------------------------

class ImportDraft(Base):
    """
    Staging area for a CSV upload before the user commits.
    Status flow: preview_ready → committing → committed → rolled_back | cancelled
    Expires after DRAFT_TTL_HOURS (default 24h); M-009b cancels expired drafts on boot.
    """
    __tablename__ = "import_drafts"

    id             = Column(Integer, primary_key=True, index=True)
    user_id        = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id     = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    filename       = Column(String(255), nullable=False)     # sanitised at ingest (BASTION-11)
    format         = Column(String(10), nullable=False)      # 'csv' | 'ofx' | 'qif'
    parsed_meta    = Column(JSON, nullable=True)             # row_count, header, detected_account_last4
    column_mapping = Column(JSON, nullable=True)             # {"date": 0, "description": 1, "amount": 2}
    status         = Column(String(20), nullable=False, index=True)
    # 'preview_ready' | 'committing' | 'committed' | 'cancelled' | 'rolled_back'
    committed_at   = Column(DateTime, nullable=True)
    created_at     = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at     = Column(DateTime, nullable=False)

    rows         = relationship("ImportDraftRow", back_populates="draft", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="import_draft", foreign_keys="Transaction.import_id")
    account      = relationship("Account")
    user         = relationship("User")


class ImportDraftRow(Base):
    """One CSV data row within an ImportDraft."""
    __tablename__ = "import_draft_rows"

    id              = Column(Integer, primary_key=True, index=True)
    draft_id        = Column(Integer, ForeignKey("import_drafts.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    row_index       = Column(Integer, nullable=False)
    raw             = Column(JSON, nullable=False)           # original CSV row as list[str]
    # Resolved fields after column mapping:
    date            = Column(Date, nullable=True)
    description     = Column(String(500), nullable=True)
    amount          = Column(Numeric(14, 2), nullable=True)  # kept as Numeric; cast to float on commit
    category_id     = Column(Integer, ForeignKey("categories.id"), nullable=True)
    # Dedup result:
    duplicate_of    = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    duplicate_score = Column(Float, nullable=True)
    # User decisions:
    excluded        = Column(Boolean, nullable=False, default=False)
    user_edited     = Column(Boolean, nullable=False, default=False)

    draft = relationship("ImportDraft", back_populates="rows")
