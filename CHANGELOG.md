# Changelog

All notable changes to Tally are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and [Semantic Versioning](https://semver.org/).

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
- ING bank statement imports now correctly handle debit columns that are already stored as negative values, preventing double-negation of debit amounts.

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
