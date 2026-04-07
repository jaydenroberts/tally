from datetime import datetime, date as date_type
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint,
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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    import_log = relationship("ImportLog", back_populates="transactions")


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

    debt = relationship("Debt", back_populates="payments")


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

    goal = relationship("SavingsGoal", back_populates="contributions")


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
