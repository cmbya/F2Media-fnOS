from pathlib import Path

from f2media.core.app_settings import AppSettingsStore
from f2media.core.config import Settings
from f2media.core.db import Database
from f2media.service import DownloadService


class DummyCookies:
    def get(self, platform):
        return None, None


class DummyParse:
    pass


class DummyLogger:
    def exception(self, *args, **kwargs):
        pass


def make_service(tmp_path: Path) -> DownloadService:
    data = tmp_path / 'data'
    downloads = tmp_path / 'downloads'
    logs = data / 'logs'
    tasks = logs / 'tasks'
    temp = data / 'tmp'
    for p in (data, downloads, logs, tasks, temp):
        p.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        data_dir=data,
        download_dir=downloads,
        log_dir=logs,
        task_log_dir=tasks,
        temp_dir=temp,
        db_path=data / 'f2media.db',
        secret_key_path=data / 'secret.key',
        host='127.0.0.1',
        port=18082,
        log_level='INFO',
    )
    db = Database(settings.db_path)
    app_settings = AppSettingsStore(db, settings)
    return DownloadService(settings, app_settings, db, DummyCookies(), DummyParse(), DummyLogger())


def test_output_layout_and_duplicate_title(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr('f2media.service.today_local', lambda: '2026-08-20')
    result = {'platform': 'douyin', 'title': '大海真蓝'}
    first = service._allocate_output_dir(result)
    second = service._allocate_output_dir(result)
    assert first.relative_to(service.app_settings.effective_download_dir()).as_posix() == '2026-08-20/抖音/大海真蓝'
    assert second.relative_to(service.app_settings.effective_download_dir()).as_posix() == '2026-08-20/抖音/大海真蓝 (2)'
