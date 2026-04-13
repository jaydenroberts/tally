# Import

Tally can import bank statements directly from CSV and PDF files. Imported transactions are matched against any existing manual estimates using a reconciliation algorithm — confirmed matches are marked as Verified and the bank's exact amount is applied.

---

## Supported Formats

| Format | Notes |
|--------|-------|
| CSV | Most banks offer CSV export. Tally supports flexible column mapping. |
| PDF | Tally extracts transaction tables from PDF bank statements using PDF table detection. |

**Note:** PDF import works best with machine-generated PDFs from your bank's online portal. Scanned PDFs (images) are not supported.

---

## Where to Place Files

Place your bank statement files in the directory you mounted as `/financial-data` when deploying Tally. Tally reads this directory as read-only — it never modifies or deletes your original files.

Alternatively, you can upload files directly in the import UI without using the `/financial-data` directory.

---

## Starting an Import

1. Go to the **Transactions** page
2. Click the **Import** button
3. The import modal opens with three steps

---

## Step 1 — Select File and Account

- Choose a file from the list of files in your `/financial-data` directory, or upload a file directly
- Select which **account** these transactions belong to

Click **Next** to proceed.

---

## Step 2 — Map Columns

Tally needs to know which columns in your file correspond to date, description, and amount.

### CSV Column Mapping

For CSV files, enter the exact column header names from your file:

| Field | What to enter |
|-------|--------------|
| Date column | The header of the date column (e.g. `Date`, `Transaction Date`) |
| Description column | The header of the description column (e.g. `Description`, `Narrative`) |
| Amount column | For single amount column files: the header of the amount column |
| Credit column | For split files: the header of the credit (positive) column |
| Debit column | For split files: the header of the debit (negative) column |

**Split credit/debit columns:** Some banks (including ING) use separate columns for credits and debits rather than a single signed amount column. Select the split mode and map both columns. Tally handles both positive and already-negative debit values correctly.

### PDF Column Mapping

For PDF files, Tally previews the detected columns from the largest table in the document. Use the dropdowns to select which column maps to each field:

- Date
- Description
- Amount (or Credit and Debit if split)

Click **Import** to run the import.

---

## Step 3 — Reconciliation Results

After import, Tally displays a summary of what happened:

| Result | Meaning |
|--------|---------|
| Matched | An existing manual transaction was matched to this bank record and verified |
| New | No matching manual transaction was found; a new transaction was created |
| Amount difference | Match was made but the bank amount differed from your estimate by more than 15% |

The amount difference table lists any transactions where the bank amount differed significantly from your estimate, showing both figures so you can review them.

---

## How Reconciliation Works

When you import, Tally compares each bank record against your existing manual transactions on the same account:

- **Date tolerance:** ±3 days
- **Amount tolerance:** ≤15% difference, with a minimum of $1
- **Best fit:** When multiple candidates exist, Tally picks the closest amount, then the closest date

When a match is found:
- The bank amount overwrites the estimate amount
- The original estimated amount is saved for reference
- A match note is recorded
- The transaction is marked **Verified**
- Your category and notes are preserved (the bank record does not overwrite them)

Transactions that don't match any manual entry are created as new Verified transactions.

---

## Import History

Go to **Import History** (owner-only, accessible from the sidebar) to see a log of all previous imports. Each entry shows:

- Filename
- Format (CSV or PDF)
- Date and time of import
- Number of transactions processed
- Status (success or error)
- Error detail if the import failed

---

## Tips for Clean Imports

- Set your date range in the bank's export to overlap your last import slightly — the reconciliation algorithm will not create duplicates if a transaction was already imported
- Use consistent account selection — always import a file to the correct account
- Review the amount difference table after each import — large discrepancies usually indicate a mismatched estimate that needs correction

---

## Related

- [Transactions](transactions.md) — reviewing and categorising imported transactions
- [Accounts](accounts.md) — accounts that imported transactions are assigned to
