"""Local backup and snapshot helpers (RM-04).

Everything in this module writes to the local filesystem or hands bytes back to
the caller. Nothing here opens a network connection and nothing is ever
uploaded: the point of the feature is to make Tally's data-sovereignty claim
provable rather than aspirational.

Snapshots use SQLite's own ``VACUUM INTO``, which produces a fully consistent,
self-contained copy of the database from a live connection without stopping the
app. It is part of SQLite itself, so this adds no dependency.

The two rules that make a snapshot trustworthy, and which the rest of this
module exists to enforce:

1. **A snapshot only gets its final name once it has been verified.** Writes go
   to a hidden ``.part-*`` file, are flushed to disk, opened read-only, checked,
   and only then renamed into place. A truncated or corrupt copy can therefore
   never appear under a name that looks like a good backup.
2. **Rotation only ever runs after a new snapshot is safely in place**, never
   deletes the newest file, and never touches a file it did not create.
"""

import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

log = logging.getLogger("tally.backup")

# Snapshots taken automatically before startup migrations are named
# "pre-<version>.db". Rotation is scoped to exactly this prefix so it can never
# delete an operator's own file that happens to live in the same directory.
PRE_MIGRATION_PREFIX = "pre-"
SNAPSHOT_SUFFIX = ".db"
PARTIAL_MARKER = ".part-"

DEFAULT_KEEP = 5

# Tables whose row counts are compared between source and snapshot on the
# startup path. These are the money-bearing tables — if a snapshot agrees with
# the live database on all of them it is a usable restore point.
CENSUS_TABLES = (
    "users",
    "accounts",
    "categories",
    "transactions",
    "budgets",
    "savings_goals",
    "savings_contributions",
    "debts",
    "debt_payments",
    "recurring_transactions",
)

# A snapshot with no accounts and no transactions in it protects nothing, so the
# startup gate treats an empty database as "nothing to back up" rather than
# refusing to boot. These are the tables that decide "empty".
DATA_TABLES = ("accounts", "transactions", "debts", "savings_goals")


def ensure_log_visible() -> None:
    """Make this module's INFO lines show up in ``docker logs``.

    uvicorn configures its own loggers and leaves the root logger bare, so an
    app-level ``log.info`` goes nowhere. For most of Tally that is merely
    untidy; for a safety feature it is a real problem, because "did the backup
    actually run?" is the one question an operator will ask and the answer would
    otherwise be invisible. Only this logger is touched, and only when nobody
    has configured logging themselves.
    """
    if log.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s:     [backup] %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


class BackupError(RuntimeError):
    """A snapshot could not be created, or was created but failed verification.

    Raised rather than logged because callers on the startup path must treat a
    failed backup as a reason not to migrate.
    """


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def database_path(engine: Engine) -> Optional[Path]:
    """Filesystem path of the SQLite file behind ``engine``.

    Returns ``None`` for in-memory databases and for any non-SQLite URL — both
    are cases where a file snapshot is meaningless rather than failed.
    """
    if engine.url.get_backend_name() != "sqlite":
        return None
    name = engine.url.database
    if not name or name == ":memory:":
        return None
    return Path(name).resolve()


def backup_dir(engine: Engine) -> Optional[Path]:
    """Directory automatic snapshots are written to.

    ``BACKUP_DIR`` wins if set. Otherwise it is a ``backups/`` directory
    alongside the database file, which for the shipped defaults is
    ``/data/backups`` — inside the volume the operator already backs up.
    Returns ``None`` when there is no database file to snapshot.
    """
    configured = os.getenv("BACKUP_DIR", "").strip()
    if configured:
        return Path(configured)
    db_file = database_path(engine)
    if db_file is None:
        return None
    return db_file.parent / "backups"


def keep_count() -> int:
    """How many automatic snapshots to retain. Floor of 1 — rotation must never
    be configurable down to "delete everything"."""
    raw = os.getenv("BACKUP_KEEP", "").strip()
    if not raw:
        return DEFAULT_KEEP
    try:
        return max(1, int(raw))
    except ValueError:
        log.warning("BACKUP_KEEP=%r is not a number — using default of %d", raw, DEFAULT_KEEP)
        return DEFAULT_KEEP


def pre_migration_enabled() -> bool:
    """Whether the pre-migration backup gate is armed. On by default."""
    return os.getenv("PRE_MIGRATION_BACKUP", "on").strip().lower() not in {
        "off", "false", "0", "no", "disabled",
    }


def safe_version(version: str) -> str:
    """Reduce an app version to characters that are safe in a filename."""
    cleaned = "".join(c if (c.isalnum() or c in "._-") else "-" for c in version.strip())
    return cleaned.strip("-.") or "unknown"


def timestamp_slug(now: Optional[datetime] = None) -> str:
    """UTC timestamp for on-demand download filenames: 20260813T091500Z."""
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Census helpers
# ---------------------------------------------------------------------------

def _existing_tables(conn) -> set:
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type = 'table'")
    ).fetchall()
    return {r[0] for r in rows}


def census(db: Session, tables: Iterable[str] = CENSUS_TABLES) -> dict:
    """Row count per table, skipping tables that do not exist yet.

    Used as the expected result a snapshot must reproduce.
    """
    present = _existing_tables(db)
    counts = {}
    for table in tables:
        if table in present:
            counts[table] = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
    return counts


def _snapshot_census(sqlite_conn: sqlite3.Connection, tables: Iterable[str]) -> dict:
    rows = sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    present = {r[0] for r in rows}
    return {
        table: sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in tables
        if table in present
    }


def has_financial_data(db: Session) -> bool:
    """True when the database holds anything worth protecting.

    A brand-new install has empty tables; refusing to start it because a backup
    could not be written would block first-run for no benefit.
    """
    counts = census(db, DATA_TABLES)
    return any(count > 0 for count in counts.values())


# ---------------------------------------------------------------------------
# Snapshot creation
# ---------------------------------------------------------------------------

def _fsync_path(path: Path) -> None:
    """Flush a file's contents to the physical device."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    """Flush a directory entry so a rename survives power loss. Best effort —
    not every filesystem allows opening a directory."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def verify_snapshot(path: Path, expected_census: Optional[dict] = None) -> dict:
    """Open a snapshot read-only and prove it is usable. Returns its census.

    Checks, in order: the file exists and is non-empty; SQLite can open it and
    ``PRAGMA quick_check`` passes (this is what catches a truncated copy); the
    money-bearing tables are present; and — when ``expected_census`` is supplied
    — every row count matches the source exactly.

    ``expected_census`` is only meaningful when nothing can be writing to the
    source at the same time, which is true on the startup path and not true for
    an on-demand download. Callers who cannot guarantee that pass ``None`` and
    get the structural checks only.
    """
    path = Path(path)
    if not path.exists():
        raise BackupError(f"snapshot was not created at {path.name}")
    if path.stat().st_size == 0:
        raise BackupError(f"snapshot {path.name} is empty")

    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise BackupError(f"snapshot {path.name} could not be opened: {type(exc).__name__}") from exc

    try:
        result = conn.execute("PRAGMA quick_check(1)").fetchone()
        if not result or result[0] != "ok":
            raise BackupError(f"snapshot {path.name} failed SQLite integrity check")
        found = _snapshot_census(conn, CENSUS_TABLES)
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"snapshot {path.name} is not a readable database: {type(exc).__name__}") from exc
    finally:
        conn.close()

    if expected_census is not None:
        missing = set(expected_census) - set(found)
        if missing:
            raise BackupError(
                f"snapshot {path.name} is missing table(s): {', '.join(sorted(missing))}"
            )
        mismatched = [
            f"{table} ({found[table]} vs {expected_census[table]})"
            for table in expected_census
            if found[table] != expected_census[table]
        ]
        if mismatched:
            raise BackupError(
                f"snapshot {path.name} row counts do not match the database: "
                + ", ".join(mismatched)
            )

    return found


def sweep_partials(directory: Path) -> int:
    """Remove leftover ``.part-*`` files from a snapshot that was interrupted.

    A container killed mid-``VACUUM INTO`` leaves a partial file behind. It can
    never be mistaken for a backup (it never got the final name), but it does
    occupy disk, so clear it on the next attempt. Returns the number removed.
    """
    removed = 0
    try:
        candidates = list(directory.glob(f"*{PARTIAL_MARKER}*"))
    except OSError:
        return 0
    for stale in candidates:
        try:
            stale.unlink()
            removed += 1
        except OSError as exc:
            log.warning("Could not remove stale partial %s: %s", stale.name, type(exc).__name__)
    if removed:
        log.info("Removed %d leftover partial snapshot file(s)", removed)
    return removed


def create_snapshot(
    engine: Engine,
    dest: Path,
    expected_census: Optional[dict] = None,
) -> Path:
    """Write a verified SQLite snapshot to ``dest``, atomically.

    The copy is built under a temporary name, flushed, verified, and only then
    renamed into place, so ``dest`` either does not exist or is a good backup —
    there is no third state. Raises ``BackupError`` on any failure, having
    cleaned up the partial file.
    """
    dest = Path(dest)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(
            f"backup directory {dest.parent} could not be created: {exc.strerror or exc}"
        ) from exc

    # VACUUM INTO refuses to overwrite an existing file, so the temp name must
    # be unique per attempt (pid + random, in case two processes race).
    tmp = dest.parent / f".{dest.name}{PARTIAL_MARKER}{os.getpid()}-{uuid.uuid4().hex[:8]}"

    try:
        # VACUUM cannot run inside a transaction, hence AUTOCOMMIT. The path is
        # bound as a parameter rather than interpolated so a directory name with
        # a quote in it cannot break the statement.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql("VACUUM INTO ?", (str(tmp),))
        _fsync_path(tmp)
        verify_snapshot(tmp, expected_census)
        os.replace(tmp, dest)
        _fsync_dir(dest.parent)
    except BackupError:
        _discard(tmp)
        raise
    except OSError as exc:
        _discard(tmp)
        raise BackupError(
            f"snapshot could not be written to {dest.parent}: {type(exc).__name__}: {exc.strerror or exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — any driver error means no backup
        _discard(tmp)
        raise BackupError(f"snapshot failed: {type(exc).__name__}") from exc

    return dest


def _discard(tmp: Path) -> None:
    """Delete a partial snapshot, never raising — the caller is already
    reporting a more important failure."""
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass


def rotate_snapshots(directory: Path, keep: int, prefix: str = PRE_MIGRATION_PREFIX) -> int:
    """Delete the oldest automatic snapshots beyond ``keep``. Returns how many
    were removed.

    Only files this module creates (``<prefix>*.db``) are considered, the newest
    ``keep`` are always retained (minimum 1), and a failure to delete is logged
    rather than raised: rotation is housekeeping, and a full disk with too many
    old backups is a better outcome than a boot failure.
    """
    keep = max(1, keep)
    try:
        snapshots = [
            p for p in directory.glob(f"{prefix}*{SNAPSHOT_SUFFIX}")
            if p.is_file() and PARTIAL_MARKER not in p.name
        ]
    except OSError as exc:
        log.warning("Could not list %s for rotation: %s", directory, type(exc).__name__)
        return 0

    if len(snapshots) <= keep:
        return 0

    # Newest first by modification time, with the name as a stable tiebreak.
    snapshots.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    removed = 0
    for stale in snapshots[keep:]:
        try:
            stale.unlink()
            removed += 1
            log.info("Rotated out old snapshot %s", stale.name)
        except OSError as exc:
            log.warning("Could not rotate out %s: %s", stale.name, type(exc).__name__)
    return removed


# ---------------------------------------------------------------------------
# The startup gate (RM-04e)
# ---------------------------------------------------------------------------

def pre_migration_backup(engine: Engine, db: Session, version: str) -> str:
    """Take a verified snapshot before startup migrations run. Returns a short
    status string for logging; raises ``BackupError`` if a backup was required
    and could not be produced.

    This is a safety gate, not a convenience feature: the caller must let the
    exception propagate so the app refuses to start rather than migrating money
    data with no way back. It is deliberately a no-op in the cases where there
    is nothing to protect, so an ordinary restart never fails on it:

    * the backup was explicitly disabled by the operator;
    * the database is not a file (in-memory, or a non-SQLite backend);
    * the database holds no accounts, transactions, debts or goals yet;
    * a verified snapshot for this exact version already exists, which means
      this version's migrations have already run once on this database.
    """
    ensure_log_visible()

    if not pre_migration_enabled():
        log.warning(
            "PRE_MIGRATION_BACKUP is off — startup migrations will run with no "
            "automatic snapshot. Take your own backup before upgrading."
        )
        return "disabled"

    # Checked before the directory is resolved: BACKUP_DIR may well be set on an
    # install whose database is not a file, and "there is nothing to snapshot"
    # is the more specific answer.
    if database_path(engine) is None:
        log.info("No file-backed SQLite database — skipping pre-migration backup")
        return "skipped-no-file-db"

    directory = backup_dir(engine)
    if directory is None:
        return "skipped-no-file-db"

    if not has_financial_data(db):
        log.info("Database has no financial data yet — skipping pre-migration backup")
        return "skipped-empty"

    dest = directory / f"{PRE_MIGRATION_PREFIX}{safe_version(version)}{SNAPSHOT_SUFFIX}"

    if dest.exists():
        try:
            verify_snapshot(dest)
            log.info("Pre-migration snapshot for v%s already exists (%s)", version, dest.name)
            return "already-present"
        except BackupError as exc:
            # An existing but unreadable file is worse than none — it looks like
            # protection and is not. Replace it.
            log.warning("Existing snapshot %s is unusable (%s) — retaking", dest.name, exc)

    sweep_partials(directory)
    expected = census(db)
    try:
        create_snapshot(engine, dest, expected_census=expected)
    except BackupError as exc:
        # The traceback alone is not an actionable message for a self-hoster
        # staring at `docker logs`, so say plainly what happened and what the
        # options are before the exception stops the app.
        log.error(
            "PRE-MIGRATION BACKUP FAILED — Tally will not start. %s. "
            "Free disk space or make %s writable by the container user, then restart. "
            "To start anyway without a snapshot (not recommended before an upgrade), "
            "set PRE_MIGRATION_BACKUP=off.",
            exc, directory,
        )
        raise
    log.info(
        "Pre-migration snapshot written: %s (%d bytes, %d transactions)",
        dest.name, dest.stat().st_size, expected.get("transactions", 0),
    )
    rotate_snapshots(directory, keep_count())
    return "created"
