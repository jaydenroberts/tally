# Transactions

The Transactions page is the core of Tally's data entry and review workflow. This is where you view your full transaction history, categorise spending, reconcile imported bank data, manage transfers between accounts, and link transactions to debts and savings goals.

---

## The Transaction List

Transactions are displayed in a paginated table with the following columns:

- **Date** — transaction date
- **Description** — the transaction description (from import or manual entry)
- **Account** — which account the transaction belongs to
- **Category** — spending category (clickable to edit inline — see below)
- **Amount** — positive for income/credits, negative for expenses/debits
- **Status** — Verified or Estimate badge
- **Actions** — row-level action buttons

---

## Verified vs Estimate

Every transaction in Tally is either **Verified** or an **Estimate**:

- **Estimate** (pink badge) — manually entered transactions. These represent what you expect or remember spending, before your bank statement confirms it.
- **Verified** (green badge) — transactions confirmed by a bank import. The import matching algorithm matched this transaction to a real bank record.

You cannot manually toggle the verified status. Verification happens automatically when you import a bank statement and the import algorithm matches a transaction.

When a match is found, the bank's amount overwrites the estimate amount, and the original estimated amount is preserved for reference.

---

## Filtering and Searching

Use the filter bar above the transaction list to narrow down what you see:

- **Account** — filter to one account
- **Category** — filter to one category
- **Status** — show only Verified, only Estimates, or all
- **Source** — show only manually entered, only imported, or all
- **Date range** — set a start and end date

Filters stack — you can combine multiple filters at once. Clearing a filter returns to the full list.

---

## Sorting

Click any of the following column headers to sort the list:

- **Date**
- **Account**
- **Amount**
- **Status**

Click once to sort ascending, click again to sort descending. An arrow indicator (↑/↓) shows the active sort direction. Changing the sort resets to page 1.

---

## Adding a Transaction

Click the **+ Expense** button (floating action button, bottom right) to add a new expense transaction manually.

Fill in:
- Date
- Description
- Account
- Category
- Amount (enter as a positive number — Tally stores expenses as negatives internally)

Click **Save** to add the transaction.

**Note:** Only owners can create, edit, or delete transactions.

---

## Adding a Transfer

Transfers move money between two of your accounts. They are excluded from budget calculations so they do not distort spending figures.

To add a transfer:
1. Click the **↔ Transfer** toggle on the floating action button (bottom right)
2. Select the **From** account and **To** account
3. Enter the date and amount
4. Click **Save**

A transfer creates two linked transactions — a debit on the From account and a credit on the To account. Both display a **↔ Transfer** badge. Deleting one side of a transfer does not delete the other.

### Linking two existing transactions as a transfer

If you import statements from two of your accounts, a payment between them arrives
twice: money out of one account and money in to the other. For example, paying your
credit card from your bank account shows as a debit on the bank statement and a credit
on the card statement. Tally cannot tell on its own that these are the same money
moving, so the credit is counted as income until you link them.

1. On the Transactions page, tick the checkbox on both transactions (they must be on
   the same page; use the account or date filters to bring them together).
2. Click **Link as transfer** in the bar above the list. The button only becomes active
   when the two are on different accounts, one is money out and the other money in, and
   neither is already linked to a debt, a savings goal or another transfer.
3. Check both rows in the confirmation box and click **Link as transfer**.

Both transactions then show a **Transfer** badge and stop counting as income or
spending. To undo it, open either transaction and click **Unlink transfer**: each one
goes back to income (money in) or expense (money out).

⚠️ Do not use this for a refund. A refund is money coming back for something you bought;
see [Income or expense](#income-or-expense) below.

---

## Income or expense

Every ordinary transaction is either **Income** or **Expense**. Imports and new entries
set this from the sign: money in is Income, money out is Expense.

The one case that needs you is a **refund**. A refund is money in, so Tally first files
it as Income. To have it reduce your spending instead:

1. Click the transaction to open it.
2. Under **Type**, click **Expense**.

The refund then reduces your spending, and the budget of its category, in the month the
refund arrived (not the month of the original purchase). Click **Income** to change it
back. Transactions linked to a debt, a savings goal or a transfer show no toggle: their
type follows the link, so remove the link first.

---

## Inline Category Editing

Click the category cell on any transaction row to edit the category without opening a form. A dropdown appears immediately. Select the new category and Tally saves the change in place.

Inline category editing works on all transactions, including imported and verified ones. (Other fields on verified transactions — amount, date, description, account — cannot be changed, as those are locked to the bank record.)

**Note:** Only owners can edit categories.

---

## Bulk Actions

Select multiple transactions using the checkboxes on the left of each row. Once one or more transactions are selected, the bulk action bar appears above the list.

Available bulk actions:

- **Set category** — apply the same category to all selected transactions. A confirmation strip shows the count before applying.
- **Delete** — permanently delete selected transactions. A confirmation modal appears. Errors (if any) are shown in the modal before deleting. Deleting a transaction that was linked to a debt or a savings goal reverses that link automatically — the debt balance or goal total is restored and the payment/contribution is removed. Deleting one side of a transfer leaves the other side intact.

Bulk category update uses parallel updates; if any individual update fails, the rest still apply and the failures are reported.

---

## Transaction Badges

Transactions can display additional badges beyond the Verified/Estimate status:

| Badge | Meaning |
|-------|---------|
| ↔ Transfer | Part of a linked transfer pair between two accounts |
| Savings (cyan) | Linked to a savings goal contribution or withdrawal |
| Debt (purple) | Linked to a debt payment record |

These badges appear in the actions column. Click the badge label to see which goal or debt the transaction is linked to.

---

## Linking a Transaction to a Debt Payment

If a transaction in your account represents a debt payment (e.g. a credit card payment or loan repayment):

1. Find the transaction in the list
2. Click the **⛓ Link Debt** button on the transaction row
3. Select the debt account to link it to

Linking reduces the debt balance, creates a payment audit record, and automatically assigns the "Debt Payment" category. The transaction displays a purple **Debt** badge.

To unlink: click the **✂ Unlink** button on the same row.

---

## Linking a Transaction to a Savings Goal

If a transaction represents money going into savings:

1. Find the transaction in the list (it should be a positive/credit transaction)
2. Click the **⬡ Link Savings** button on the transaction row
3. In the modal, enter how much to allocate to each savings goal
4. Click **Allocate**

You can split a single transaction across multiple goals. Partial allocation is allowed — you do not need to allocate the full amount. The transaction displays a cyan **Savings** badge.

To link a debit transaction to a savings withdrawal, use the **⬡ Savings Withdrawal** button instead.

---

## Unlinking Transactions

Any linked transaction (debt, savings, or transfer) has an **✂ Unlink** button. Clicking it reverses the link:

- Unlink from debt — reverses the payment record and restores the debt balance
- Unlink from savings — removes the contribution record
- Unlink from transfer — breaks the transfer pair (both transactions remain, but are no longer linked)

---

## Pagination

The transaction list is paginated. Use the pagination controls at the bottom to move between pages. Filters and sort order are preserved across page changes.

---

## Import Reconciliation Banner

After importing a bank statement, a banner appears at the top of the Transactions page summarising the import results — how many transactions were matched, how many were new, and whether any amounts differed significantly. See [Import](import.md) for details.

---

## Related

- [Import](import.md) — bringing in bank statement data
- [Accounts](accounts.md) — account management
- [Budgets](budgets.md) — budget tracking by category
- [Savings](savings.md) — savings goal management
- [Debt](debt.md) — debt payment tracking
