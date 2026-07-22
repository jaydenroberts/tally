# Changelog

All notable changes to Tally are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and [Semantic Versioning](https://semver.org/).

---

## [1.4.4.1] - 2026-07-21

Security-patch hotfix — dependency version bumps that close known vulnerabilities in third-party libraries. No application behaviour changes.

### Security

- **Updated the multipart form parser** to a release that bounds the number of headers it will accept per part, closing a denial-of-service weakness where a crafted upload could exhaust server resources.
- **Updated the JWT library** to a release with hardened algorithm handling, removing an algorithm-confusion risk on the authentication path.
- **Updated the HTTP client** used by the web app to a release that closes a header-injection flaw and a request-routing weakness that could have been used to reach unintended destinations.
- **Pinned an upper bound on the PDF text-extraction library** so imports always run against a known-good range rather than floating to an untested future release.
- Updated the frontend build tool (development-only) to a release that closes local file-read issues in its development server.

---

## [1.4.3] - 2026-07-11

Import feature release — debt-payment reconciliation, smarter matching for reference-only statement lines, and scheduled recurring generation.

### Added

- **Debt payments now reconcile on import.** An unverified debt-payment estimate is matched against the corresponding statement line just like ordinary spending. When the bank figure differs from your estimate, Tally asks you to confirm rather than changing it silently; confirming updates the transaction, the payment record, and the debt balance together so they always agree.
- **Reference-only statement lines match more often.** When a statement line and one of your estimates carry no recognisable merchant name but share the same receipt/reference number, Tally now treats them as a confident match instead of asking you to check it.
- **Recurring transactions now generate on a daily schedule, not only at startup.** A lightweight in-process timer wakes shortly after midnight (UTC) each day and creates any due recurring entries, so a long-running instance no longer needs a restart to catch up. No new dependencies and no external scheduler.

### Changed

- **The import review step now separates "will reconcile" from "new."** The summary and the import button show how many transactions will merge into ones you already have versus how many are genuinely new — updating live as you include or exclude rows.
- The statement-upload size cap is now configurable via `MAX_UPLOAD_BYTES` (default 10 MB).

### Fixed

- Reconciling a debt payment whose amount changed can no longer be silently auto-verified — it is always surfaced for confirmation, because it moves a debt balance.
- Undo is blocked (with a clear message) on an import that adjusted a debt balance from a confirmed payment, so a rollback can never leave the debt out of step.

---

## [1.4.2] - 2026-07-10

Correctness & security hardening release. No new features; a broad sweep of money-accuracy, AI-chat, dashboard, import, and security fixes from a full code audit.

### Security

- **CORS is now locked down** — cross-origin access is restricted to an explicit allow-list (`ALLOWED_ORIGINS`, default local origin) and credentialed CORS is disabled (auth is a Bearer token, not cookies).
- **Login and password-recovery endpoints are rate-limited** (per-IP, 5/min by default, configurable) to blunt brute-force. No new dependencies.
- **The container no longer runs as root**, and the build-only C compiler is removed from the final image.
- **Changing a password now invalidates existing sessions** — tokens carry a version stamp; a password change or recovery stops older tokens working.
- **Tally is single-tenant by design** — authenticated users can see all data; roles limit actions, not visibility. Do not expose it as a multi-user service (see README).

### Fixed — money accuracy

- **Deleting a transaction that paid down a debt or funded a savings goal now reverses that money** (debt balance / goal total restored, payment/contribution removed) — single and bulk deletes. Deleting one side of a transfer no longer strands the other.
- **Over-payments/withdrawals no longer inflate balances when undone** — only the amount actually applied is recorded, so link/unlink cancel out exactly.
- **Deleting a debt or savings goal that has history no longer errors**; linked transactions revert to ordinary entries.
- **Savings transfers and debt payments no longer distort income/expense totals** across the dashboard, budgets, and transactions pages.
- **Emptying a savings goal no longer marks it "complete" and locks it**; goal/debt completion status now updates both ways.

### Fixed — imports

- Signed debits written as "-48.56 Dr" or "(-48.56)" are no longer flipped to income.
- Rows with an unreadable amount or date are no longer imported as $0.00 — the import stops and lists them.
- Re-importing a statement no longer double-counts rows already reconciled to an estimate.
- A reconciled transaction now takes the bank statement's date (correct month); undo restores the original.
- Changing the column mapping no longer overwrites hand-edited rows; duplicate/exclude flags stay in sync.
- Committing re-checks duplicates and refuses an expired draft. Account-number detection ignores dates/years. Import timestamps carry an explicit UTC offset.

### Fixed — AI chat

- The chat no longer breaks itself when the assistant errors mid-reply (clean recovery, no leaked provider details).
- Summary-only personas can no longer be handed data-changing tools.
- The AI's budget figures and "over/warning" wording now match the rest of the app; AI-added income is recorded as income.
- A long tool-using task ends with a summary instead of a bare "maximum depth" error.

### Fixed — dashboard, recurring, budgets

- Dashboard net-worth history no longer double-counts a month; income/spend totals apply the shared exclusion rules.
- Recurring monthly/yearly entries no longer drift off month-end; reactivating a long-paused entry no longer backfills every missed period.
- Weekly/yearly budgets are pro-rated into the month view; "over" triggers above 100% (warning from 80%).
- Deleting a category that ever had a budget no longer returns an error.

### Fixed — UI

- Recurring/debt date badges and new-entry date defaults now use your local date (correct "Due today" and no saving to yesterday). Savings goal deadlines use the same local-date basis, so an "overdue"/on-time badge no longer flips a day early.
- Failed dashboard loads and import preview actions now show an error instead of hanging or silently failing; un-checking an import row to exclude it reliably sticks.
- The dashboard "Budget used" figure no longer shows "NaN%".

### Changed

- The dashboard trend graph is labelled "Monthly net cash flow" (its actual meaning), and its 1M/3M/6M/12M range selector now changes the window shown. A true net-worth trend is planned for a later release.

### Known limitation

- Dashboard net worth still sums raw balances across currencies (a mixed-currency flag is returned for the UI). Per-currency net worth is deferred.

---

## [1.4.1.1] - 2026-07-10

### Security

- **Fixed an unauthenticated path-traversal hole in the static file server.** The single-page-app fallback route served any file path it was handed without confirming the file lived inside the app's static directory, so a crafted request could read files outside it — including the application database. Requested paths are now resolved and confirmed to stay within the static root before being served; anything outside falls back to the app's index page.

### Fixed

- **The one-time import-deduplication cleanup no longer re-runs on every startup.** A maintenance step that removes exact duplicate imported transactions was running on each boot and could fail — or delete a transaction still referenced by a linked payment, saving contribution, or import review row. It now runs exactly once (guarded by a persisted marker) and always skips any transaction another record still points to, so startup can never crash on it and linked history is preserved.

---

## [1.4.1] - 2026-05-22

### Fixed

- **Import reconciliation now matches on the merchant, not just the amount.** Previously an imported bank row could validate an unrelated manual estimate that happened to fall within the date/amount window, overwriting it with the wrong figure. The matcher now compares a normalised merchant identity and assigns matches one-to-one, so it only auto-confirms a manual entry when the merchant, amount, and date all agree.

### Added

- **"Quick check" step in the import wizard.** When the importer finds a likely match it isn't fully sure of (for example a generic "Direct Debit" line), it now surfaces the bank row alongside the entry you already added and asks you to confirm before merging. Suggestions default to off, so nothing is ever merged without your say-so — anything you skip is simply added as a new transaction.

---

## [1.4.0] - 2026-05-20

### Added

- **Staged import wizard** — CSV/PDF import is now a guided flow: choose account → upload → match columns → review → confirm, with a 5-minute undo window after committing.
- **Reconciliation matcher** — manual entries are provisional estimates that give instant budget feedback; when a bank import matches one (±3 days, 15%/$1 tolerance, expense or income), it validates the estimate and marks it Verified, preserving your category and notes. Unmatched imported rows are added as verified transactions; near-duplicate imports are flagged for review. "Needs review" now means a manual entry not yet confirmed by an import.
- **Split credit/debit CSV auto-detection** — files with separate money-in / money-out columns are recognised by header and mapped automatically; a Balance column is never mistaken for the transaction amount.
- **Transaction pagination** — the Transactions list is paged (50 per page) with server-side totals, so the monthly stat cards and segment counts stay accurate across pages.
- **Transaction multi-select** — select-all and shift-click range selection, with single and bulk delete.
- **Local AI provider support** — chat works with Ollama and any OpenAI-compatible endpoint, fully on-prem, in addition to hosted providers.
- **PDF statement import** — multi-table picker with a generalised text fallback for statements that don't expose clean tables.
- **Australian timezone options** — added the full set of Australian timezones in Settings.

### Changed

- **Unified page headers** — all pages share a consistent header treatment and scroll behaviour.
- **Import timestamps are timezone-aware** — the undo countdown and import history now display correctly in any timezone.

### Fixed

- Import undo could be hidden in non-UTC timezones; the countdown now resolves correctly everywhere.
- Deleting transactions linked by imports or schedules no longer fails on a foreign-key constraint; import rollback now reliably removes everything it created and reverts any estimates it matched.
- Desktop Transactions list now scrolls fully and no longer reflows when switching filters.
- Mobile layout fixes across the dashboard, transactions, and budgets views.

### Security

- PDF-parsing dependencies updated to patched releases.

---

## [1.3.3] - 2026-04-30

### Security

- **Category IDOR in AI write tools** — `add_transaction` and `update_transaction` tool handlers now verify that the supplied `category_id` belongs to the current user or is a system category before use (Medium, F-CHAT-05).
- **Float validation on all API inputs** — all monetary and numeric fields across every Pydantic schema now reject NaN, Infinity, and -Infinity at the API boundary via `_check_finite` validators (Medium, F-CHAT-06).
- **Float sanitization on AI responses** — numeric values read from the database for AI tool responses and system prompt injection are now passed through `_sanitize_float()`, replacing corrupt floats with 0.0 before they reach the model (Medium, F-CHAT-06).
- **Per-tool call rate limiting** — individual AI tool invocations are now capped per chat stream (e.g. `get_transactions` max 3, `get_budget_summary` max 2) to prevent data enumeration via repeated calls with varying filters (Medium, F-CHAT-07).
- **Persona isolation invariant documented** — added security invariant comment confirming all financial data is scoped to `current_user.id` regardless of shared persona assignment (Medium, F-CHAT-08).

### Changed

- Replaced bank-specific institution names in code comments, UI placeholders, and documentation with generic descriptions.

---

## [1.3.0] - 2026-04-22

### Added

- **Category management UI** — new "Categories" tab in Settings (owner only). Add, rename (inline — Enter to commit, Escape to cancel), and delete user-defined categories. System categories shown as read-only. Deletion nulls out linked transactions and budgets rather than blocking.
- **Budget awareness in AI chat** — system prompt now includes a per-category budget vs. spend table (verified + estimated split) for the current month. Works with all data access levels.
- **AI multi-turn tool use** — chat endpoint now correctly handles multi-turn tool use for both Anthropic (content block format) and OpenAI/compatible providers (tool_calls + tool_call_id format). Previously tool follow-up calls failed with a stream error.
- **Three-tab transaction form** — Add Transaction FAB now has Expense / Income / Transfer tabs. Expense tab auto-negates (user enters positive value, sign applied on save). Income tab has a prominent description field and stores a positive amount with `transaction_type="income"`. Income transactions display a "+ Income" badge in the list.

### Changed

- AI model updated from `claude-3-5-sonnet-20241022` (deprecated April 2026) to `claude-sonnet-4-6`.

### Fixed

- NULL `transaction_type` rows now correctly included in budget spend calculations (affected manually created transactions prior to this release).
- Corrected AI API key fallback order — `AI_API_KEY` checked before `ANTHROPIC_API_KEY`.
- `docker-compose.yml` financial-data volume corrected to a generic relative path (`./financial-data`).
- M-002 migration retired — it contained a personal name string incompatible with public release; any install reaching v1.3.0 without M-002 having run should manually reset the analyst persona in Settings.

### Security

- **Category PATCH/DELETE** now enforce ownership — previously any authenticated user could modify or delete another user's custom categories (Critical, OWASP API3:2023).
- **AI write tools** now validate monetary amounts (rejects NaN, Infinity, values outside ±999,999,999.99) and enforce field length limits: description ≤ 500 chars, notes ≤ 2000 chars (High).
- **AI `category_name` filter** sanitized via `_sanitize_category_name()` before use in ILIKE query (High).
- **Persona `system_prompt` sandboxed** — an explicit `---` separator and framing sentence now precede user-configured persona content in the AI system prompt, making the authority boundary clear to the model (High).

---

## [1.2.0] - 2026-04-13

### Added

- **Savings bucket allocation** — allocate a credit transaction (e.g. a paycheck) across multiple savings goals in one step. A new allocate button appears on positive transactions, opening a modal where you specify how much goes to each goal. Contributions are linked back to the source transaction for a full audit trail.
- **Savings withdrawal linking** — when you spend from a savings goal, link the debit transaction to that goal so your savings balance and transaction history stay in sync.
- **Debt payment linkage** — link any expense transaction directly to a debt. Tally records the payment against the debt balance, creates a payment history entry, and auto-categorises the transaction as "Debt Payment". Unlink at any time to reverse.
- **Transfer workflow** — record money moving between your own accounts as a transfer (not an expense). The FAB on the Transactions page now has an Expense / Transfer toggle. Transfers create a matched debit-and-credit pair and are excluded from budget calculations.
- **Transfer pair linking** — link two existing transactions as a transfer pair after the fact, and unlink them if needed.
- **Transaction type badges** — transactions linked to a savings goal show a "Savings" badge; those linked to a debt show the debt name. Transfer transactions show a "↔ Transfer" badge.
- **Inline category editing** — click the category cell on any transaction row to change its category immediately, without opening an edit form. Works on imported and verified transactions.
- **Bulk category update** — select multiple transactions and set their category in one action from the bulk action bar. A confirmation strip shows how many rows will be updated before you apply.
- **Sortable transaction columns** — click Date, Account, Amount, or Status column headers to sort the transaction list. Sort direction toggles with each click and resets pagination.
- **Closed account status** — mark an account as closed instead of deleting it. Closed accounts are hidden by default and shown in a collapsible section; you can reopen them at any time.
- **Mobile navigation** — a hamburger menu and slide-in drawer replaces the sidebar on small screens. The desktop layout is unchanged.
- **Logo and favicon** — Tally now has a custom Dracula-themed logo (tally mark + dollar sign). The favicon and browser tab icon are set across all device sizes.
- **Admin account recovery** — if you are locked out of your owner account, set the `RECOVERY_TOKEN` environment variable and call `POST /api/auth/recover` to regain access. No email or SMTP setup required. Tally logs a warning at startup if a recovery token is configured, so you remember to remove it after use.
- **Full user documentation** — a complete `docs/` directory ships with this release, covering every feature: getting started, configuration, dashboard, accounts, transactions, budgets, savings goals, debt tracker, CSV/PDF import, AI coach, and settings.

### Changed

- Selecting a currency in Settings now updates all pages immediately without requiring a page reload.
- Budget spending totals now exclude transfers, debt payments, and savings transfers — only true expense transactions count against a budget.
- Import reconciliation now skips non-expense transactions, so transfers and debt payments are never incorrectly matched against imported bank statement lines.
- Savings goals and contribution history now reflect the latest data immediately after changes in Settings, without requiring a logout and login.

### Fixed

- PDF import now selects the largest table in the document by row count, rather than always using the first table. This fixes imports of multi-page PDFs where the first page contains an account summary rather than the transaction list.
- Deleting a transaction that was linked to a debt payment or savings contribution no longer fails with a database constraint error. The links are cleanly removed before deletion, for both single and bulk deletes.
- Bulk delete errors are now shown in the confirmation modal instead of being silently swallowed.
- The row actions column in the transaction list is now wide enough to display all available action buttons without them overlapping.
- The static file server now correctly serves favicons, manifests, and other root-level assets instead of returning the app shell for every non-API path.
- Bank statement imports now correctly handle debit columns that are already stored as negative values, preventing double-negation of debit amounts.

### Security

- **Admin account recovery** (`RECOVERY_TOKEN`) uses constant-time token comparison to prevent timing attacks. The endpoint returns 404 (not 401) when no recovery token is configured, avoiding endpoint enumeration.

---

## [1.1.5] - 2026-04-09

### Added
- Duplicate import detection: re-importing a file that has already been imported is now blocked, with a clear error message showing the original import date.
- Bulk transaction delete: select multiple transactions using the checkboxes in the transaction list and delete them all at once from the bulk action bar.

### Fixed
- Existing databases upgraded cleanly to remove any duplicate transactions that may have been created by earlier imports before duplicate detection was introduced.

---

## [1.1.4] - 2026-04-08

### Fixed
- Existing installs that were affected by the personal data issue introduced in v1.1.1 are now automatically cleaned up on startup. No manual action required.

---

## [1.1.3] - 2026-04-08

### Security
- Prompt injection: AI persona system prompts are now applied after the safety enforcement layer, not before — preventing a crafted system prompt from overriding access controls.
- SSE data leakage: raw tool call results are no longer streamed in chat events; only the AI's final formatted response is sent to the client.
- AI data reads are now scoped to the authenticated user only — the AI cannot read or reference data belonging to other users.
- AI data writes (when the persona allows them) now verify ownership before making any changes — preventing one user's AI session from modifying another user's data.

---

## [1.1.2] - 2026-04-07

### Fixed
- Database schema migrations now run automatically on container startup, so updating to a new version no longer requires any manual database steps.
- The built-in seed data no longer contains any personal financial information. The public Docker image ships with generic placeholder data only.

---

## [1.1.1] - 2026-04-07

### Security
- `SECRET_KEY` is now validated at startup: Tally will refuse to start if the key is missing, too short, or set to a known weak value. This prevents silent JWT vulnerabilities from misconfigured deployments.
- Chat input is now limited in length, preventing unusually large messages from being sent to the AI.

---

## [1.1.0] - 2026-04-07

### Added
- **AI financial coach** — a chat interface powered by the Claude API. Talk to your data in plain English: ask about your spending, get budget assessments, or explore what-if scenarios.
- **Personas** — owners can create multiple AI personas with different names, system prompts, tones, and data access levels. Assign a persona to each user from the Settings page.
- **Data access levels** — each persona is configured with one of three access levels: full (sees all transactions and history), summary (sees aggregate totals only), or readonly (no financial data, general coaching only).
- **Data write permission** — personas can optionally be allowed to add or modify transactions on your behalf during a chat session. Disabled by default.
- Streaming responses: the AI reply appears word-by-word as it is generated, rather than waiting for the full response.

---

## [1.0.0] - 2026-04-04

### Added
- Initial release of Tally — a self-hosted personal finance app for households, packaged as a single Docker container.
- **Dashboard** — at-a-glance balance summary across all accounts, account table, and recent transactions.
- **Accounts** — add and manage bank accounts, savings accounts, and credit accounts; soft-delete accounts you no longer use.
- **Transactions** — log expenses and income, assign categories, filter and search; verified (imported) vs. estimated (manual) transaction workflow.
- **Budgets** — create monthly category budgets with dual-segment progress bars showing confirmed vs. estimated spend; navigate by month.
- **Savings goals** — set a target amount and deadline; log contributions with optional notes; automatic projection to target date.
- **Debt tracker** — track debts with interest-free period warnings, two-phase payoff projections (0% → standard rate), payment logging with notes, and paydown strategy badges (avalanche, snowball, fixed).
- **Recurring transactions** — define transactions that repeat on a daily, weekly, fortnightly, monthly, or yearly schedule; Tally generates them automatically on startup.
- **CSV import** — import bank statement CSV files; Tally reconciles imports against existing manual transactions within a ±3 day / ≤15% amount window.
- **PDF import** — import PDF bank statements with a 3-step guided flow: file selection, column mapping, and reconciliation review.
- **Import history** — owners can view a full log of every import, including filename, date, transaction count, and any errors.
- **JWT authentication** — 30-day login sessions; configurable via environment variable.
- **Role-based access** — owner role for full control; viewer role for read-only access. Role display names are editable.
- **First-run setup** — set your first owner account via environment variables or the setup page on first visit.
- **Multi-currency display** — configure your preferred currency symbol in Settings; applies across all pages.
- **Dracula theme** — full official Dracula colour palette throughout the UI.
- **Settings** — tabbed interface covering profile (change password), user management, personas, and general preferences.
- Available on DockerHub as `jaydenroberts/tally:1.0.0` and via Unraid Community Applications.
