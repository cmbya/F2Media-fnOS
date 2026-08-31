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


def test_output_layout_uses_platform_nickname_date_and_unique_filenames(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr('f2media.service.today_local', lambda: '2026-08-20')
    result = {
        'platform': 'douyin',
        'author': {'username': 'user_001', 'name': '测试用户'},
        'title': '大海真蓝',
    }
    first = service._allocate_output_dir(result)
    second = service._allocate_output_dir(result)
    relative = '抖音/测试用户/2026-08-20'
    assert first.relative_to(service.app_settings.effective_download_dir()).as_posix() == relative
    assert second == first

    first_target = service._unique_media_target(first, '大海真蓝', '.mp4')
    first_target.write_bytes(b'content')
    second_target = service._unique_media_target(first, '大海真蓝', '.mp4')
    assert first_target.name == '大海真蓝.mp4'
    assert second_target.name == '大海真蓝 (2).mp4'


def test_username_folder_prefers_nickname_for_every_platform(tmp_path):
    service = make_service(tmp_path)

    assert service._username_folder({
        'platform': 'kuaishou',
        'author': {'nickname': '快手昵称', 'username': 'kuaishou_id'},
    }) == '快手昵称'
    assert service._username_folder({
        'platform': 'instagram',
        'author': {'name': 'Instagram 昵称', 'username': 'instagram_id'},
    }) == 'Instagram 昵称'


def test_username_folder_falls_back_to_platform_account_when_nickname_missing(tmp_path):
    service = make_service(tmp_path)

    assert service._username_folder({
        'platform': 'douyin',
        'author': {'unique_id': 'douyin_id'},
    }) == 'douyin_id'
    assert service._username_folder({
        'platform': 'instagram',
        'username': 'instagram_id',
    }) == 'instagram_id'
