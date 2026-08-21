"""Data export and backup endpoints (RM-04 legs b and c).

Three ways to get every byte of your data out of Tally, all of them local:

* ``GET /api/data/backup`` — a SQLite snapshot of the whole database. This is
  the restore path; see docs/backup-restore.md.
* ``GET /api/data/export`` — every table as JSON, for reading elsewhere.
* ``GET /api/transactions/export?format=csv`` — lives in the transactions
  router because it shares that router's filter layer.

Nothing here uploads anything. Each response is built into a private temporary
directory, streamed to the caller, and the directory is deleted afterwards, so
the export never accumulates on the data volume.
"""

import errno
import json
import logging
import shutil
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from .. import backup, models
from ..auth import require_owner
from ..database import Base, engine, get_db

router = APIRouter(prefix="/api/data", tags=["data"])
log = logging.getLogger("tally.data")

# The JSON export is a portability format, not a credential dump. Password
# hashes stay in the .db backup (which is the restore path) and are replaced
# with null here so a JSON file copied to a laptop is not an offline cracking
# target.
REDACTED_COLUMNS = {("users", "hashed_password")}

EXPORT_FORMAT_VERSION = 1


def json_safe(value):
    """Convert a SQLAlchemy row value into something ``json.dumps`` accepts."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        # No binary columns exist today; if one is ever added, degrade to a
        # readable marker rather than crashing the whole export.
        return f"<{len(value)} bytes omitted>"
    return value


def _temp_dir_response(build, filename: str, media_type: str) -> FileResponse:
    """Build a file in a throwaway directory and stream it, cleaning up after.

    The file is written before the response is returned, so a failure surfaces
    as a proper error status rather than a truncated download.
    """
    tmpdir = tempfile.mkdtemp(prefix="tally-export-")
    path = Path(tmpdir) / filename
    try:
        build(path)
    except BaseException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        background=BackgroundTask(shutil.rmtree, tmpdir, ignore_errors=True),
    )


def storage_error(exc: OSError, what: str) -> HTTPException:
    """Map a filesystem failure to a status code the UI can explain.

    A full disk is the common real-world case and deserves its own code so the
    operator is not left guessing at a generic 500.
    """
    if exc.errno == errno.ENOSPC:
        return HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=f"Not enough free disk space to build the {what}.",
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Could not build the {what}: {type(exc).__name__}.",
    )


@router.get("/backup")
def download_backup(_: models.User = Depends(require_owner)):
    """Download a consistent SQLite snapshot of the whole database.

    Uses ``VACUUM INTO``, so it is safe to run while Tally is in use — the copy
    reflects a single committed point in time. Owner-only: this file contains
    every account, transaction and password hash in the install.
    """
    filename = f"tally-backup-{backup.timestamp_slug()}.db"

    def build(path: Path) -> None:
        # No expected census is passed: another user could be writing while the
        # download runs, so row counts are legitimately allowed to differ from
        # a reading taken a moment earlier. The structural checks (readable
        # database, integrity check, money tables present) still apply.
        backup.create_snapshot(engine, path)

    try:
        return _temp_dir_response(build, filename, "application/octet-stream")
    except backup.BackupError as exc:
        log.error("Backup download failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not create the backup: {exc}",
        ) from exc
    except OSError as exc:
        log.error("Backup download failed: %s", type(exc).__name__)
        raise storage_error(exc, "backup") from exc


@router.get("/export")
def export_all_data(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_owner),
):
    """Export every table as a single JSON document.

    Tables are discovered from the ORM metadata rather than listed by hand, so a
    table added in a later release is exported without anyone remembering to
    update this endpoint.
    """
    filename = f"tally-export-{backup.timestamp_slug()}.json"

    def build(path: Path) -> None:
        with path.open("w", encoding="utf-8") as fh:
            fh.write('{\n  "tally_export": ')
            json.dump(
                {
                    "format_version": EXPORT_FORMAT_VERSION,
                    "generated_at": datetime.now().astimezone().isoformat(),
                    "note": (
                        "Password hashes are omitted. Use the SQLite backup "
                        "(Settings > Data > Download backup) to restore an install."
                    ),
                },
                fh,
                indent=2,
            )
            fh.write(',\n  "tables": {\n')
            # One table at a time, one row at a time — memory stays flat no
            # matter how many transactions the install has.
            for table_index, table in enumerate(Base.metadata.sorted_tables):
                if table_index:
                    fh.write(",\n")
                fh.write(f"    {json.dumps(table.name)}: [")
                rows_written = 0
                for row in db.execute(select(table)).mappings():
                    payload = {
                        column: (
                            None
                            if (table.name, column) in REDACTED_COLUMNS
                            else json_safe(value)
                        )
                        for column, value in row.items()
                    }
                    fh.write("\n      " if rows_written == 0 else ",\n      ")
                    fh.write(json.dumps(payload, default=str))
                    rows_written += 1
                fh.write("\n    ]" if rows_written else "]")
            fh.write("\n  }\n}\n")

    try:
        return _temp_dir_response(build, filename, "application/json")
    except OSError as exc:
        log.error("JSON export failed: %s", type(exc).__name__)
        raise storage_error(exc, "export") from exc
