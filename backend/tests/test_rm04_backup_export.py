"""RM-04 — sovereignty proof bundle.

Covers the pre-migration backup gate (leg e), the on-demand backup download
(leg c), the JSON export (leg b), and the transactions CSV export (leg a).

The backup unit tests build their own file-backed SQLite database under
``tmp_path`` rather than using the shared in-memory fixture: a snapshot is a
file operation, and testing it against an in-memory database would prove
nothing about the thing that actually has to work.
"""

import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import backup, main, models
from app.routers import data as data_router
from app.auth import hash_password
from app.database import Base, engine as app_engine

SQLITE_MAGIC = b"SQLite format 3\x00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed(session, tx_count: int = 3):
    """Seed the minimum object graph a transaction needs, plus ``tx_count`` rows."""
    role = models.Role(name="owner", display_name="Owner", is_system=True)
    persona = models.Persona(name="analyst", data_access_level="full", is_system=True)
    session.add_all([role, persona])
    session.flush()

    user = models.User(
        username="snapshot-owner",
        hashed_password=hash_password("snapshot-pass"),
        role_id=role.id,
        persona_id=persona.id,
    )
    session.add(user)
    session.flush()

    account = models.Account(
        user_id=user.id, name="Everyday Account", account_type="checking",
        balance=250.0, currency="AUD",
    )
    session.add(account)
    session.flush()

    for i in range(tx_count):
        session.add(models.Transaction(
            account_id=account.id,
            date=date(2026, 5, 1) + timedelta(days=i),
            description=f"Sample transaction {i}",
            amount=-10.0 - i,
            transaction_type="expense",
            source="manual",
        ))
    session.commit()
    return user, account


@pytest.fixture()
def source_db(tmp_path):
    """A real, file-backed database with three transactions in it."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'source.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    _seed(session)
    yield engine, session
    session.close()
    engine.dispose()


@pytest.fixture()
def backups(tmp_path, monkeypatch):
    directory = tmp_path / "backups"
    monkeypatch.setenv("BACKUP_DIR", str(directory))
    monkeypatch.delenv("PRE_MIGRATION_BACKUP", raising=False)
    monkeypatch.delenv("BACKUP_KEEP", raising=False)
    return directory


def _rows(db_file: Path, sql: str):
    conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Leg (e) — the snapshot itself
# ---------------------------------------------------------------------------

def test_snapshot_is_a_real_restorable_database(source_db, tmp_path):
    """The core claim: a VACUUM INTO snapshot opens on its own and holds the rows.

    This is the "a backup you have never restored is not a backup" test — the
    snapshot is opened as an independent SQLite file with no help from
    SQLAlchemy or the app, and its contents are compared row by row.
    """
    engine, session = source_db
    dest = tmp_path / "backups" / "proof.db"

    backup.create_snapshot(engine, dest, expected_census=backup.census(session))

    assert dest.exists()
    assert dest.read_bytes()[:16] == SQLITE_MAGIC

    descriptions = [r[0] for r in _rows(dest, "SELECT description FROM transactions ORDER BY id")]
    assert descriptions == ["Sample transaction 0", "Sample transaction 1", "Sample transaction 2"]

    amounts = [r[0] for r in _rows(dest, "SELECT amount FROM transactions ORDER BY id")]
    assert amounts == [-10.0, -11.0, -12.0]

    assert _rows(dest, "SELECT name FROM accounts")[0][0] == "Everyday Account"
    # The snapshot is a full database, not a table dump: schema and integrity
    # both survive, which is what makes "stop the container, copy the file back"
    # a valid restore procedure.
    assert _rows(dest, "PRAGMA integrity_check")[0][0] == "ok"


def test_snapshot_tracks_later_writes(source_db, tmp_path):
    """A second snapshot reflects data added after the first."""
    engine, session = source_db
    first = tmp_path / "first.db"
    backup.create_snapshot(engine, first)

    account = session.query(models.Account).first()
    session.add(models.Transaction(
        account_id=account.id, date=date(2026, 6, 1),
        description="Added after the first snapshot", amount=-99.0,
        transaction_type="expense", source="manual",
    ))
    session.commit()

    second = tmp_path / "second.db"
    backup.create_snapshot(engine, second, expected_census=backup.census(session))

    assert _rows(first, "SELECT COUNT(*) FROM transactions")[0][0] == 3
    assert _rows(second, "SELECT COUNT(*) FROM transactions")[0][0] == 4


def test_verify_rejects_a_truncated_snapshot(source_db, tmp_path):
    """A half-written file must never pass verification."""
    engine, session = source_db
    good = tmp_path / "good.db"
    backup.create_snapshot(engine, good)

    truncated = tmp_path / "truncated.db"
    data = good.read_bytes()
    truncated.write_bytes(data[: len(data) // 3])

    with pytest.raises(backup.BackupError):
        backup.verify_snapshot(truncated)


def test_verify_rejects_an_empty_file(tmp_path):
    empty = tmp_path / "empty.db"
    empty.touch()
    with pytest.raises(backup.BackupError):
        backup.verify_snapshot(empty)


def test_verify_rejects_a_row_count_mismatch(source_db, tmp_path):
    """Census mismatch is the check that catches a silently short copy."""
    engine, session = source_db
    snapshot = tmp_path / "census.db"
    backup.create_snapshot(engine, snapshot)

    wrong = backup.census(session)
    wrong["transactions"] += 1
    with pytest.raises(backup.BackupError, match="row counts"):
        backup.verify_snapshot(snapshot, expected_census=wrong)


def test_failed_snapshot_leaves_no_partial_file(source_db, tmp_path):
    """An unwritable destination raises and leaves nothing behind that could be
    mistaken for a backup."""
    engine, _ = source_db
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("this is a file, so mkdir must fail")

    with pytest.raises(backup.BackupError):
        backup.create_snapshot(engine, blocker / "snapshot.db")

    assert blocker.is_file()
    assert not list(tmp_path.glob("*.part-*"))


def test_sweep_removes_interrupted_partials(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    (directory / ".pre-1.4.5.db.part-42-abcd1234").write_bytes(b"half a file")
    keeper = directory / "pre-1.4.5.db"
    keeper.write_bytes(b"not a real db, but not a partial either")

    assert backup.sweep_partials(directory) == 1
    assert keeper.exists()
    assert not list(directory.glob("*.part-*"))


# ---------------------------------------------------------------------------
# Leg (e) — rotation
# ---------------------------------------------------------------------------

def test_rotation_keeps_the_newest_and_ignores_foreign_files(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    for i in range(5):
        snapshot = directory / f"pre-1.4.{i}.db"
        snapshot.write_bytes(b"x")
        os.utime(snapshot, (1_700_000_000 + i, 1_700_000_000 + i))
    # Files this module did not create must survive rotation untouched.
    foreign = directory / "my-own-backup.db"
    foreign.write_bytes(b"operator's own copy")

    assert backup.rotate_snapshots(directory, keep=2) == 3
    remaining = sorted(p.name for p in directory.glob("*.db"))
    assert remaining == ["my-own-backup.db", "pre-1.4.3.db", "pre-1.4.4.db"]


def test_rotation_never_deletes_the_last_copy(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    only = directory / "pre-1.4.5.db"
    only.write_bytes(b"x")

    # keep=0 is nonsense; the floor of 1 means it cannot delete the only backup.
    assert backup.rotate_snapshots(directory, keep=0) == 0
    assert only.exists()


def test_keep_count_floors_and_falls_back(monkeypatch):
    monkeypatch.setenv("BACKUP_KEEP", "0")
    assert backup.keep_count() == 1
    monkeypatch.setenv("BACKUP_KEEP", "not-a-number")
    assert backup.keep_count() == backup.DEFAULT_KEEP
    monkeypatch.delenv("BACKUP_KEEP")
    assert backup.keep_count() == backup.DEFAULT_KEEP


# ---------------------------------------------------------------------------
# Leg (e) — the startup gate
# ---------------------------------------------------------------------------

def test_gate_creates_a_snapshot_named_for_the_version(source_db, backups):
    engine, session = source_db
    assert backup.pre_migration_backup(engine, session, "1.4.5") == "created"

    snapshot = backups / "pre-1.4.5.db"
    assert snapshot.exists()
    assert _rows(snapshot, "SELECT COUNT(*) FROM transactions")[0][0] == 3


def test_gate_is_idempotent_across_restarts(source_db, backups):
    """An ordinary restart at the same version must not re-snapshot."""
    engine, session = source_db
    assert backup.pre_migration_backup(engine, session, "1.4.5") == "created"
    written_at = (backups / "pre-1.4.5.db").stat().st_mtime_ns

    assert backup.pre_migration_backup(engine, session, "1.4.5") == "already-present"
    assert (backups / "pre-1.4.5.db").stat().st_mtime_ns == written_at


def test_gate_replaces_a_corrupt_existing_snapshot(source_db, backups):
    """A file that looks like a backup but is not one is worse than none."""
    engine, session = source_db
    backups.mkdir(parents=True)
    corrupt = backups / "pre-1.4.5.db"
    corrupt.write_bytes(b"this is not a database")

    assert backup.pre_migration_backup(engine, session, "1.4.5") == "created"
    assert _rows(corrupt, "SELECT COUNT(*) FROM transactions")[0][0] == 3


def test_gate_skips_an_empty_database(tmp_path, backups):
    """A fresh install has nothing to lose, so first run is never blocked."""
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        assert backup.pre_migration_backup(engine, session, "1.4.5") == "skipped-empty"
        assert not backups.exists()
    finally:
        session.close()
        engine.dispose()


def test_gate_skips_an_in_memory_database(backups):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        assert backup.pre_migration_backup(engine, session, "1.4.5") == "skipped-no-file-db"
    finally:
        session.close()
        engine.dispose()


def test_gate_can_be_turned_off_explicitly(source_db, backups, monkeypatch):
    engine, session = source_db
    monkeypatch.setenv("PRE_MIGRATION_BACKUP", "off")
    assert backup.pre_migration_backup(engine, session, "1.4.5") == "disabled"
    assert not backups.exists()


def test_gate_raises_when_the_backup_directory_is_unusable(source_db, tmp_path, monkeypatch):
    """The whole point of leg (e): no verified snapshot means no migration."""
    engine, session = source_db
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the backup directory should be")
    monkeypatch.setenv("BACKUP_DIR", str(blocker / "backups"))

    with pytest.raises(backup.BackupError):
        backup.pre_migration_backup(engine, session, "1.4.5")


def test_gate_rotates_only_after_a_successful_snapshot(source_db, backups, monkeypatch):
    engine, session = source_db
    monkeypatch.setenv("BACKUP_KEEP", "2")
    for version in ("1.4.2", "1.4.3", "1.4.4", "1.4.5"):
        backup.pre_migration_backup(engine, session, version)

    remaining = sorted(p.name for p in backups.glob("pre-*.db"))
    assert remaining == ["pre-1.4.4.db", "pre-1.4.5.db"]
    # Whatever rotation removed, the newest snapshot is still a real database.
    assert _rows(backups / "pre-1.4.5.db", "SELECT COUNT(*) FROM transactions")[0][0] == 3


def test_version_string_is_made_filename_safe():
    assert backup.safe_version("1.4.5") == "1.4.5"
    assert "/" not in backup.safe_version("1.4.5/../../etc")
    assert backup.safe_version("1.4.5/../../etc") == "1.4.5-..-..-etc"
    assert backup.safe_version("") == "unknown"


def test_startup_aborts_when_the_backup_gate_fails(monkeypatch):
    """A failed backup must stop the app, not be logged and stepped over.

    Declared after the leg-(c) helpers would read better, but this is the single
    most important assertion in the file: it proves the gate is wired into the
    lifespan without a try/except softening it.
    """
    def refuse(*_args, **_kwargs):
        raise backup.BackupError("simulated disk full")

    monkeypatch.setattr(main.backup, "pre_migration_backup", refuse)
    with pytest.raises(backup.BackupError):
        with TestClient(main.app):
            pass


# ---------------------------------------------------------------------------
# Leg (a) — transactions CSV export
# ---------------------------------------------------------------------------

def _csv_lines(response):
    return response.text.strip().split("\r\n")


def test_csv_export_requires_authentication(client):
    assert client.get("/api/transactions/export").status_code == 403


def test_csv_export_returns_every_transaction(client, auth_headers, db, test_account):
    for i in range(3):
        db.add(models.Transaction(
            account_id=test_account.id, date=date(2026, 5, 1) + timedelta(days=i),
            description=f"Row {i}", amount=-5.0 - i, transaction_type="expense",
        ))
    db.commit()

    resp = client.get("/api/transactions/export", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in resp.headers["content-disposition"]

    lines = _csv_lines(resp)
    assert lines[0] == "id,date,description,amount,transaction_type,category,account,source,is_verified,notes"
    assert len(lines) == 4
    assert "Row 0" in lines[1]
    assert ",-5.00," in lines[1]
    assert "Test Cheque" in lines[1]


def test_csv_export_honours_the_shared_filter_layer(client, auth_headers, db, test_account):
    db.add_all([
        models.Transaction(
            account_id=test_account.id, date=date(2026, 5, 1),
            description="Old row", amount=-5.0, transaction_type="expense",
        ),
        models.Transaction(
            account_id=test_account.id, date=date(2026, 7, 1),
            description="New row", amount=-6.0, transaction_type="expense",
        ),
    ])
    db.commit()

    resp = client.get(
        "/api/transactions/export",
        params={"date_from": "2026-06-01"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.text
    assert "New row" in body
    assert "Old row" not in body


def test_csv_export_neutralises_spreadsheet_formulas(client, auth_headers, db, test_account):
    db.add(models.Transaction(
        account_id=test_account.id, date=date(2026, 5, 1),
        description="=1+1", amount=-5.0, transaction_type="expense",
    ))
    db.commit()

    resp = client.get("/api/transactions/export", headers=auth_headers)
    assert "'=1+1" in resp.text
    # The amount column is generated by Tally and must stay machine-readable.
    assert ",-5.00," in resp.text


def test_csv_export_rejects_an_unknown_format(client, auth_headers):
    resp = client.get("/api/transactions/export", params={"format": "xlsx"}, headers=auth_headers)
    assert resp.status_code == 400


def test_export_route_is_not_shadowed_by_the_id_route(client, auth_headers):
    """`/export` is declared before `/{tx_id}`; regressing that order would turn
    this into a 404 or 422 rather than a CSV."""
    resp = client.get("/api/transactions/export", headers=auth_headers)
    assert resp.headers["content-type"].startswith("text/csv")


# ---------------------------------------------------------------------------
# Leg (b) — JSON export
# ---------------------------------------------------------------------------

def test_json_export_requires_owner(client, db):
    viewer_role = models.Role(name="viewer", display_name="Viewer", is_system=True)
    db.add(viewer_role)
    db.flush()
    db.add(models.User(
        username="viewer-user",
        hashed_password=hash_password("viewer-pass"),
        role_id=viewer_role.id,
    ))
    db.commit()

    token = client.post(
        "/api/auth/login", json={"username": "viewer-user", "password": "viewer-pass"}
    ).json()["access_token"]
    resp = client.get("/api/data/export", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_json_export_contains_every_table_and_hides_password_hashes(
    client, auth_headers, db, test_account
):
    db.add(models.Transaction(
        account_id=test_account.id, date=date(2026, 5, 1),
        description="Exported row", amount=-12.34, transaction_type="expense",
    ))
    db.commit()

    resp = client.get("/api/data/export", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    payload = json.loads(resp.content)

    assert payload["tally_export"]["format_version"] == data_router.EXPORT_FORMAT_VERSION
    tables = payload["tables"]
    # Every mapped table is present, including ones with no rows.
    assert set(tables) == {t.name for t in Base.metadata.sorted_tables}

    exported = tables["transactions"]
    assert any(row["description"] == "Exported row" and row["amount"] == -12.34 for row in exported)
    # Dates round-trip as ISO strings rather than crashing the serialiser.
    assert exported[0]["date"] == "2026-05-01"
    assert all(row["hashed_password"] is None for row in tables["users"])
    assert tables["users"][0]["username"] == "testowner"


# ---------------------------------------------------------------------------
# Leg (c) — one-click backup download
# ---------------------------------------------------------------------------

def _app_engine_usable() -> bool:
    """The download endpoint snapshots the app's real database, so these tests
    only run where that database is reachable — inside the container or in CI,
    both of which set DATABASE_URL to a writable path."""
    try:
        with app_engine.connect():
            return True
    except Exception:
        return False


app_db_required = pytest.mark.skipif(
    not _app_engine_usable(),
    reason="requires a writable DATABASE_URL (set in CI and in the container)",
)


def test_backup_download_requires_owner(client, db):
    viewer_role = models.Role(name="viewer", display_name="Viewer", is_system=True)
    db.add(viewer_role)
    db.flush()
    db.add(models.User(
        username="viewer-backup",
        hashed_password=hash_password("viewer-pass"),
        role_id=viewer_role.id,
    ))
    db.commit()

    token = client.post(
        "/api/auth/login", json={"username": "viewer-backup", "password": "viewer-pass"}
    ).json()["access_token"]
    resp = client.get("/api/data/backup", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@app_db_required
def test_backup_download_returns_an_openable_database(client, auth_headers, tmp_path):
    resp = client.get("/api/data/backup", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/octet-stream"
    assert 'filename="tally-backup-' in resp.headers["content-disposition"]
    assert resp.content[:16] == SQLITE_MAGIC

    downloaded = tmp_path / "downloaded.db"
    downloaded.write_bytes(resp.content)
    assert _rows(downloaded, "PRAGMA integrity_check")[0][0] == "ok"


@app_db_required
def test_backup_download_does_not_accumulate_temporary_files(client, auth_headers):
    import tempfile
    before = set(Path(tempfile.gettempdir()).glob("tally-export-*"))
    client.get("/api/data/backup", headers=auth_headers)
    after = set(Path(tempfile.gettempdir()).glob("tally-export-*"))
    assert after == before
