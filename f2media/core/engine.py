from __future__ import annotations

import os
import shutil
from pathlib import Path

ENV_NAMES = {
    "yt-dlp": "F2MEDIA_YTDLP_BIN",
    "gallery-dl": "F2MEDIA_GALLERYDL_BIN",
    "x-cli": "F2MEDIA_XCLI_BIN",
    "short_videos": "F2MEDIA_SHORT_VIDEOS_BIN",
}

BINARY_NAMES = {
    "yt-dlp": "yt-dlp",
    "gallery-dl": "gallery-dl",
    "x-cli": "x-cli",
    "short_videos": "short_videos",
}


def _override_path(name: str) -> Path | None:
    data = os.getenv("F2MEDIA_DATA_DIR", "").strip()
    binary = BINARY_NAMES.get(name)
    if not data or not binary:
        return None
    path = Path(data) / "engine-overrides" / name / "current" / binary
    return path if path.is_file() and os.access(path, os.X_OK) else None


def packaged_engine_path(name: str) -> str | None:
    env_name = ENV_NAMES.get(name)
    if env_name:
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    binary = BINARY_NAMES.get(name, name)
    return shutil.which(binary)


def engine_command(name: str) -> list[str] | None:
    override = _override_path(name)
    if override:
        return [str(override)]
    packaged = packaged_engine_path(name)
    return [packaged] if packaged else None


def engine_display_path(name: str) -> str | None:
    cmd = engine_command(name)
    return " ".join(cmd) if cmd else None
