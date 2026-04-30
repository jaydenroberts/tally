# Accounts

The Accounts page is where you manage all the financial accounts Tally tracks — bank accounts, credit cards, savings accounts, and anything else you want to include. Every transaction in Tally belongs to an account.

---

## Account Types

When adding an account, choose the type that best matches what it is:

| Type | Description |
|------|-------------|
| Bank | Everyday transaction accounts, chequing accounts |
| Credit Card | Credit accounts — balances are negative (money owed) |
| Savings | Savings accounts and term deposits |
| Investment | Investment or brokerage accounts |
| Other | Anything that doesn't fit the above |

The type affects how balances are displayed and summarised on the Dashboard.

---

## Adding an Account

1. Click **Add Account** in the top right of the Accounts page
2. Enter an account name (e.g. "Everyday Account", "Visa Credit Card")
3. Select the account type
4. Enter the current balance
5. Optionally enter a currency code (e.g. `AUD`, `USD`) — this is for reference only
6. Click **Save**

The account appears immediately in the account grid.

**Note:** Only owners can create, edit, or delete accounts. Viewer accounts can see accounts and balances but cannot make changes.

---

## Editing an Account

Click the edit icon on any account card to update the name, type, or balance. Changing the balance directly is an override — it does not create a transaction. Use this only for initial setup or corrections.

---

## Account Cards

Accounts are displayed as cards, grouped by type. Each card shows:

- Account name
- Account type
- Current balance (formatted in your configured currency)

---

## Closing an Account

When you no longer actively use an account but want to keep its transaction history, close it rather than deleting it.

To close an account:
1. Click the **Close** action on the account card
2. Confirm the action

Closed accounts are removed from the main card grid and from balance totals. They appear in a collapsible **Closed Accounts** section at the bottom of the page.

To reopen a closed account, expand the **Closed Accounts** section and click **Reopen** on the relevant account.

**Note:** Closing an account does not delete its transactions. All transaction history is preserved and still visible in the Transactions page.

---

## Soft Delete vs Close

Tally has two ways to remove an account from active use:

- **Close** — marks the account as closed. History is preserved. Account can be reopened. Use this for accounts you've genuinely closed at the bank.
- **Delete** — permanently removes the account. This is only available for accounts with no transactions. It cannot be undone.

In practice, use **Close** in almost all cases.

---

## Including Closed Accounts in Views

By default, closed accounts are hidden from the main grid and excluded from balance totals. The **Closed Accounts** section at the bottom of the Accounts page lets you review them.

In the Transactions page, you can still see transactions from closed accounts — they appear in the transaction list with their account name intact.

---

## Related

- [Transactions](transactions.md) — viewing and managing transactions per account
- [Import](import.md) — importing bank statements to an account
- [Dashboard](dashboard.md) — balance summary across all accounts
