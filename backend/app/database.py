import os
import sys
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////data/tally.db")

# The shipped image runs as this user (Dockerfile: useradd -r ... tally).
# Named here only for the help text — the check itself uses the real uid.
IMAGE_UID = 999
UNRAID_DEFAULT_DATA_DIR = "/mnt/user/appdata/tally/data"


def _sqlite_file_path(url: str) -> str | None:
    """Return the filesystem path behind a file-backed SQLite URL, else None.

    In-memory databases, non-SQLite backends and ``file:`` URIs are skipped —
    there is no directory to check, or SQLAlchemy/SQLite own the semantics.
    """
    try:
        parsed = make_url(url)
    except Exception:
        return None
    if parsed.get_backend_name() != "sqlite":
        return None
    database = parsed.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return None
    return database


def check_data_dir_writable(url: str = DATABASE_URL) -> None:
    """BACKLOG-062 (#62): fail fast, in plain words, when /data is not writable.

    Without this the first write surfaces as a SQLAlchemy ``OperationalError:
    attempt to write a readonly database`` (or ``unable to open database
    file``) buried in a traceback. The most common cause is a bind-mounted
    data folder owned by root on the host while the container runs as the
    non-root ``tally`` user.

    Checks, for a file-backed SQLite URL only:
      * the folder must exist and be writable — SQLite in WAL mode creates
        ``<db>-wal`` and ``<db>-shm`` beside the database, so a writable
        file in an unwritable folder is still fatal;
      * the database file itself must be writable if it already exists.

    On failure: ONE message on stderr naming the uid Tally runs as, the
    owner of the offending path, and the exact ``chown`` to run, then
    ``SystemExit(1)`` — no traceback.
    """
    path = _sqlite_file_path(url)
    if path is None:
        return

    directory = os.path.dirname(os.path.abspath(path))

    if not os.path.isdir(directory):
        offending, problem = directory, "does not exist"
    elif not os.access(directory, os.W_OK | os.X_OK):
        offending, problem = directory, "is not writable by the user Tally runs as"
    elif os.path.exists(path) and not os.access(path, os.W_OK):
        offending, problem = path, "is not writable by the user Tally runs as"
    else:
        return

    uid, gid = os.getuid(), os.getgid()
    owner_line = ""
    try:
        st = os.stat(offending)
        owner_line = (
            f"  {offending} is owned by uid {st.st_uid} (gid {st.st_gid}), "
            f"permissions {oct(st.st_mode & 0o777)}.\n"
        )
    except OSError:
        pass

    message = (
        f"\nTally cannot start: {offending} {problem}.\n"
        f"  Tally runs inside the container as uid {uid}"
        f"{' (the tally user)' if uid == IMAGE_UID else ''}; "
        f"it needs to create and write its database under {directory}.\n"
        f"{owner_line}"
        f"\nFix: on the HOST (not inside the container), give the folder you mount at "
        f"{directory} to uid {uid}, then restart the container:\n"
        f"\n    sudo chown -R {uid}:{gid} <your data folder>\n"
        f"\n  (On Unraid the default folder is {UNRAID_DEFAULT_DATA_DIR}.)\n"
        f"  See docs/getting-started.md, Installation.\n"
    )
    print(message, file=sys.stderr, flush=True)
    raise SystemExit(1)


check_data_dir_writable()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Enable WAL mode and foreign keys for every SQLite connection
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
