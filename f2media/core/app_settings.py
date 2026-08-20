from __future__ import annotations

import os
from pathlib import Path

from .config import Settings
from .db import Database


class AppSettingsStore:
    """Persistent user-facing settings stored in F2Media's private SQLite DB."""

    DOWNLOAD_DIR_KEY = "download_dir"

    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    def effective_download_dir(self) -> Path:
        raw = (self.db.get_setting(self.DOWNLOAD_DIR_KEY) or "").strip()
        if not raw:
            return self.settings.download_dir
        return Path(raw).expanduser()

    def snapshot(self) -> dict:
        custom = (self.db.get_setting(self.DOWNLOAD_DIR_KEY) or "").strip()
        effective = self.effective_download_dir()
        return {
            "default_download_dir": str(self.settings.download_dir),
            "custom_download_dir": custom or None,
            "download_dir": str(effective),
            "download_dir_exists": effective.exists(),
            "download_dir_writable": effective.exists() and os.access(effective, os.W_OK),
        }

    def set_download_dir(self, raw: str | None) -> Path:
        value = (raw or "").strip()
        if not value:
            self.db.delete_setting(self.DOWNLOAD_DIR_KEY)
            return self.settings.download_dir

        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("下载目录必须填写绝对路径，例如 /vol2/1000/图库/F2Media")
        # Resolve without strict=True so a new child directory can be created.
        path = path.resolve()
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise ValueError("下载目录不是文件夹")

        probe = path / ".f2media-write-test"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            raise ValueError(f"下载目录不可写：{exc}") from exc

        self.db.put_setting(self.DOWNLOAD_DIR_KEY, str(path))
        return path
