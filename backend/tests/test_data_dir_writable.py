"""
BACKLOG-062 (GitHub #62) — clear startup message when /data is not writable.

``check_data_dir_writable`` runs at import of ``app.database``, before the
engine is created. These tests call it directly with throwaway paths under
``tmp_path``; nothing here touches the real database.

The chmod-based tests are skipped when running as root, because root ignores
permission bits. The ``os.access``-patched test covers the same message path
everywhere, including the in-container suite (which runs as root).
"""
import os
import stat

import pytest

from app import database
from app.database import check_data_dir_writable

needs_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses permission bits",
)


def _url(path) -> str:
    return f"sqlite:///{path}"


def _assert_one_plain_message(err: str, folder) -> None:
    assert "Tally cannot start" in err
    assert err.count("Tally cannot start") == 1
    assert str(folder) in err
    assert f"uid {os.getuid()}" in err
    assert f"sudo chown -R {os.getuid()}:{os.getgid()} <your data folder>" in err
    assert database.UNRAID_DEFAULT_DATA_DIR in err
    assert "Traceback" not in err


@needs_non_root
def test_readonly_folder_exits_with_message(tmp_path, capsys):
    folder = tmp_path / "data"
    folder.mkdir()
    folder.chmod(0o555)
    try:
        with pytest.raises(SystemExit) as exc:
            check_data_dir_writable(_url(folder / "tally.db"))
        assert exc.value.code == 1
        err = capsys.readouterr().err
        _assert_one_plain_message(err, folder)
        assert f"owned by uid {os.getuid()}" in err
        assert "0o555" in err
    finally:
        folder.chmod(0o755)


@needs_non_root
def test_readonly_existing_file_exits_with_message(tmp_path, capsys):
    db_file = tmp_path / "tally.db"
    db_file.write_bytes(b"")
    db_file.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    try:
        with pytest.raises(SystemExit) as exc:
            check_data_dir_writable(_url(db_file))
        assert exc.value.code == 1
        _assert_one_plain_message(capsys.readouterr().err, db_file)
    finally:
        db_file.chmod(0o644)


def test_unwritable_folder_detected_even_as_root(tmp_path, capsys, monkeypatch):
    """Same message path, forced via os.access so it runs as root too."""
    folder = tmp_path / "data"
    folder.mkdir()
    monkeypatch.setattr(database.os, "access", lambda *a, **kw: False)
    with pytest.raises(SystemExit) as exc:
        check_data_dir_writable(_url(folder / "tally.db"))
    assert exc.value.code == 1
    _assert_one_plain_message(capsys.readouterr().err, folder)


def test_missing_folder_exits_with_message(tmp_path, capsys):
    folder = tmp_path / "does-not-exist"
    with pytest.raises(SystemExit) as exc:
        check_data_dir_writable(_url(folder / "tally.db"))
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "does not exist" in err
    assert "Traceback" not in err


def test_writable_folder_passes(tmp_path, capsys):
    check_data_dir_writable(_url(tmp_path / "tally.db"))
    db_file = tmp_path / "existing.db"
    db_file.write_bytes(b"")
    check_data_dir_writable(_url(db_file))
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("url", [
    "sqlite:///:memory:",
    "sqlite://",
    "postgresql://user:pass@db.example.invalid/tally",
])
def test_non_file_databases_are_not_checked(url, monkeypatch):
    monkeypatch.setattr(database.os, "access", lambda *a, **kw: False)
    check_data_dir_writable(url)  # must not raise
