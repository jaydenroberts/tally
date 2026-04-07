from datetime import datetime, date
from typing import Literal, Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

DataAccessLevel = Literal["full", "summary", "readonly"]


class PersonaCreate(BaseModel):
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    data_access_level: DataAccessLevel = "full"
    can_modify_data: bool = False
    data_window_days: int = 90
    tone_notes: Optional[str] = None


class PersonaUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    data_access_level: Optional[DataAccessLevel] = None
    can_modify_data: Optional[bool] = None
    data_window_days: Optional[int] = None
    tone_notes: Optional[str] = None


class PersonaResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    data_access_level: str
    can_modify_data: bool
    data_window_days: int
    tone_notes: Optional[str] = None
    is_system: bool
    created_by: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class RoleBase(BaseModel):
    display_name: str
    description: Optional[str] = None


class RoleCreate(RoleBase):
    name: str  # slug


class RoleUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None


class RoleResponse(RoleBase):
    id: int
    name: str
    is_system: bool

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    username: str
    email: Optional[str] = None
    password: str
    role_id: int


class UserUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    role_id: Optional[int] = None
    persona_id: Optional[int] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    role: RoleResponse
    persona: Optional[PersonaResponse] = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class AccountCreate(BaseModel):
    name: str
    account_type: Optional[str] = None
    institution: Optional[str] = None
    balance: float = 0.0
    currency: str = "USD"
    notes: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_type: Optional[str] = None
    institution: Optional[str] = None
    balance: Optional[float] = None
    currency: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class AccountResponse(BaseModel):
    id: int
    user_id: int
    name: str
    account_type: Optional[str] = None
    institution: Optional[str] = None
    balance: float
    currency: str
    is_active: bool
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    color: Optional[str] = None
    icon: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None
    color: Optional[str] = None
    icon: Optional[str] = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    parent_id: Optional[int] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    user_id: Optional[int] = None
    is_system: bool

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

class TransactionCreate(BaseModel):
    account_id: int
    date: date
    description: Optional[str] = None
    amount: float
    category_id: Optional[int] = None
    notes: Optional[str] = None
    # source and is_verified are set by the backend; not accepted from clients


class TransactionUpdate(BaseModel):
    date: Optional[date] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    category_id: Optional[int] = None
    notes: Optional[str] = None
    # is_verified intentionally excluded — verification is automatic only


class TransactionResponse(BaseModel):
    id: int
    account_id: int
    date: date
    description: Optional[str] = None
    amount: float
    source: str                                    # 'manual' | 'import'
    is_verified: bool
    original_amount: Optional[float] = None        # set if bank overwrote a manual entry
    match_note: Optional[str] = None
    category_id: Optional[int] = None
    category: Optional[CategoryResponse] = None
    notes: Optional[str] = None
    import_log_id: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Import Logs  (defined here so ReconciliationSummary can reference it directly)
# ---------------------------------------------------------------------------

class ImportLogResponse(BaseModel):
    id: int
    user_id: int
    filename: str
    file_type: Optional[str] = None
    imported_at: datetime
    transaction_count: int
    status: Optional[str] = None
    error_detail: Optional[str] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Reconciliation (returned by import endpoint)
# ---------------------------------------------------------------------------

class MatchWarning(BaseModel):
    transaction_id: int
    description: Optional[str]
    manual_amount: float
    bank_amount: float


class ReconciliationSummary(BaseModel):
    matched_count: int          # manual estimates matched + verified by this import
    new_from_bank_count: int    # brand-new transactions created from this import
    estimates_pending: int      # unverified manual entries still in this account
    amount_diff_warnings: list[MatchWarning]
    import_log: ImportLogResponse


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

class BudgetCreate(BaseModel):
    category_id: int
    amount: float
    period: str  # monthly, weekly, yearly
    start_date: date
    end_date: Optional[date] = None


class BudgetUpdate(BaseModel):
    amount: Optional[float] = None
    period: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None


class BudgetResponse(BaseModel):
    id: int
    user_id: int
    category_id: int
    category: Optional[CategoryResponse] = None
    amount: float
    period: str
    start_date: date
    end_date: Optional[date] = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class BudgetStatus(BaseModel):
    """Budget with live spending breakdown for a given month."""
    budget: BudgetResponse
    verified_spend: float       # absolute spend confirmed by bank statements
    estimated_spend: float      # spend from unverified manual entries
    total_spend: float          # verified + estimated
    remaining: float            # budget.amount - total_spend (can be negative)
    pct_total: float            # total_spend / budget.amount * 100 (capped display at 100)
    pct_verified: float         # verified_spend / budget.amount * 100
    pct_estimated: float        # estimated_spend / budget.amount * 100
    status: str                 # "healthy" | "warning" | "over"


# ---------------------------------------------------------------------------
# Savings Goals
# ---------------------------------------------------------------------------

class SavingsGoalCreate(BaseModel):
    name: str
    target_amount: float
    current_amount: float = 0.0
    monthly_contribution: Optional[float] = None
    deadline: Optional[date] = None
    linked_account_id: Optional[int] = None
    notes: Optional[str] = None


class SavingsGoalUpdate(BaseModel):
    name: Optional[str] = None
    target_amount: Optional[float] = None
    current_amount: Optional[float] = None
    monthly_contribution: Optional[float] = None
    deadline: Optional[date] = None
    linked_account_id: Optional[int] = None
    is_completed: Optional[bool] = None
    notes: Optional[str] = None


class SavingsGoalResponse(BaseModel):
    id: int
    user_id: int
    name: str
    target_amount: float
    current_amount: float
    monthly_contribution: Optional[float] = None
    deadline: Optional[date] = None
    linked_account_id: Optional[int] = None
    linked_account: Optional[AccountResponse] = None
    is_completed: bool
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ContributionRequest(BaseModel):
    amount: float
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Debts
# ---------------------------------------------------------------------------

class DebtCreate(BaseModel):
    name: str
    creditor: Optional[str] = None
    debt_type: Optional[str] = None          # credit_card | personal_loan | car_loan | mortgage | bnpl | other
    original_amount: float
    current_balance: float
    interest_rate: Optional[float] = None    # annual %
    interest_free_end_date: Optional[date] = None
    minimum_payment: Optional[float] = None
    due_day: Optional[int] = None
    paydown_strategy: Optional[str] = None   # avalanche | snowball | fixed
    linked_account_id: Optional[int] = None
    notes: Optional[str] = None


class DebtUpdate(BaseModel):
    name: Optional[str] = None
    creditor: Optional[str] = None
    debt_type: Optional[str] = None
    current_balance: Optional[float] = None
    interest_rate: Optional[float] = None
    interest_free_end_date: Optional[date] = None
    minimum_payment: Optional[float] = None
    due_day: Optional[int] = None
    paydown_strategy: Optional[str] = None
    linked_account_id: Optional[int] = None
    is_paid_off: Optional[bool] = None
    notes: Optional[str] = None


class DebtResponse(BaseModel):
    id: int
    user_id: int
    name: str
    creditor: Optional[str] = None
    debt_type: Optional[str] = None
    original_amount: float
    current_balance: float
    interest_rate: Optional[float] = None
    interest_free_end_date: Optional[date] = None
    minimum_payment: Optional[float] = None
    due_day: Optional[int] = None
    paydown_strategy: Optional[str] = None
    linked_account_id: Optional[int] = None
    linked_account: Optional[AccountResponse] = None
    is_paid_off: bool
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PaymentRequest(BaseModel):
    amount: float
    notes: Optional[str] = None


class DebtPaymentResponse(BaseModel):
    id: int
    debt_id: int
    amount: float
    balance_after: float
    notes: Optional[str] = None
    paid_at: datetime

    model_config = {"from_attributes": True}


class SavingsContributionResponse(BaseModel):
    id: int
    goal_id: int
    amount: float
    balance_after: float
    notes: Optional[str] = None
    contributed_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Recurring Transactions
# ---------------------------------------------------------------------------

RecurringFrequency = Literal["daily", "weekly", "fortnightly", "monthly", "yearly"]


class RecurringTransactionCreate(BaseModel):
    account_id: int
    category_id: Optional[int] = None
    description: str
    amount: float
    frequency: RecurringFrequency
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None


class RecurringTransactionUpdate(BaseModel):
    category_id: Optional[int] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    frequency: Optional[RecurringFrequency] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class RecurringTransactionResponse(BaseModel):
    id: int
    user_id: int
    account_id: int
    account: Optional[AccountResponse] = None
    category_id: Optional[int] = None
    category: Optional[CategoryResponse] = None
    description: str
    amount: float
    frequency: str
    start_date: date
    end_date: Optional[date] = None
    next_due: date
    is_active: bool
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ImportLogResponse is defined above (before ReconciliationSummary) to avoid forward refs.
