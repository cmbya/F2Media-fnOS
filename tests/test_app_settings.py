from pathlib import Path

import pytest

from f2media.core.app_settings import AppSettingsStore
from f2media.core.config import Settings
from f2media.core.db import Database


def _settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    default = tmp_path / "default-downloads"
    logs = tmp_path / "logs"
    tasks = logs / "tasks"
    for path in (data, default, logs, tasks):
        path.mkdir(parents=True, exist_ok=True)
    return Settings(
        host="127.0.0.1",
        port=18082,
        data_dir=data,
        download_dir=default,
        log_dir=logs,
        task_log_dir=tasks,
        temp_dir=data / "tmp",
        db_path=data / "f2media.db",
        secret_key_path=data / "secret.key",
        log_level="INFO",
    )


def test_custom_download_dir_persists_and_resets(tmp_path: Path):
    settings = _settings(tmp_path)
    db = Database(settings.db_path)
    store = AppSettingsStore(db, settings)
    custom = tmp_path / "custom" / "media"
    assert store.set_download_dir(str(custom)) == custom.resolve()
    assert store.effective_download_dir() == custom.resolve()
    assert AppSettingsStore(db, settings).effective_download_dir() == custom.resolve()
    assert store.set_download_dir("") == settings.download_dir
    assert store.effective_download_dir() == settings.download_dir


def test_custom_download_dir_requires_absolute_path(tmp_path: Path):
    settings = _settings(tmp_path)
    store = AppSettingsStore(Database(settings.db_path), settings)
    with pytest.raises(ValueError, match="绝对路径"):
        store.set_download_dir("relative/path")
