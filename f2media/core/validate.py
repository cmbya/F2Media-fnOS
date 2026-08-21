from __future__ import annotations

from pathlib import Path

MEDIA_EXTS = {
    ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".ts",
    ".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".heic",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".heic"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".ts"}


def snapshot(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def new_media(root: Path, before: set[str]) -> list[str]:
    after = snapshot(root)
    files = sorted(after - before)
    return [f for f in files if Path(f).suffix.lower() in MEDIA_EXTS]


def validate_output(platform: str, files: list[str]) -> tuple[str, str]:
    if not files:
        return "failed", "适配器结束后没有检测到新增媒体文件"
    if platform == "douyin":
        live = [f for f in files if "_live_" in Path(f).stem.lower() and Path(f).suffix.lower() in VIDEO_EXTS]
        images = [f for f in files if "_image_" in Path(f).stem.lower() and Path(f).suffix.lower() in IMAGE_EXTS]
        if live and not images:
            return "partial", "检测到动态文件，但没有检测到对应静态图"
        if images and any("live" in f.lower() for f in files) and not live:
            return "partial", "疑似实况图集，但没有检测到动态视频文件"
    return "success", f"新增媒体文件 {len(files)} 个"
