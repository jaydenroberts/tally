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

Alternatively, you can upload a file directly in the import wizard without using the `/financial-data` directory. Uploaded files must be `.csv` or `.pdf` and are size-capped (default 10 MB, set by `MAX_UPLOAD_BYTES`); larger files are rejected.

---

## Starting an Import

1. Go to the **Transactions** page
2. Click the **Import** button
3. The import wizard opens as a guided flow: **choose account → upload → match columns → review → confirm**

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

**Split credit/debit columns:** Some banks use separate columns for credits and debits rather than a single signed amount column. Select the split mode and map both columns. Tally handles both positive and already-negative debit values correctly.

### PDF Column Mapping

For PDF files, Tally previews the detected columns from the largest table in the document. Use the dropdowns to select which column maps to each field:

- Date
- Description
- Amount (or Credit and Debit if split)

Click **Import** to run the import.

---

## Step 4 — Review

Before anything is committed, the review step shows what the import will do, with a
running count in the form **"X will reconcile · Y new"** — how many bank rows match
an existing estimate (and will verify it) versus how many will be added as new
transactions.

Rows where an estimate matches but the bank amount has drifted are surfaced here for
you to confirm. This includes **debt-payment estimates**: if you logged a payment as
an estimate and the imported bank amount differs, the row goes to Review, and
confirming it updates both the transaction and the linked debt balance to the bank's
figure.

## Step 5 — Confirmation Results

After you confirm, Tally displays a summary of what happened:

| Result | Meaning |
|--------|---------|
| Reconciled | An existing manual estimate was matched to this bank record and verified. The transaction adopts the bank statement's date (which may move it into the correct month); an undo restores the original date. |
| New | No matching estimate was found; a new verified transaction was created |
| Amount difference | A match was made but the bank amount differed from your estimate by more than 15% — shown for review |

The amount difference table lists any transactions where the bank amount differed significantly from your estimate, showing both figures so you can review them.

---

## How Reconciliation Works

When you import, Tally compares each bank record against your existing manual transactions on the same account:

- **Date tolerance:** ±3 days
- **Amount tolerance:** ≤15% difference, with a minimum of $1
- **Best fit:** When multiple candidates exist, Tally picks the closest amount, then the closest date

When a match is found:
- The bank amount overwrites the estimate amount
- The transaction adopts the bank statement's date (correcting the month if your estimate was dated differently)
- The original estimated amount and date are saved for reference, so an undo restores them
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

- Set your date range in the bank's export to overlap your last import slightly — re-importing rows that were already imported (or already reconciled to an estimate) will not create duplicates or double-count them
- Use consistent account selection — always import a file to the correct account
- Review the amount difference table after each import — large discrepancies usually indicate a mismatched estimate that needs correction

---

## Related

- [Transactions](transactions.md) — reviewing and categorising imported transactions
- [Accounts](accounts.md) — accounts that imported transactions are assigned to
