# Tally

A self-hosted personal finance web application for households. Track accounts, transactions, budgets, savings goals, and debt — all in one place, on your own infrastructure.

![License](https://img.shields.io/badge/license-MIT-green)

---

> ### ⚠️ Security: single-tenant only
>
> Tally is designed for a **single household you fully trust**. Authentication
> gates access to the app, but the data layer is **not user-scoped**: any
> authenticated user (owner *or* viewer) can read all accounts, transactions,
> budgets, debts, and savings in the instance. Roles limit *actions*, not *data
> visibility*.
>
> **Do not expose Tally as a shared multi-user service** to people who should not
> see each other's finances, and do not put it on the public internet. Run it on
> your LAN or behind a private tunnel/VPN. Per-user data isolation is tracked as a
> future enhancement.
>
> Cross-origin browser access is additionally restricted to an explicit allow-list
> (`ALLOWED_ORIGINS`), and the login and password-recovery endpoints are
> rate-limited per IP. See [Configuration](docs/configuration.md).

---

## Features

- **Multi-user** with configurable roles (Owner / Viewer by default)
- **Transaction tracking** — verified/unverified status, sortable columns, inline category editing, bulk category update
- **Transfers** — record money moving between accounts; excluded from budget calculations
- **Budgets** by category and period (transfers and debt payments excluded)
- **Savings goals** — allocate income across goals in one step; link withdrawals back to the goal
- **Debt tracking** — interest rate, minimum payment, paydown strategy badges; link expense transactions directly to a debt
- **Closed account lifecycle** — mark accounts as closed rather than deleting them
- **CSV/PDF import** from your existing financial files (read-only access)
- **AI chat interface** — ask questions about your finances in plain language; powered by Anthropic, OpenAI, or any OpenAI-compatible endpoint (e.g. Ollama); persona system controls data access and write permissions
- **Mobile navigation** — slide-in drawer on small screens
- **Dracula-inspired UI** with custom logo and favicon
- Single Docker container — easy self-hosting

---

## Installation

### Option 1 — Docker run (quick start)

> **Warning:** Tally runs as a **non-root** user inside the container. The host
> directory you mount at `/data` must be **writable by that user**, or Tally will
> fail to create its database on first start. On Unraid, `/mnt/user/appdata/...`
> is writable by default. On a plain Linux host, make the data directory
> writable by the container's user first (see [Getting Started](docs/getting-started.md)).

```bash
# Generate a secret key
SECRET_KEY=$(openssl rand -hex 32)

docker run -d \
  --name tally \
  --restart unless-stopped \
  -p 8091:8091 \
  -v /path/to/your/data:/data \
  -v /path/to/your/financial-files:/financial-data:ro \
  -e SECRET_KEY=$SECRET_KEY \
  -e FIRST_RUN_OWNER_USERNAME=admin \
  -e FIRST_RUN_OWNER_PASSWORD=changeme \
  jaydenroberts/tally:latest
```

Open `http://localhost:8091` — your owner account will be created automatically on first run.

### Option 2 — Docker Compose

Create a `docker-compose.yml`:

```yaml
services:
  tally:
    image: jaydenroberts/tally:latest
    container_name: tally
    restart: unless-stopped
    ports:
      - "8091:8091"
    volumes:
      - ./data:/data
      - ./financial-data:/financial-data:ro
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - ACCESS_TOKEN_EXPIRE_DAYS=30
      - FIRST_RUN_OWNER_USERNAME=${FIRST_RUN_OWNER_USERNAME}
      - FIRST_RUN_OWNER_PASSWORD=${FIRST_RUN_OWNER_PASSWORD}
```

Create a `.env` file alongside it:

```env
SECRET_KEY=         # generate with: openssl rand -hex 32
FIRST_RUN_OWNER_USERNAME=admin
FIRST_RUN_OWNER_PASSWORD=changeme
```

Then start:

```bash
docker compose up -d
```

### Option 3 — Unraid Community Applications

1. Open your Unraid web UI and go to the **Apps** tab.
2. Search for **Tally**.
3. Click **Install** and fill in the required fields (SECRET_KEY is mandatory — generate one with `openssl rand -hex 32`).
4. Click **Apply** and wait for the container to start.
5. Open `http://[your-unraid-ip]:8091`.

**Manual install via Docker tab (without CA):**

1. Go to the **Docker** tab in Unraid and click **Add Container**.
2. Set the repository to `jaydenroberts/tally:latest`.
3. Add a path: Container path `/data` → Host path `/mnt/user/appdata/tally/data` (Read/Write).
4. Add a path (optional): Container path `/financial-data` → Host path of your bank statement files (Read Only).
5. Add a variable: `SECRET_KEY` = your generated key.
6. Set port: Host `8091` → Container `8091`.
7. Click **Apply**.

---

## Configuration

All configuration is via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes | — | JWT signing secret. Generate with `openssl rand -hex 32`. Never reuse across installs. |
| `ACCESS_TOKEN_EXPIRE_DAYS` | No | `30` | How long login sessions last, in days. |
| `FIRST_RUN_OWNER_USERNAME` | No | — | Auto-creates the first owner account on startup. Leave blank to use the setup page instead. |
| `FIRST_RUN_OWNER_PASSWORD` | No | — | Required if `FIRST_RUN_OWNER_USERNAME` is set. |
| `DATABASE_URL` | No | `sqlite:////data/tally.db` | SQLite database path. Change only if you know what you're doing. |
| `FINANCIAL_DATA_PATH` | No | `/financial-data` | Container path where bank statement files are mounted. |
| `AI_PROVIDER` | No | — | AI provider to use for the chat feature: `anthropic`, `openai`, or `ollama` (any OpenAI-compatible endpoint). Leave unset to disable the chat page. |
| `AI_API_KEY` | No | — | API key for the selected provider. Not required for local Ollama. |
| `AI_MODEL` | No | — | Model name to use (e.g. `claude-sonnet-4-6`, `gpt-4o`, `llama3`). |
| `AI_BASE_URL` | No | — | Base URL override for OpenAI-compatible endpoints (e.g. `http://ollama:11434/v1`). Required for Ollama; not needed for Anthropic or OpenAI. |
| `ALLOWED_ORIGINS` | No | local origin | Comma-separated allow-list of origins permitted to call the API from a browser (CORS). Add your LAN/tunnel URL here if you access Tally from another hostname. |
| `AUTH_RATE_LIMIT_MAX` | No | `5` | Maximum login/password-recovery attempts per IP within the rate-limit window. |
| `AUTH_RATE_LIMIT_WINDOW_SECONDS` | No | `60` | Length of the auth rate-limit window, in seconds. |
| `MAX_UPLOAD_BYTES` | No | `10485760` | Maximum size (in bytes) of a statement file uploaded through the import wizard. Uploads over this limit are rejected. |
| `RECOVERY_TOKEN` | No | — | Enables the `POST /api/auth/recover` endpoint for owner password recovery. Use a token of at least 32 random characters (`openssl rand -hex 32`). Remove after use. |

---

## First-Run Setup

On first start, Tally checks whether any users exist. If none do, it enters setup mode.

**Automatic setup (via env vars):** If `FIRST_RUN_OWNER_USERNAME` and `FIRST_RUN_OWNER_PASSWORD` are set, the owner account is created silently at startup. No setup page is shown.

**Manual setup (via browser):** If those vars are not set, navigate to `http://[host]:8091` — you will be redirected to a setup page where you can create the first owner account. This endpoint is disabled once any user exists.

After setup, log in with your owner credentials. You can add viewer accounts, configure roles, and invite household members from the **Settings** page.

---

## Role System

Tally ships with two roles:

| Slug | Default Display Name | Permissions |
|---|---|---|
| `owner` | Owner | Full access: manage users, accounts, all data |
| `viewer` | Viewer | Read-only access to shared household data |

Display names are editable by any owner via the UI without affecting permissions logic.

---

## Documentation

Full documentation is available in the [`docs/`](docs/) directory:

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | First-run setup, logging in, adding accounts |
| [Configuration](docs/configuration.md) | All environment variables explained |
| [Dashboard](docs/dashboard.md) | Balance summary and recent transactions |
| [Accounts](docs/accounts.md) | Adding accounts, closed account lifecycle |
| [Transactions](docs/transactions.md) | Logging, importing, transfers, linking to savings/debt |
| [Budgets](docs/budgets.md) | Monthly category budgets and progress tracking |
| [Savings Goals](docs/savings.md) | Goal setup, contributions, bucket allocation |
| [Debt Tracker](docs/debt.md) | Debt tracking, payment logging, paydown strategies |
| [CSV & PDF Import](docs/import.md) | Importing bank statements, column mapping, reconciliation |
| [AI Coach](docs/ai-coach.md) | Chat interface, personas, data access levels |
| [Settings](docs/settings.md) | User management, personas, preferences |

---

## Development

### Prerequisites
- Python 3.11+
- Node.js 20+

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8091
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # proxies /api to port 8091
```

### Build & Run (Docker)

```bash
docker build -t tally .
docker run -p 8091:8091 -v $(pwd)/data:/data tally
```

---

## Financial File Import

Tally mounts your existing financial files **read-only**. It never modifies originals — it only reads them and imports transactions into its own SQLite database.

Mount your files at `/financial-data` (or configure `FINANCIAL_DATA_PATH`).

Supported formats: CSV (auto-detected column mapping), PDF bank statements (text extraction).

---

## License

MIT — see [LICENSE](LICENSE).
