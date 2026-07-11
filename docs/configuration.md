# Configuration

Tally is configured through environment variables passed to the Docker container. This page covers all available variables, volume mounts, and port configuration.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | **Yes** | — | JWT signing key. Generate with `openssl rand -hex 32`. Required for authentication to work. |
| `ACCESS_TOKEN_EXPIRE_DAYS` | No | `30` | How long login sessions remain valid, in days. After expiry, users must log in again. |
| `DATABASE_URL` | No | `sqlite:////data/tally.db` | Full SQLite connection string. Only change this if you have a specific reason to move the database file. |
| `FINANCIAL_DATA_PATH` | No | `/financial-data` | Path inside the container where Tally looks for importable bank statement files. Should match your read-only volume mount. |
| `FIRST_RUN_OWNER_USERNAME` | No | — | If set, Tally auto-creates an owner account with this username on first startup. Has no effect if users already exist. |
| `FIRST_RUN_OWNER_PASSWORD` | No | — | Required if `FIRST_RUN_OWNER_USERNAME` is set. |
| `ALLOWED_ORIGINS` | No | local origin | Comma-separated allow-list of browser origins permitted to call the API (CORS). Defaults to the local origin; add your LAN or tunnel URL if you reach Tally from another hostname. |
| `AUTH_RATE_LIMIT_MAX` | No | `5` | Maximum login/password-recovery attempts per IP within the rate-limit window. |
| `AUTH_RATE_LIMIT_WINDOW_SECONDS` | No | `60` | Length of the auth rate-limit window, in seconds. |
| `MAX_UPLOAD_BYTES` | No | `10485760` | Maximum size (in bytes) of a statement file uploaded through the import wizard. Larger uploads are rejected. |
| `RECOVERY_TOKEN` | No | — | When set, activates the password recovery endpoint (`POST /api/auth/recover`). Remove after use. See [Account Recovery](settings.md#account-recovery). |

**Warning:** If you change `SECRET_KEY` after users have logged in, all existing sessions will be invalidated. Users will need to log in again.

---

## Volume Mounts

| Container path | Purpose | Recommended host path |
|----------------|---------|----------------------|
| `/data` | Persistent storage for the SQLite database | `/mnt/user/appdata/tally` |
| `/financial-data` | Read-only directory of bank statement files for import | `/mnt/user/financial-data` |

The `/financial-data` volume is optional. If you do not mount it, file-picker import will be unavailable, but you can still import by uploading files directly in the import UI.

**Note:** Mount `/financial-data` as read-only (`:ro`) — Tally never writes to this directory.

**Warning:** Tally runs as a **non-root** user inside the container. The host directory you mount at `/data` must be writable by that user, or Tally cannot create or open its database and the container will fail to start. On Unraid, `/mnt/user/appdata/` paths are writable by default; on a plain Linux host, make the data directory writable by the container user before starting.

---

## Ports

| Container port | Default host port | Description |
|----------------|-------------------|-------------|
| `8091` | `8092` | Tally web UI and API |

Map the container port `8091` to any available port on your host. The examples in this documentation use `8092` as the host port.

---

## Cross-Origin Access (CORS)

By default Tally only accepts browser API requests from the local origin. If you
open the UI from a different hostname — a LAN IP, a reverse-proxy domain, or a
tunnel URL — add that origin to `ALLOWED_ORIGINS` (comma-separated) so the browser
is allowed to talk to the API. Requests from origins not on the list are rejected.

Authentication uses a Bearer token rather than cookies, so credentialed
cross-origin requests are disabled.

---

## Token Expiry

The default session length is 30 days. After that, users are redirected to the login page. You can shorten or extend this with `ACCESS_TOKEN_EXPIRE_DAYS`.

For a personal single-user installation, a longer expiry (e.g. `90`) reduces login friction. For a shared household setup with viewer accounts, a shorter expiry may be appropriate.

---

## Database

Tally uses SQLite with WAL mode and foreign key enforcement enabled. The database file is created automatically on first startup at the path specified by `DATABASE_URL`.

Do not modify the database file directly while the container is running. Always stop the container before performing manual database operations.

---

## Persistent Data

Everything in the `/data` volume is your Tally data. Back up this directory regularly using your host's backup tooling (e.g. Unraid's built-in backup, rsync, or a scheduled script).

To migrate Tally to a new server: stop the container, copy the `/data` directory to the new host, and start the container there with the same environment variables.

---

## Related

- [Getting Started](getting-started.md) — Docker install and first login
- [Settings](settings.md) — in-app preferences and user management
