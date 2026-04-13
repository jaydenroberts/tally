# Getting Started

This guide walks you through deploying Tally for the first time — from pulling the Docker image to completing initial setup. The whole process takes around five minutes.

---

## Prerequisites

- A host running Docker (Unraid, TrueNAS, a Linux server, or any machine with Docker installed)
- A terminal or Unraid Docker UI access
- Port 8092 available on your host (or a port of your choosing)
- A directory on your host for persistent data (e.g. `/mnt/user/appdata/tally`)
- Optionally: a directory containing your bank statement files (CSV or PDF)

---

## Installation

### Option 1 — Docker Run

```bash
docker run -d \
  --name tally \
  -p 8092:8091 \
  -v /mnt/user/appdata/tally:/data \
  -v /mnt/user/financial-data:/financial-data:ro \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  -e FIRST_RUN_OWNER_USERNAME=admin \
  -e FIRST_RUN_OWNER_PASSWORD=changeme \
  --restart unless-stopped \
  jaydenroberts/tally:latest
```

Replace `/mnt/user/appdata/tally` with your actual data path and set a strong password.

### Option 2 — Docker Compose

Create a `docker-compose.yml` file:

```yaml
services:
  tally:
    image: jaydenroberts/tally:latest
    container_name: tally
    ports:
      - "8092:8091"
    volumes:
      - /mnt/user/appdata/tally:/data
      - /mnt/user/financial-data:/financial-data:ro
    environment:
      - SECRET_KEY=your-secret-key-here
      - FIRST_RUN_OWNER_USERNAME=admin
      - FIRST_RUN_OWNER_PASSWORD=changeme
    restart: unless-stopped
```

Then run:

```bash
docker compose up -d
```

### Option 3 — Unraid Community Applications

Search for **Tally** in the Unraid Community Applications store. Fill in the required fields (secret key, username, password, data path) and click **Apply**.

---

## Generating a Secret Key

The `SECRET_KEY` environment variable is required. It signs your JWT authentication tokens. Generate a secure value with:

```bash
openssl rand -hex 32
```

Store this value somewhere safe (e.g. a password manager). If you lose it, all existing sessions will be invalidated when you restart the container with a new key.

---

## First Login

1. Open your browser and navigate to `http://your-server-ip:8092`
2. If you set `FIRST_RUN_OWNER_USERNAME` and `FIRST_RUN_OWNER_PASSWORD`, the owner account is created automatically. Log in with those credentials.
3. If you did not set those variables, Tally will show a **Setup** screen on first visit. Enter your desired username and password to create the owner account.

**Note:** The setup endpoint is only available before any users exist. Once the owner account is created, the setup page is no longer accessible.

---

## After First Login

Once logged in, you will land on the **Dashboard**. It will be empty until you add accounts.

Recommended first steps:
1. Go to **Accounts** and add your bank accounts, credit cards, and savings accounts
2. Go to **Settings → General** to set your preferred currency symbol
3. Go to **Import** to bring in your first bank statement

---

## Data Persistence

All Tally data is stored in the `/data` volume. This includes:
- `tally.db` — the SQLite database containing all your financial data

Back up this directory regularly. Tally does not include built-in backup tooling.

---

## Related

- [Configuration](configuration.md) — full environment variable reference
- [Accounts](accounts.md) — adding your first accounts
- [Import](import.md) — importing bank statements
