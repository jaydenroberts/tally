# Debt

The Debt page tracks money you owe — credit card balances, personal loans, car loans, mortgages, buy-now-pay-later accounts, and anything else. Each debt tracks its balance, interest details, payment history, and projects a payoff date.

---

## Debt Types

When adding a debt, select the type that matches your account:

| Type | Description |
|------|-------------|
| Credit Card | Revolving credit — includes standard and balance transfer cards |
| Personal Loan | Fixed-term unsecured loan |
| Car Loan | Vehicle finance |
| Mortgage | Home loan |
| BNPL | Buy now pay later (e.g. Afterpay, Zip) |
| Other | Anything that doesn't fit the above |

---

## Adding a Debt

1. Click **Add Debt**
2. Enter a name (e.g. "Visa Card", "Car Loan")
3. Select the debt type
4. Enter the current balance (amount owed)
5. Enter the interest rate (annual percentage rate)
6. Optionally set an **interest-free end date** (for 0% balance transfer cards or BNPL)
7. Select a **paydown strategy**: Avalanche, Snowball, or Fixed
8. Click **Save**

**Note:** Only owners can create, edit, or delete debts.

---

## Interest-Free Period Warnings

If a debt has an interest-free end date set:

- A warning banner appears on the debt card as the end date approaches
- The warning colour escalates as the date gets closer (orange → red)
- After the end date passes, the debt is treated as a standard interest-bearing debt in payoff projections

Use this for 0% balance transfer cards and BNPL accounts so you don't miss the interest-free cutoff.

---

## Paydown Strategies

| Strategy | Description |
|----------|-------------|
| Avalanche | Pay minimums on all debts, put extra funds toward the highest-interest debt first. Minimises total interest paid. |
| Snowball | Pay minimums on all debts, put extra funds toward the smallest balance first. Builds momentum. |
| Fixed | Fixed payment amount each period regardless of balance. |

The strategy is recorded for reference and affects how payoff projections are calculated.

---

## Payoff Projections

Each debt card shows a projected payoff date based on your payment history and strategy:

- **Interest-free phase** — if an interest-free end date is set and it hasn't passed, the projection uses a 0% rate for that period
- **Standard phase** — after the interest-free period ends (or immediately if no interest-free date is set), the projection uses full amortization based on your interest rate and payment amounts

The projection updates each time you log a payment.

---

## Logging a Payment

To record a payment toward a debt:

1. Click **Log Payment** on the debt card
2. Enter the payment amount and date
3. Optionally add a note
4. Optionally select a **source account** — the account the payment came from

If you select a source account, Tally creates a linked debit transaction on that account automatically. You do not need to enter the transaction separately.

5. Click **Save**

The debt balance decreases by the payment amount.

---

## Payment History

Click the **⏱** (clock) icon on a debt card to view the full payment history. The history table shows each payment with its date, amount, note, and whether it is linked to a transaction.

---

## Linking Payments to Existing Transactions

If you have already entered a transaction that represents a debt payment and want to link it to a debt:

1. Go to **Transactions** and find the transaction
2. Click the **⛓ Link Debt** button on the transaction row
3. Select the debt to link it to

Linking automatically:
- Reduces the debt balance
- Creates a payment audit record
- Sets the transaction category to "Debt Payment"
- Displays a purple **Debt** badge on the transaction

To unlink, click the **✂ Unlink** button on the transaction row. The debt balance is restored.

---

## Debt Badges on Transactions

Linked transactions display a purple **Debt** badge showing the name of the debt. On the Transactions page, this lets you quickly see which payments are accounted for in your debt tracker.

---

## Editing and Deleting Debts

Click the edit icon on a debt card to update the name, balance, interest rate, end date, or strategy. Click the delete icon and confirm to remove a debt. Deleting a debt does not delete any transactions linked to it.

---

## Related

- [Transactions](transactions.md) — linking transactions to debt payments
- [Accounts](accounts.md) — the source accounts payments come from
- [Budgets](budgets.md) — debt payments are excluded from budget calculations
