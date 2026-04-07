# Tally

A self-hosted personal finance web application for households. Track accounts, transactions, budgets, savings goals, and debt — all in one place, on your own infrastructure.

![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

- **Multi-user** with configurable roles (Owner / Viewer by default)
- **Transaction tracking** with verified/unverified status
- **Budgets** by category and period
- **Savings goals** with progress tracking
- **Debt tracking** with interest rate and minimum payment
- **CSV/PDF import** from your existing financial files (read-only access)
- **AI chat interface** — ask questions about your finances in plain language; powered by Anthropic, OpenAI, or any OpenAI-compatible endpoint (e.g. Ollama); persona system controls data access and write permissions
- **Dracula-inspired UI**
- Single Docker container — easy self-hosting

---

## Installation

### Option 1 — Docker run (quick start)

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
| `AI_MODEL` | No | — | Model name to use (e.g. `claude-3-5-sonnet-20241022`, `gpt-4o`, `llama3`). |
| `AI_BASE_URL` | No | — | Base URL override for OpenAI-compatible endpoints (e.g. `http://ollama:11434/v1`). Required for Ollama; not needed for Anthropic or OpenAI. |

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
