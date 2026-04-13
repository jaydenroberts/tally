# Savings

The Savings page lets you track progress toward specific financial goals — an emergency fund, a holiday, a home deposit, or anything else you're saving for. Each goal tracks contributions, projects a completion date, and can be linked to actual account transactions.

---

## Savings Goals

Each savings goal has:

- **Name** — what you're saving for
- **Target amount** — the total you want to reach
- **Current balance** — how much has been saved so far
- **Deadline** (optional) — a target date to reach the goal
- **Linked account** (optional) — which account holds these funds

---

## Goal Cards

Each goal is displayed as a card showing:

- Goal name and target
- Progress bar (current balance vs target)
- Projected completion date (calculated from recent contribution pace)
- Current balance
- Days until deadline (if set)

---

## Adding a Savings Goal

1. Click **Add Goal**
2. Enter a name, target amount, and optional deadline
3. Optionally link to a savings account
4. Click **Save**

**Note:** Only owners can create, edit, or delete savings goals.

---

## Logging a Contribution

To manually record a contribution to a goal:

1. Click **Contribute** on the goal card
2. Enter the amount and date
3. Add an optional note
4. Click **Save**

The goal balance increases by the contribution amount. A contribution record is added to the audit trail.

---

## Contribution History

Click the **⏱** (clock) icon on a goal card to view the full contribution history. The history table shows each contribution with its date, amount, and note.

---

## Allocating from an Account

If you have a savings account linked to a goal (or multiple goals), you can allocate a credit transaction directly from the Transactions page.

When a credit transaction arrives in a savings account:
1. Go to **Transactions** and find the transaction
2. Click the **⬡ Link Savings** button on that row
3. In the **Allocate to Goals** modal, enter how much to allocate to each goal
4. Click **Allocate**

You can split one transaction across multiple goals. Partial allocation is allowed — you don't have to allocate the full amount.

The transaction is marked with a cyan **Savings** badge. Each goal's balance increases by the amount allocated to it.

---

## Withdrawals

When you spend from a savings goal (e.g. you've reached your holiday fund and book the trip):

1. Go to **Transactions** and find the debit transaction that represents the spend
2. Click the **⬡ Savings Withdrawal** button on that row
3. Select the goal this withdrawal is coming from
4. Click **Link**

The goal balance decreases by the withdrawal amount. The transaction is marked with a cyan **Savings** badge.

Alternatively, you can record a withdrawal directly from the Savings page using the withdraw action on a goal card.

---

## Projections

Tally calculates a projected completion date for each goal based on your average contribution rate. If you have set a deadline:

- If you are on track to meet it, the projection is shown in green
- If the projected date is after your deadline, it is shown in red

Projections are estimates based on past behaviour and are updated each time you view the page.

---

## Editing and Deleting Goals

Click the edit icon on a goal card to update the name, target, deadline, or linked account. Click the delete icon and confirm to remove a goal. Deleting a goal does not delete any transactions linked to it.

---

## Related

- [Transactions](transactions.md) — linking transactions to savings goals
- [Accounts](accounts.md) — the savings accounts your goals are connected to
- [Dashboard](dashboard.md) — overall financial position
