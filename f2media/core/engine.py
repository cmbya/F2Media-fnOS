from __future__ import annotations

import os
import shutil


ENV_NAMES = {
    "f2": "F2MEDIA_F2_BIN",
    "yt-dlp": "F2MEDIA_YTDLP_BIN",
    "gallery-dl": "F2MEDIA_GALLERYDL_BIN",
    "ks-downloader": "F2MEDIA_KS_BIN",
    "xhs-downloader": "F2MEDIA_XHS_BIN",
}


def engine_command(name: str) -> list[str] | None:
    env_name = ENV_NAMES.get(name)
    if env_name:
        value = os.getenv(env_name, "").strip()
        if value:
            return [value]
    found = shutil.which(name)
    return [found] if found else None


def engine_display_path(name: str) -> str | None:
    cmd = engine_command(name)
    return " ".join(cmd) if cmd else None
