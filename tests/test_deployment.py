from pathlib import Path
import sqlite3

import pytest

from verifydesk.config import Config
from verifydesk.deployment import check_storage, DeploymentError


def config(directory):
    return Config("123456:abcdefghijklmnopqrstuvwxyz0123456789ABCDE", (9001,), directory)


def test_preflight_leaves_business_database_untouched(tmp_path):
    path = tmp_path / "desk.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE existing (value TEXT)")
        db.execute("INSERT INTO existing VALUES ('unchanged')")
    before = path.read_bytes()
    check_storage(config(tmp_path), {})
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("mount", ["", "/elsewhere", "relative"])
def test_railway_requires_matching_volume(tmp_path, mount):
    with pytest.raises(DeploymentError, match="Volume"):
        check_storage(config(tmp_path), {
            "RAILWAY_ENVIRONMENT_ID": "test", "RAILWAY_VOLUME_MOUNT_PATH": mount,
        })


def test_railway_rejects_ephemeral_directory_even_if_variable_is_faked(tmp_path):
    with pytest.raises(DeploymentError, match="Volume"):
        check_storage(config(tmp_path), {
            "RAILWAY_SERVICE_ID": "test", "RAILWAY_VOLUME_MOUNT_PATH": str(tmp_path),
        })


def test_preflight_accepts_mounted_writable_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "is_mount", lambda path: path == tmp_path)
    check_storage(config(tmp_path), {
        "RAILWAY_SERVICE_ID": "test", "RAILWAY_VOLUME_MOUNT_PATH": str(tmp_path),
    })
    assert list(tmp_path.iterdir()) == []


def test_preflight_rejects_unusable_storage(tmp_path):
    target = tmp_path / "file"
    target.write_text("existing")
    with pytest.raises(DeploymentError, match="SQLite"):
        check_storage(config(target), {})
