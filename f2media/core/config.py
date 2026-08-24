from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    download_dir: Path
    log_dir: Path
    task_log_dir: Path
    temp_dir: Path
    db_path: Path
    secret_key_path: Path
    host: str
    port: int
    log_level: str


def load_settings() -> Settings:
    base = Path(os.getenv("F2MEDIA_DATA_DIR", Path.cwd() / "data")).expanduser().resolve()
    downloads = Path(os.getenv("F2MEDIA_DOWNLOAD_DIR", base / "downloads")).expanduser().resolve()
    log_dir = Path(os.getenv("F2MEDIA_LOG_DIR", base / "logs")).expanduser().resolve()
    task_log_dir = Path(os.getenv("F2MEDIA_TASK_LOG_DIR", log_dir / "tasks")).expanduser().resolve()
    temp_dir = base / "tmp"
    for p in (base, downloads, log_dir, task_log_dir, temp_dir):
        p.mkdir(parents=True, exist_ok=True)
    # Private state must not inherit a permissive NAS/service umask. The download directory is
    # intentionally excluded because it is a user-facing fnOS share.
    for p in (base, temp_dir):
        try:
            os.chmod(p, 0o700)
        except OSError:
            pass
    return Settings(
        data_dir=base,
        download_dir=downloads,
        log_dir=log_dir,
        task_log_dir=task_log_dir,
        temp_dir=temp_dir,
        db_path=base / "f2media.db",
        secret_key_path=base / "secret.key",
        host=os.getenv("F2MEDIA_HOST", "0.0.0.0"),
        port=int(os.getenv("F2MEDIA_PORT", "18082")),
        log_level=os.getenv("F2MEDIA_LOG_LEVEL", "INFO").upper(),
    )
