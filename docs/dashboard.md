# Dashboard

The Dashboard is the first page you see after logging in. It provides a snapshot of your current financial position — account balances, a summary of where you stand, and your most recent transactions.

---

## Overview Panel

The top section of the Dashboard shows your overall balance summary:

- **Account balances** — the sum of all active account balances. Credit card balances are negative (money owed), bank and savings balances are positive.
  These are the balances you typed in on the **Accounts** page. Importing or adding
  transactions does **not** change them, so update an account's balance by hand when you
  want this figure to be current. A balance worked out from your transactions is planned
  for a later release. The figure under it is this month's income minus spending.
- **Individual account balances** — each account is listed with its current balance and account type.

Balances are shown in the currency you configured in **Settings → General**. The currency symbol is applied globally; Tally does not do currency conversion.

---

## Accounts Table

Below the summary, the Dashboard shows a table of all your active accounts. Each row displays:

- Account name
- Account type (bank, credit card, savings, investment, or other)
- Current balance

Click any account name to go to the **Accounts** page filtered to that account.

---

## Recent Transactions

The bottom section shows your most recent transactions across all accounts. Each row includes:

- Date
- Description
- Account
- Category
- Amount
- Status badge — **Verified** (green) for transactions confirmed by a bank import, or **Estimate** (pink) for manually entered transactions not yet confirmed

This panel shows a fixed number of recent entries. To see the full transaction history with filtering and search, go to the **Transactions** page.

---

## Monthly Net Cash Flow

The Dashboard shows a **Monthly net cash flow** chart — income minus spending for
each month, using the same exclusion rules as the rest of the app (transfers, debt
payments, and savings transfers are not counted as income or expense).

A range selector lets you switch the window shown between **1M**, **3M**, **6M**, and
**12M**. A full net-worth trend over time is planned for a later release.

---

## Budget Progress

The **This month** card shows **Budget used** — this month's total spending as a
percentage of your combined monthly budget limits — with the amount spent against those
limits and the days left in the month underneath. Total spending includes categories that
have no budget.

Next to the accounts table (below it on a narrow screen), a **Budget progress** card lists
each category with a monthly budget, with its own progress bar. A category that passes its limit also appears under **Needs your
attention** near the top of the page, with a link to **Budgets**.

Both use the same rule as the [Budgets](budgets.md) page: only expense transactions count,
and a refund — money in, typed as an **Expense** — reduces the figure instead of being
counted as separate income.

---

## Status Badges

Tally uses a colour-coded badge system throughout the UI:

| Badge | Colour | Meaning |
|-------|--------|---------|
| Verified | Green | Transaction matched and confirmed by a bank import |
| Estimate | Pink | Manually entered; not yet confirmed by import |
| Savings | Cyan | Transaction linked to a savings goal contribution or withdrawal |
| Debt | Purple | Transaction linked to a debt payment |
| Transfer | Cyan arrow | Transaction is one side of an account transfer |

---

## What the Dashboard Does Not Show

The Dashboard is intentionally minimal. Beyond the budget summary above, it does not show:

- Savings goal progress (see [Savings](savings.md))
- Debt balances (see [Debt](debt.md))
- AI coaching (see [AI Coach](ai-coach.md))

Use the sidebar navigation to access each feature area.

---

## Related

- [Accounts](accounts.md) — managing your accounts
- [Transactions](transactions.md) — full transaction history and filtering
- [Budgets](budgets.md) — budget tracking by category
