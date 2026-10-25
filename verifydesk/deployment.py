"""Offline storage preflight. It never polls Telegram or changes the working database."""

from collections.abc import Mapping
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile

from .config import Config, ConfigurationError


class DeploymentError(ValueError):
    pass


def check_storage(config: Config, environment: Mapping[str, str] | None = None):
    environment = os.environ if environment is None else environment
    directory = config.data_dir.resolve()
    on_railway = any(environment.get(key) for key in (
        "RAILWAY_ENVIRONMENT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_PROJECT_ID",
    ))
    if on_railway:
        mount = environment.get("RAILWAY_VOLUME_MOUNT_PATH", "")
        if not mount or not Path(mount).is_absolute() or Path(mount).resolve() != directory:
            raise DeploymentError("Railway: подключите Volume в /app/data и задайте DATA_DIR=/app/data.")
        if not directory.is_mount():
            raise DeploymentError("Railway: каталог данных не является подключённым Volume.")
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix=".preflight-", dir=directory) as probe:
            with closing(sqlite3.connect(Path(probe) / "check.sqlite3")) as db, db:
                db.execute("CREATE TABLE probe (value TEXT)")
                db.execute("INSERT INTO probe VALUES ('ok')")
                assert db.execute("SELECT value FROM probe").fetchone()[0] == "ok"
    except (OSError, sqlite3.Error) as exc:
        raise DeploymentError("Каталог DATA_DIR недоступен для записи SQLite.") from exc


def main():
    try:
        config = Config.load()
        check_storage(config)
    except (ConfigurationError, DeploymentError) as exc:
        print(str(exc))
        return 1
    print("Конфигурация и хранилище SQLite готовы. Telegram не запускался.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
