"""
routers/chat.py — AI chat endpoint for Tally.

POST /api/chat
    Accepts a list of messages and streams an SSE response using the
    configured AI provider (see providers.py).

Data access is scoped by the current user's persona:
    data_access_level == "full"     → transactions + accounts + budgets + categories
    data_access_level == "summary"  → aggregated summaries only (no raw transactions)
    data_access_level == "readonly" → same as full but read-only (family view)

Write tools (update_transaction, add_transaction, add_savings_contribution,
add_debt_payment) are only included when persona.can_modify_data is True.

TODO: Chat history is ephemeral — each request is stateless. Revisit for
      persistent SQLite storage in a future phase so conversations survive
      page reloads and are scoped per user/persona.
"""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user
from ..providers import stream_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str   # "user" | "assistant" | "tool"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format — providers.py normalises
# to Anthropic format when needed)
# ---------------------------------------------------------------------------

READ_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_transactions",
            "description": (
                "Retrieve a list of transactions within the persona's data window. "
                "Returns date, description, amount, category, and verification status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of transactions to return (1-100). Default 50.",
                        "default": 50,
                    },
                    "category_name": {
                        "type": "string",
                        "description": "Filter by category name (case-insensitive, partial match).",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Start date filter (ISO 8601, e.g. '2025-01-01').",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "End date filter (ISO 8601).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_accounts",
            "description": "Return all active accounts with name, type, institution, and current balance.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_budget_summary",
            "description": (
                "Return budget vs spend for all active budgets in a given month. "
                "Includes verified spend, estimated spend, and status (healthy/warning/over)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "Year (e.g. 2025). Defaults to current year.",
                    },
                    "month": {
                        "type": "integer",
                        "description": "Month 1-12. Defaults to current month.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "Return all available spending categories (system + user-defined).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

WRITE_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "add_transaction",
            "description": "Add a new manual transaction to an account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "integer", "description": "Account to post the transaction against."},
                    "date": {"type": "string", "description": "Transaction date (ISO 8601, e.g. '2025-04-06')."},
                    "description": {"type": "string", "description": "Transaction description / payee name."},
                    "amount": {
                        "type": "number",
                        "description": "Amount. Negative for expenses/outflows, positive for income.",
                    },
                    "category_id": {"type": "integer", "description": "Category ID (optional)."},
                    "notes": {"type": "string", "description": "Optional notes."},
                },
                "required": ["account_id", "date", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_transaction",
            "description": (
                "Update fields on an existing manual (unverified) transaction. "
                "Imported (verified) transactions cannot be modified."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "integer", "description": "ID of the transaction to update."},
                    "date": {"type": "string", "description": "New date (ISO 8601)."},
                    "description": {"type": "string", "description": "New description."},
                    "amount": {"type": "number", "description": "New amount."},
                    "category_id": {"type": "integer", "description": "New category ID."},
                    "notes": {"type": "string", "description": "New notes."},
                },
                "required": ["transaction_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_savings_contribution",
            "description": "Log a contribution to a savings goal, increasing its current balance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "integer", "description": "Savings goal ID."},
                    "amount": {"type": "number", "description": "Contribution amount (positive)."},
                    "notes": {"type": "string", "description": "Optional notes."},
                },
                "required": ["goal_id", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_debt_payment",
            "description": "Log a payment against a debt, reducing its current balance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "debt_id": {"type": "integer", "description": "Debt ID."},
                    "amount": {"type": "number", "description": "Payment amount (positive)."},
                    "notes": {"type": "string", "description": "Optional notes."},
                },
                "required": ["debt_id", "amount"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    db: Session,
    current_user: models.User,
    persona: models.Persona,
    window_start: date,
) -> Any:
    """
    Execute a tool call against the database and return a JSON-serialisable result.
    Write tools are guarded by persona.can_modify_data; this check is belt-and-braces
    since the tool definitions themselves are not provided to the model when
    can_modify_data is False.
    """

    # ── Read tools ────────────────────────────────────────────────────────────

    if tool_name == "get_accounts":
        accounts = (
            db.query(models.Account)
            .filter(models.Account.is_active == True)
            .all()
        )
        return [
            {
                "id": a.id,
                "name": a.name,
                "type": a.account_type,
                "institution": a.institution,
                "balance": a.balance,
                "currency": a.currency,
            }
            for a in accounts
        ]

    if tool_name == "get_categories":
        cats = db.query(models.Category).filter(
            (models.Category.user_id == None) | (models.Category.user_id == current_user.id)
        ).all()
        return [{"id": c.id, "name": c.name, "color": c.color, "icon": c.icon} for c in cats]

    if tool_name == "get_transactions":
        limit = min(int(tool_input.get("limit", 50)), 100)
        q = (
            db.query(models.Transaction)
            .options(joinedload(models.Transaction.category))
            .filter(models.Transaction.date >= window_start)
        )
        if "date_from" in tool_input and tool_input["date_from"]:
            try:
                q = q.filter(models.Transaction.date >= date.fromisoformat(tool_input["date_from"]))
            except ValueError:
                pass
        if "date_to" in tool_input and tool_input["date_to"]:
            try:
                q = q.filter(models.Transaction.date <= date.fromisoformat(tool_input["date_to"]))
            except ValueError:
                pass
        if "category_name" in tool_input and tool_input["category_name"]:
            q = q.join(models.Category, isouter=True).filter(
                models.Category.name.ilike(f"%{tool_input['category_name']}%")
            )
        txs = q.order_by(models.Transaction.date.desc()).limit(limit).all()
        return [
            {
                "id": t.id,
                "account_id": t.account_id,
                "date": t.date.isoformat(),
                "description": t.description,
                "amount": t.amount,
                "category": t.category.name if t.category else None,
                "category_id": t.category_id,
                "is_verified": t.is_verified,
                "source": t.source,
                "notes": t.notes,
            }
            for t in txs
        ]

    if tool_name == "get_budget_summary":
        today = date.today()
        year  = int(tool_input.get("year",  today.year))
        month = int(tool_input.get("month", today.month))
        first_day = date(year, month, 1)
        last_day  = date(year, month, calendar.monthrange(year, month)[1])

        budgets = (
            db.query(models.Budget)
            .options(joinedload(models.Budget.category))
            .filter(
                models.Budget.is_active == True,
                models.Budget.start_date <= last_day,
                or_(models.Budget.end_date == None, models.Budget.end_date >= first_day),
            )
            .all()
        )
        result = []
        for budget in budgets:
            verified_raw = (
                db.query(func.sum(models.Transaction.amount))
                .filter(
                    models.Transaction.category_id == budget.category_id,
                    models.Transaction.date >= first_day,
                    models.Transaction.date <= last_day,
                    models.Transaction.is_verified == True,
                )
                .scalar()
            ) or 0.0
            estimated_raw = (
                db.query(func.sum(models.Transaction.amount))
                .filter(
                    models.Transaction.category_id == budget.category_id,
                    models.Transaction.date >= first_day,
                    models.Transaction.date <= last_day,
                    models.Transaction.is_verified == False,
                )
                .scalar()
            ) or 0.0
            verified_spend  = max(0.0, -verified_raw)
            estimated_spend = max(0.0, -estimated_raw)
            total_spend     = round(verified_spend + estimated_spend, 2)
            divisor = budget.amount if budget.amount > 0 else 1.0
            pct = round((total_spend / divisor) * 100, 1)
            if pct >= 90:
                status = "over"
            elif pct >= 75:
                status = "warning"
            else:
                status = "healthy"
            result.append({
                "category": budget.category.name if budget.category else None,
                "budget_amount": budget.amount,
                "period": budget.period,
                "verified_spend": round(verified_spend, 2),
                "estimated_spend": round(estimated_spend, 2),
                "total_spend": total_spend,
                "remaining": round(budget.amount - total_spend, 2),
                "pct_used": pct,
                "status": status,
            })
        return result

    # ── Write tools — gated by can_modify_data ────────────────────────────────

    if tool_name in ("add_transaction", "update_transaction", "add_savings_contribution", "add_debt_payment"):
        if not persona.can_modify_data:
            return {"error": "This persona does not have permission to modify data."}

    if tool_name == "add_transaction":
        account = db.query(models.Account).filter(
            models.Account.id == tool_input.get("account_id")
        ).first()
        if not account:
            return {"error": f"Account {tool_input.get('account_id')} not found."}
        try:
            tx_date = date.fromisoformat(tool_input["date"])
        except (KeyError, ValueError):
            return {"error": "Invalid or missing date. Use ISO 8601 format (YYYY-MM-DD)."}
        tx = models.Transaction(
            account_id=tool_input["account_id"],
            date=tx_date,
            description=tool_input.get("description", ""),
            amount=float(tool_input["amount"]),
            category_id=tool_input.get("category_id"),
            notes=tool_input.get("notes"),
            source="manual",
            is_verified=False,
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)
        return {"success": True, "transaction_id": tx.id, "amount": tx.amount, "date": tx.date.isoformat()}

    if tool_name == "update_transaction":
        tx_id = tool_input.get("transaction_id")
        tx = db.query(models.Transaction).filter(models.Transaction.id == tx_id).first()
        if not tx:
            return {"error": f"Transaction {tx_id} not found."}
        if tx.is_verified and tx.source == "import":
            return {"error": "Imported (verified) transactions cannot be edited."}
        updatable = {
            "date", "description", "amount", "category_id", "notes"
        }
        for field in updatable:
            if field in tool_input and tool_input[field] is not None:
                value = tool_input[field]
                if field == "date":
                    try:
                        value = date.fromisoformat(value)
                    except ValueError:
                        return {"error": f"Invalid date format: {value}"}
                setattr(tx, field, value)
        db.commit()
        db.refresh(tx)
        return {"success": True, "transaction_id": tx.id, "amount": tx.amount, "date": tx.date.isoformat()}

    if tool_name == "add_savings_contribution":
        goal_id = tool_input.get("goal_id")
        amount  = float(tool_input.get("amount", 0))
        if amount <= 0:
            return {"error": "Contribution amount must be positive."}
        goal = db.query(models.SavingsGoal).filter(models.SavingsGoal.id == goal_id).first()
        if not goal:
            return {"error": f"Savings goal {goal_id} not found."}
        if goal.is_completed:
            return {"error": "Goal is already completed."}
        new_amount = round(goal.current_amount + amount, 2)
        goal.current_amount = new_amount
        if new_amount >= goal.target_amount:
            goal.is_completed = True
        db.add(models.SavingsContribution(
            goal_id=goal_id,
            amount=amount,
            balance_after=new_amount,
            notes=tool_input.get("notes"),
        ))
        db.commit()
        return {
            "success": True,
            "goal_id": goal_id,
            "new_balance": new_amount,
            "is_completed": goal.is_completed,
        }

    if tool_name == "add_debt_payment":
        debt_id = tool_input.get("debt_id")
        amount  = float(tool_input.get("amount", 0))
        if amount <= 0:
            return {"error": "Payment amount must be positive."}
        debt = db.query(models.Debt).filter(models.Debt.id == debt_id).first()
        if not debt:
            return {"error": f"Debt {debt_id} not found."}
        if debt.is_paid_off:
            return {"error": "Debt is already paid off."}
        new_balance = round(max(0.0, debt.current_balance - amount), 2)
        debt.current_balance = new_balance
        if new_balance == 0:
            debt.is_paid_off = True
        db.add(models.DebtPayment(
            debt_id=debt_id,
            amount=amount,
            balance_after=new_balance,
            notes=tool_input.get("notes"),
        ))
        db.commit()
        return {
            "success": True,
            "debt_id": debt_id,
            "new_balance": new_balance,
            "is_paid_off": debt.is_paid_off,
        }

    return {"error": f"Unknown tool: {tool_name}"}


# ---------------------------------------------------------------------------
# Financial context builder
# ---------------------------------------------------------------------------

def _build_system_prompt(
    persona: models.Persona,
    window_start: date,
    db: Session,
    current_user: models.User,
) -> str:
    """
    Assemble the system prompt injected ahead of every conversation.
    Context depth depends on data_access_level.
    """
    today = date.today()
    access = persona.data_access_level   # "full" | "summary" | "readonly"
    lines: list[str] = []

    # Persona identity
    base_prompt = persona.system_prompt or (
        "You are a helpful household finance assistant for the Tally app."
    )
    lines.append(base_prompt)
    lines.append("")
    lines.append(f"Today's date: {today.isoformat()}")
    lines.append(f"Data window: {window_start.isoformat()} to {today.isoformat()} ({persona.data_window_days} days)")
    lines.append("")

    # Access-level-specific context
    if access in ("full", "readonly"):
        # Account balances
        accounts = (
            db.query(models.Account)
            .filter(models.Account.is_active == True)
            .all()
        )
        if accounts:
            lines.append("## Accounts")
            for a in accounts:
                lines.append(f"- {a.name} ({a.account_type or 'account'}): {a.currency} {a.balance:,.2f}")
            lines.append("")

        # Current month budget snapshot
        first_day = date(today.year, today.month, 1)
        last_day  = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        budgets = (
            db.query(models.Budget)
            .options(joinedload(models.Budget.category))
            .filter(
                models.Budget.is_active == True,
                models.Budget.start_date <= last_day,
                or_(models.Budget.end_date == None, models.Budget.end_date >= first_day),
            )
            .all()
        )
        if budgets:
            lines.append(f"## Budget snapshot — {today.strftime('%B %Y')}")
            for budget in budgets:
                spend_raw = (
                    db.query(func.sum(models.Transaction.amount))
                    .filter(
                        models.Transaction.category_id == budget.category_id,
                        models.Transaction.date >= first_day,
                        models.Transaction.date <= last_day,
                    )
                    .scalar()
                ) or 0.0
                spend = max(0.0, -spend_raw)
                pct = round((spend / budget.amount) * 100, 1) if budget.amount > 0 else 0.0
                cat_name = budget.category.name if budget.category else "Unknown"
                lines.append(f"- {cat_name}: spent {spend:,.2f} of {budget.amount:,.2f} ({pct}%)")
            lines.append("")

    elif access == "summary":
        # Summary: only totals, no individual transactions
        accounts = (
            db.query(models.Account)
            .filter(models.Account.is_active == True)
            .all()
        )
        total_balance = sum(a.balance for a in accounts)
        lines.append(f"## Summary")
        lines.append(f"- Total balance across {len(accounts)} account(s): {total_balance:,.2f}")

        # Spending total for current month
        first_day = date(today.year, today.month, 1)
        last_day  = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        spend_raw = (
            db.query(func.sum(models.Transaction.amount))
            .filter(
                models.Transaction.date >= first_day,
                models.Transaction.date <= last_day,
                models.Transaction.amount < 0,
            )
            .scalar()
        ) or 0.0
        lines.append(f"- Total spending this month: {abs(spend_raw):,.2f}")
        lines.append("")
        lines.append(
            "You have summary-only access. You cannot view individual transactions, "
            "account names, or detailed budget breakdowns."
        )
        lines.append("")

    # Capabilities notice
    if persona.can_modify_data:
        lines.append(
            "You may use the write tools (add_transaction, update_transaction, "
            "add_savings_contribution, add_debt_payment) to help the user manage their finances."
        )
    else:
        lines.append("You have read-only access. You cannot modify any data.")

    if persona.tone_notes:
        lines.append("")
        lines.append(f"Tone guidance: {persona.tone_notes}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

SENTINEL = "\x00TOOL:"


def _sse(event: str, data: str) -> str:
    """Format a single SSE message. Newlines in data are encoded per the SSE spec."""
    data_lines = '\n'.join(f'data: {line}' for line in data.split('\n'))
    return f"event: {event}\n{data_lines}\n\n"


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------

@router.post("")
async def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Stream an AI response to a conversation.

    The response is an SSE stream. Event types:
        delta      — text fragment (data: raw text)
        tool_call  — tool being invoked (data: JSON {name, input})
        tool_result — tool result injected into conversation (data: JSON)
        done       — stream complete (data: "[DONE]")
        error      — fatal error (data: message string)

    The client is responsible for accumulating delta events into the full
    assistant message. Each request is stateless — the full conversation
    history must be sent on every call.
    """
    # ── Persona check ─────────────────────────────────────────────────────────
    persona = current_user.persona
    if persona is None:
        raise HTTPException(
            status_code=400,
            detail="No persona assigned to this user. Assign a persona in Settings before using the chat.",
        )

    # Enforce family persona access constraints (belt-and-braces; persona model
    # fields are the authoritative source — not the name).
    # data_access_level == "summary" → family-style persona; no raw data access.
    window_start = date.today() - timedelta(days=persona.data_window_days)

    # Build tool list scoped to persona capabilities
    available_tools = list(READ_TOOLS)
    if persona.data_access_level == "summary":
        # summary access: no raw transaction/account/category tool access
        available_tools = []
    if persona.can_modify_data:
        available_tools = available_tools + list(WRITE_TOOLS)

    system_prompt = _build_system_prompt(persona, window_start, db, current_user)

    # Convert request messages to provider format
    messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    async def event_stream():
        # We may need to run multiple rounds if the model uses tools.
        # Each round appends the assistant's tool calls and tool results to
        # `messages`, then re-invokes the model.
        MAX_TOOL_ROUNDS = 6
        current_messages = list(messages)

        for _round in range(MAX_TOOL_ROUNDS + 1):
            if _round == MAX_TOOL_ROUNDS:
                yield _sse("error", "Maximum tool call depth reached.")
                break

            tool_calls_this_round: list[dict] = []
            assistant_text = ""

            async for chunk in stream_chat(
                messages=current_messages,
                tools=available_tools,
                system=system_prompt,
            ):
                if chunk.startswith(SENTINEL):
                    # Tool call sentinel
                    tool_data = json.loads(chunk[len(SENTINEL):])
                    tool_calls_this_round.append(tool_data)
                    yield _sse("tool_call", json.dumps({
                        "name": tool_data["name"],
                        "input": tool_data["input"],
                    }))
                else:
                    assistant_text += chunk
                    yield _sse("delta", chunk)

            if not tool_calls_this_round:
                # No tool calls — conversation turn complete
                break

            # Append the assistant's turn (including any tool calls) to history
            # then execute each tool and append results, then loop.
            if assistant_text:
                current_messages.append({"role": "assistant", "content": assistant_text})

            for tc in tool_calls_this_round:
                result = _execute_tool(
                    tool_name=tc["name"],
                    tool_input=tc["input"],
                    db=db,
                    current_user=current_user,
                    persona=persona,
                    window_start=window_start,
                )
                result_json = json.dumps(result)
                yield _sse("tool_result", json.dumps({"name": tc["name"], "result": result}))

                # Append tool result to conversation for next round
                current_messages.append({
                    "role": "tool",
                    "content": result_json,
                })

        yield _sse("done", "[DONE]")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
