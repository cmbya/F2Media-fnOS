from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .engine import engine_command


def _version(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=12)
        out = (p.stdout or "").strip().splitlines()
        return (out[0] if out else f"exit={p.returncode}")[:500]
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def _disk(path: Path) -> dict:
    try:
        u = shutil.disk_usage(path)
        return {"total": u.total, "used": u.used, "free": u.free}
    except Exception as e:
        return {"error": str(e)}


def diagnostics(download_dir: Path, data_dir: Path) -> dict:
    tools = {}
    for name in ("yt-dlp", "gallery-dl"):
        prefix = engine_command(name)
        tools[name] = {
            "path": " ".join(prefix) if prefix else None,
            "version": _version([*prefix, "--version"]) if prefix else "MISSING",
        }
    for name in ("ffmpeg", "ffprobe", "deno"):
        env_name = {"ffmpeg": "FFMPEG_BINARY", "ffprobe": "F2MEDIA_FFPROBE_BIN", "deno": "F2MEDIA_DENO_BIN"}[name]
        exe = os.getenv(env_name, "").strip() or shutil.which(name)
        arg = "-version" if name in {"ffmpeg", "ffprobe"} else "--version"
        tools[name] = {"path": exe, "version": _version([exe, arg]) if exe else "MISSING"}
    douyin = importlib.util.find_spec("douyin_video_parser")
    parsers = {
        "douyin_parse": {"ok": douyin is not None, "detail": douyin.origin if douyin else "MISSING"},
        "short_videos_local": {"ok": True, "detail": "Python port: douyin/kuaishou/xiaohongshu/bilibili"},
        "free_api": {"ok": True, "detail": "configurable"},
    }
    return {
        "python": sys.version.replace("\n", " "),
        "executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "libc": platform.libc_ver(),
        "timezone": os.getenv("TZ", "<system>"),
        "data_dir": str(data_dir),
        "data_exists": data_dir.exists(),
        "data_writable": os.access(data_dir, os.W_OK),
        "download_dir": str(download_dir),
        "download_exists": download_dir.exists(),
        "download_writable": download_dir.exists() and os.access(download_dir, os.W_OK),
        "download_disk": _disk(download_dir),
        "tools": tools,
        "parsers": parsers,
    }


def parser_diagnostics() -> list[dict]:
    douyin = importlib.util.find_spec("douyin_video_parser")
    return [
        {"parser": "douyin_parse", "ok": douyin is not None, "detail": douyin.origin if douyin else "MISSING"},
        {"parser": "short_videos-local", "ok": True, "detail": "douyin/kuaishou/xiaohongshu/bilibili Python port"},
        {"parser": "free-api", "ok": True, "detail": "WebUI configurable"},
        {"parser": "gallery-dl", "ok": engine_command("gallery-dl") is not None, "detail": " ".join(engine_command("gallery-dl") or [])},
        {"parser": "yt-dlp", "ok": engine_command("yt-dlp") is not None, "detail": " ".join(engine_command("yt-dlp") or [])},
    ]
