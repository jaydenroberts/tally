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
- **Dracula-inspired UI**
- Single Docker container — easy self-hosting

---

## Quick Start

### Docker (recommended)

```bash
docker run -d \
  --name tally \
  -p 8091:8091 \
  -v /path/to/your/data:/data \
  -v /path/to/your/financial-files:/financial-data:ro \
  -e SECRET_KEY=your-secret-key-here \
  ghcr.io/yourusername/tally:latest
```

Open `http://localhost:8091` and create your first owner account.

### Docker Compose

```bash
cp .env.example .env
# Edit .env with your values
docker compose up -d
```

---

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(required)* | JWT signing secret — use a long random string |
| `ACCESS_TOKEN_EXPIRE_DAYS` | `30` | JWT token lifetime in days |
| `DATABASE_URL` | `sqlite:////data/tally.db` | SQLite database path |
| `FINANCIAL_DATA_PATH` | `/financial-data` | Read-only path to your financial files |
| `FIRST_RUN_OWNER_USERNAME` | — | Auto-create owner on first run |
| `FIRST_RUN_OWNER_PASSWORD` | — | Auto-create owner on first run |

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
