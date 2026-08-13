# Backup & Restore

Tally keeps every byte of your financial data on your own server. This page covers
how to get a copy of it out, and how to put it back.

Nothing on this page sends data anywhere. Every file described here is generated on
your server and downloaded straight to the device you are using.

---

## What Tally Does Automatically

Before Tally applies any change to your database during an upgrade, it saves a
complete snapshot first.

- **Where:** a `backups` folder inside your `/data` volume — the same directory as
  `tally.db`. On the host that is, for example, `/mnt/user/appdata/tally/backups`.
- **Named:** `pre-<version>.db`, e.g. `pre-1.4.4.1.db` — the version being upgraded
  *from*, so the file tells you what it can restore you to.
- **When:** on the first start after an upgrade. Ordinary restarts do not create a
  new snapshot, because the database has not changed version.
- **How many:** the five most recent are kept; older ones are deleted automatically.
  Change this with `BACKUP_KEEP`.

**If the snapshot cannot be written and verified, Tally will not start.** That is
deliberate. A container that refuses to start is a problem you can fix in a minute;
a migration that damages your financial history with no snapshot behind it is not.
If this happens you will see a line like this in the container logs:

```
ERROR:     [backup] PRE-MIGRATION BACKUP FAILED — Tally will not start.
```

The message says what went wrong. The usual causes are a full disk or a `/data`
directory the container cannot write to.

**Automatic snapshots are not an off-site backup.** They live on the same disk as
the database, so they protect you from a bad upgrade, not from a dead drive. Copy
the `/data` directory somewhere else on a schedule as well.

---

## Getting a Copy of Your Data

Go to **Settings → Data** (owner accounts only). There are three downloads.

| Download | File | Use it for |
|----------|------|------------|
| **Download backup** | `.db` | Restoring Tally. This is the only one you can restore from. |
| **Export all data (JSON)** | `.json` | Reading or transforming your data in another tool. |
| **Export transactions (CSV)** | `.csv` | Opening your transactions in a spreadsheet. |

Notes:

- The **backup** is a complete copy of the database, taken safely while Tally is
  running. You do not need to stop the container to download one.
- The **JSON export** contains every table, but password hashes are left out. It is
  a portability format, not a restore file.
- The **CSV export** contains one row per transaction with its category and account.
  Text fields that begin with `=`, `+`, `-` or `@` are written with a leading
  apostrophe so that a spreadsheet treats them as text rather than a formula.

---

## Restoring From a Backup

Restoring is a manual, deliberate procedure — Tally will never overwrite your live
database on its own.

You will need terminal access to the host running Tally.

> ⚠️ **This replaces your current data.** Everything recorded since the backup was
> taken will be gone. If the current database still opens, download a backup of it
> first (Settings → Data) so you can change your mind.

Throughout, replace `/mnt/user/appdata/tally` with the host directory you mounted at
`/data`, and `tally` with your container's name.

### Step 1 — Stop Tally

```bash
docker stop tally
```

Expected output:

```
tally
```

Nothing may write to the database file while you replace it, so this step is not
optional.

### Step 2 — Choose the backup file

List what you have:

```bash
ls -la /mnt/user/appdata/tally/backups
```

Expected output — one line per automatic snapshot:

```
-rw-r--r-- 1 999 999 274432 Aug 13 11:11 pre-1.4.4.1.db
```

If you are restoring a backup you downloaded from **Settings → Data** instead, copy
it onto the host first; it will be named something like
`tally-backup-20260813T111132Z.db`.

### Step 3 — Move the damaged database out of the way

Do not delete it. Rename it, so you can still get at it if the restore is not what
you expected.

```bash
cd /mnt/user/appdata/tally
mv tally.db tally.db.broken
mv tally.db-wal tally.db-wal.broken 2>/dev/null
mv tally.db-shm tally.db-shm.broken 2>/dev/null
```

The `-wal` and `-shm` files may not exist. The `2>/dev/null` simply hides the
"No such file" message if they do not.

⚠️ The `-wal` file holds recent changes that are not yet in the main file. Leaving
an old `-wal` next to a restored `tally.db` will corrupt it. Move all three.

### Step 4 — Put the backup in place

```bash
cp backups/pre-1.4.4.1.db tally.db
```

There is no output. Confirm it arrived:

```bash
ls -la tally.db
```

Expected output — a file of roughly the size you saw in step 2:

```
-rw-r--r-- 1 root root 274432 Aug 13 11:20 tally.db
```

### Step 5 — Make the file writable by Tally

⚠️ **This is the step most restores get wrong.** Tally runs as a non-root user
inside the container, so a file you copied as `root` will be read-only to it and the
container will fail to start with `attempt to write a readonly database`.

```bash
chown 999:999 tally.db
```

Expected output: none. If your host does not let you `chown`, this works too:

```bash
chmod 666 tally.db
```

### Step 6 — Start Tally

```bash
docker start tally
```

Expected output:

```
tally
```

Then check it came up:

```bash
docker logs --tail 20 tally
```

Expected output ends with:

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8091 (Press CTRL+C to quit)
```

### Step 7 — Confirm your data is back

Open Tally in your browser and log in. Your accounts and transactions should be
exactly as they were when the backup was taken.

Remember that your **password is also restored** — if you changed it after the
backup was taken, log in with the older one.

### Step 8 — Clean up

Once you are satisfied, remove the files you set aside in step 3:

```bash
rm /mnt/user/appdata/tally/tally.db.broken
rm /mnt/user/appdata/tally/tally.db-wal.broken
rm /mnt/user/appdata/tally/tally.db-shm.broken
```

---

## Checking a Backup Without Restoring It

You can confirm a snapshot is sound without touching your live install. On any
machine with `sqlite3` available:

```bash
sqlite3 pre-1.4.4.1.db "PRAGMA integrity_check; SELECT COUNT(*) FROM transactions;"
```

Expected output — `ok`, then your transaction count:

```
ok
2841
```

A backup you have never opened is not a backup. Doing this once, today, is worth
more than any amount of trust in the feature.

---

## Settings

All optional. See [Configuration](configuration.md) for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_DIR` | `backups` beside the database | Where automatic snapshots are written. |
| `BACKUP_KEEP` | `5` | How many automatic snapshots to keep. Minimum 1. |
| `PRE_MIGRATION_BACKUP` | `on` | Set to `off` to skip the automatic pre-upgrade snapshot. Only do this if you take your own snapshot before every upgrade. |

---

## Related

- [Configuration](configuration.md) — environment variables and volume mounts
- [Getting Started](getting-started.md) — install and first run
- [Settings](settings.md) — the Data tab and other settings
