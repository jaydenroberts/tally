"""Single source of truth for how ``Transaction.transaction_type`` participates
in money aggregates.

Why this module exists
----------------------
Every income/expense aggregate in the app must filter on an **inclusive
whitelist** built from the constants below.

An *exclusive* filter — "everything except transfers" — fails **open**: the day
a new ``transaction_type`` is added, it silently starts counting as ordinary
spend or income at every site that was not updated. The failure is silent and
it is on real money.

An *inclusive* whitelist fails **closed**: a type the aggregates have not been
taught about is excluded from flow until it is added here, in one place. That
turns "someone forgot a call site" from a silent defect into an impossible
state, and it is what makes adding a new transaction type a safe operation.

The vocabulary
--------------
``expense``          money leaving the household (a spend)
``income``           money entering the household
``transfer``         a leg of an account-to-account transfer pair
``savings_transfer`` a leg of a transfer into or out of a savings goal
``debt_payment``     a payment against a liability

The last three are balance-sheet movements between accounts the household
already owns. They move money around; they are not income and they are not
spend, so they never belong in a flow aggregate.

NULL handling
-------------
``transaction_type`` is ``NOT NULL`` with a default of ``'expense'`` (migration
M-006), so a NULL cannot occur on a current database. The filters below still
treat NULL as spend, matching the long-standing convention in ``budgets.py``
and ``chat.py``, so that every aggregate agrees on legacy rows if one is ever
restored from a pre-M-006 backup.
"""

from typing import Optional

from sqlalchemy import or_

# Types that count as household spending.
SPEND_TYPES = frozenset({"expense"})

# Types that count as household income.
INCOME_TYPES = frozenset({"income"})

# The whitelist: types that appear in income/expense aggregates at all.
FLOW_TYPES = SPEND_TYPES | INCOME_TYPES

# Balance-sheet movements — money the household moves between its own accounts.
# Never part of a flow aggregate. Listed explicitly so the vocabulary is
# documented in one place; the aggregates themselves whitelist FLOW_TYPES and
# so exclude these (and any future type) automatically.
BALANCE_SHEET_TYPES = frozenset({"transfer", "savings_transfer", "debt_payment"})

# Both transfer-pair leg types. Used by the Transactions page's display
# segments, which deliberately hide transfer legs without hiding anything else
# (see ``transactions._apply_tx_filters``).
TRANSFER_LEG_TYPES = frozenset({"transfer", "savings_transfer"})

# Every type the application writes. Kept so tests can assert that FLOW_TYPES
# and BALANCE_SHEET_TYPES stay an exact partition of the vocabulary — if a new
# type is added to one set and not the other, that test fails loudly.
ALL_TYPES = FLOW_TYPES | BALANCE_SHEET_TYPES


def flow_filter(column):
    """SQLAlchemy clause: rows that participate in income/expense aggregates."""
    return or_(column.in_(FLOW_TYPES), column.is_(None))


def spend_filter(column):
    """SQLAlchemy clause: rows that count as household spending."""
    return or_(column.in_(SPEND_TYPES), column.is_(None))


def is_flow(transaction_type: Optional[str]) -> bool:
    """Python-side equivalent of :func:`flow_filter`, for in-memory filtering."""
    return transaction_type is None or transaction_type in FLOW_TYPES


def is_spend(transaction_type: Optional[str]) -> bool:
    """Python-side equivalent of :func:`spend_filter`."""
    return transaction_type is None or transaction_type in SPEND_TYPES
