# Tally Documentation

Tally is a self-hosted personal finance web application for households. It runs as a single Docker container and gives you full control of your financial data — no third-party services, no subscriptions, no data leaving your server.

This documentation covers Tally v1.2.0.

---

## What Tally Does

- Tracks bank accounts, credit cards, savings, and debt in one place
- Imports bank statements from CSV and PDF files
- Reconciles imported transactions against manually entered estimates
- Tracks budgets by category with verified and estimated spend
- Manages savings goals with contributions, allocations, and projections
- Tracks debts with payment logging, payoff projections, and interest-free period warnings
- Provides an AI financial coaching interface powered by configurable personas
- Supports multiple users with owner and viewer roles

---

## Documentation Index

| Document | What it covers |
|----------|----------------|
| [Getting Started](getting-started.md) | Prerequisites, Docker install, first login, setup wizard |
| [Configuration](configuration.md) | Environment variables, volumes, ports reference |
| [Dashboard](dashboard.md) | What the dashboard shows and how to read it |
| [Accounts](accounts.md) | Adding accounts, account types, closing and reopening |
| [Transactions](transactions.md) | Viewing, filtering, categorising, inline edit, bulk actions, transfers, transaction linking |
| [Import](import.md) | CSV and PDF import, column mapping, reconciliation results |
| [Budgets](budgets.md) | Creating budgets, reading progress bars, month navigation |
| [Savings](savings.md) | Savings goals, contributions, account allocation, withdrawals, projections |
| [Debt](debt.md) | Debt tracker, payment logging, payment linkage, payoff projection |
| [AI Coach](ai-coach.md) | AI chat feature, personas, data access levels |
| [Settings](settings.md) | Profile, users, roles, personas, general preferences |

---

## Quick Start

1. Deploy Tally using the [Getting Started](getting-started.md) guide
2. Add your accounts in [Accounts](accounts.md)
3. Import your first bank statement via [Import](import.md)
4. Set up budgets in [Budgets](budgets.md)

---

## Version

This documentation covers **Tally v1.2.0**. Tally follows semantic versioning. Breaking changes will be noted in each document section where applicable.
