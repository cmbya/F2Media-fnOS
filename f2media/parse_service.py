from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .core.app_settings import AppSettingsStore
from .core.cookie_format import netscape_for_engine
from .core.cookies import CookieStore
from .core.engine import engine_command
from .core.platforms import ParsedInput, parse_input
from .core.redact import redact_text

_PARSE_VIDEO_PLATFORMS = {"douyin", "kuaishou", "xiaohongshu", "bilibili", "twitter"}
_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".m3u8"}
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic"}


def _media_kind(url: str) -> str:
    path = urlparse(url).path.lower()
    suffix = Path(path).suffix
    if suffix in _VIDEO_EXT:
        return "video"
    if suffix in _IMAGE_EXT:
        return "image"
    if any(x in url.lower() for x in ("video", "videoplayback", ".m4s")):
        return "video"
    return "unknown"


def _clean_url(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    if isinstance(value, dict):
        for key in ("url", "src", "image", "image_url", "video", "video_url", "videoUrl"):
            out = _clean_url(value.get(key))
            if out:
                return out
    return None


def _unique(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        url = item.get("url")
        if not url:
            continue
        key = (item.get("type", "unknown"), url)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def normalize_parse_video(data: Any, platform: str, source_url: str) -> dict:
    if dataclasses.is_dataclass(data):
        data = dataclasses.asdict(data)
    if not isinstance(data, dict):
        raise ValueError("解析器返回了无法识别的数据结构")

    author_data = data.get("author") or {}
    if dataclasses.is_dataclass(author_data):
        author_data = dataclasses.asdict(author_data)
    author = {
        "id": str(author_data.get("uid") or author_data.get("id") or "") if isinstance(author_data, dict) else "",
        "name": (author_data.get("name") or author_data.get("nickname") or "") if isinstance(author_data, dict) else str(author_data or ""),
        "avatar": (author_data.get("avatar") or author_data.get("avatar_url") or "") if isinstance(author_data, dict) else "",
    }

    media: list[dict] = []
    live_photos: list[dict] = []

    video = _clean_url(data.get("video_url")) or _clean_url(data.get("url"))
    if video:
        media.append({"type": "video", "url": video})

    images = data.get("images") or []
    if isinstance(images, (str, dict)):
        images = [images]
    for image in images if isinstance(images, list) else []:
        image_url = _clean_url(image)
        if image_url:
            media.append({"type": "image", "url": image_url})
        if isinstance(image, dict):
            live_video = _clean_url(image.get("video_url")) or _clean_url(image.get("videoUrl"))
            if not live_video and isinstance(image.get("video"), (str, dict)):
                live_video = _clean_url(image.get("video"))
            if image_url and live_video:
                live_photos.append({"image_url": image_url, "video_url": live_video})
                media.append({"type": "live_video", "url": live_video})

    # parse-video-py current public models expose Live Photo in two shapes:
    # 1) images[index].live_photo_url (preferred, keeps image/video alignment)
    # 2) image_live_photos (legacy/compat list, sometimes aligned with images, sometimes compact)
    # Keep the generic live_photo/live_photos forms too for adapter compatibility.
    for idx, image in enumerate(images if isinstance(images, list) else []):
        if not isinstance(image, dict):
            continue
        image_url = _clean_url(image)
        live_video = _clean_url(image.get("live_photo_url"))
        if image_url and live_video:
            live_photos.append({"image_url": image_url, "video_url": live_video, "index": idx})
            media.append({"type": "live_video", "url": live_video})

    image_live = data.get("image_live_photos") or []
    if isinstance(image_live, (str, dict)):
        image_live = [image_live]
    if isinstance(image_live, list):
        # If the list length equals images length, preserve index pairing, including null slots.
        aligned = isinstance(images, list) and len(image_live) == len(images)
        compact_image_index = 0
        for idx, raw_video in enumerate(image_live):
            video_url = _clean_url(raw_video)
            if not video_url:
                continue
            image_url = None
            if aligned and idx < len(images):
                image_url = _clean_url(images[idx])
            elif isinstance(images, list):
                # Older parse-video-py builds returned a compact live-video list. Pair in
                # source order as a best-effort fallback and mark the source index.
                while compact_image_index < len(images) and not _clean_url(images[compact_image_index]):
                    compact_image_index += 1
                if compact_image_index < len(images):
                    image_url = _clean_url(images[compact_image_index])
                    compact_image_index += 1
            if image_url:
                live_photos.append({"image_url": image_url, "video_url": video_url, "index": idx if aligned else None})
            media.append({"type": "live_video", "url": video_url})

    raw_live = data.get("live_photo") or data.get("live_photos") or []
    if isinstance(raw_live, dict):
        raw_live = [raw_live]
    for pair in raw_live if isinstance(raw_live, list) else []:
        if not isinstance(pair, dict):
            continue
        image_url = _clean_url(pair.get("image")) or _clean_url(pair.get("image_url"))
        video_url = _clean_url(pair.get("video")) or _clean_url(pair.get("video_url")) or _clean_url(pair.get("live_photo_url"))
        if image_url and video_url:
            live_photos.append({"image_url": image_url, "video_url": video_url})
            media.extend([
                {"type": "image", "url": image_url},
                {"type": "live_video", "url": video_url},
            ])

    media = _unique(media)
    live_photos = list({(x["image_url"], x["video_url"]): x for x in live_photos}.values())
    if live_photos:
        media_type = "live_photo"
    elif any(x["type"] == "image" for x in media) and not any(x["type"] == "video" for x in media):
        media_type = "gallery"
    elif any(x["type"] == "video" for x in media):
        media_type = "video"
    else:
        media_type = str(data.get("type") or "unknown")

    return {
        "ok": bool(media),
        "platform": platform,
        "source_url": source_url,
        "parser": "parse-video-py",
        "title": str(data.get("title") or data.get("desc") or ""),
        "author": author,
        "cover_url": _clean_url(data.get("cover_url")) or _clean_url(data.get("cover")),
        "media_type": media_type,
        "media": media,
        "live_photos": live_photos,
        "counts": {
            "videos": sum(1 for x in media if x["type"] == "video"),
            "images": sum(1 for x in media if x["type"] == "image"),
            "live_photos": len(live_photos),
        },
    }


def normalize_ytdlp(data: dict, platform: str, source_url: str) -> dict:
    entry = data
    entries = data.get("entries") if isinstance(data, dict) else None
    if isinstance(entries, list) and entries:
        entry = next((x for x in entries if isinstance(x, dict)), data)
    media: list[dict] = []
    direct = _clean_url(entry.get("url"))
    if direct:
        media.append({"type": "video", "url": direct})
    requested = entry.get("requested_downloads") or []
    if isinstance(requested, list):
        for item in requested:
            u = _clean_url(item)
            if u:
                media.append({"type": "video", "url": u})
    media = _unique(media)
    thumbs = entry.get("thumbnails") or []
    cover = _clean_url(entry.get("thumbnail"))
    if not cover and isinstance(thumbs, list) and thumbs:
        cover = _clean_url(thumbs[-1])
    return {
        "ok": bool(entry.get("id") or media),
        "platform": platform,
        "source_url": source_url,
        "parser": "yt-dlp",
        "title": str(entry.get("title") or entry.get("description") or ""),
        "author": {
            "id": str(entry.get("uploader_id") or entry.get("channel_id") or ""),
            "name": str(entry.get("uploader") or entry.get("channel") or ""),
            "avatar": "",
        },
        "cover_url": cover,
        "media_type": "video" if media else "metadata",
        "media": media,
        "live_photos": [],
        "counts": {"videos": len(media), "images": 0, "live_photos": 0},
    }


class ParseService:
    def __init__(self, settings, app_settings: AppSettingsStore, cookies: CookieStore, logger: logging.Logger):
        self.settings = settings
        self.app_settings = app_settings
        self.cookies = cookies
        self.logger = logger

    async def parse_text(self, text: str) -> list[dict]:
        return [await self.parse_item(item) for item in parse_input(text)]

    async def parse_item(self, item: ParsedInput) -> dict:
        attempts: list[dict] = []
        if item.platform == "unknown":
            return {"ok": False, "platform": "unknown", "source_url": item.url, "attempts": [], "error": "无法识别平台"}

        if item.platform in _PARSE_VIDEO_PLATFORMS:
            try:
                result = await self._parse_video_py(item)
                attempts.append({"parser": "parse-video-py", "ok": result["ok"]})
                if result["ok"]:
                    result["attempts"] = attempts
                    return result
            except Exception as exc:
                attempts.append({"parser": "parse-video-py", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

        if item.platform in {"instagram", "twitter", "facebook", "tiktok"}:
            try:
                result = await self._gallery_probe(item)
                attempts.append({"parser": "gallery-dl", "ok": result["ok"]})
                if result["ok"]:
                    result["attempts"] = attempts
                    return result
            except Exception as exc:
                attempts.append({"parser": "gallery-dl", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

        try:
            result = await self._ytdlp_probe(item)
            attempts.append({"parser": "yt-dlp", "ok": result["ok"]})
            if result["ok"]:
                result["attempts"] = attempts
                return result
        except Exception as exc:
            attempts.append({"parser": "yt-dlp", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

        error = attempts[-1].get("error") if attempts else "没有可用解析器"
        self.logger.warning("parse failed platform=%s url=%s attempts=%s", item.platform, item.url, attempts)
        return {
            "ok": False,
            "platform": item.platform,
            "source_url": item.url,
            "attempts": attempts,
            "error": error or "所有解析器均失败",
        }

    async def _parse_video_py(self, item: ParsedInput) -> dict:
        from parse_video_py import parse_video_share_url

        info = await asyncio.wait_for(parse_video_share_url(item.url), timeout=45)
        result = normalize_parse_video(info, item.platform, item.url)
        if not result["ok"]:
            raise RuntimeError("parse-video-py 未返回媒体地址")
        return result

    async def _capture(self, cmd: list[str], *, state_dir: Path, timeout: int = 60) -> tuple[int, str, str]:
        env = os.environ.copy()
        env.update({
            "HOME": str(state_dir),
            "XDG_CACHE_HOME": str(state_dir / "cache"),
            "XDG_CONFIG_HOME": str(state_dir / "config"),
        })
        for p in (state_dir, state_dir / "cache", state_dir / "config"):
            p.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(state_dir), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"解析命令超过 {timeout}s")
        return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    async def _cookie_file(self, item: ParsedInput, suffix: str) -> Path | None:
        cookie, _ = self.cookies.get(item.platform)
        if not cookie:
            return None
        jar = netscape_for_engine(item.platform, cookie)
        if not jar:
            return None
        path = self.settings.temp_dir / f"parse-{uuid.uuid4().hex[:10]}-{suffix}.txt"
        path.write_text(jar, encoding="utf-8")
        path.chmod(0o600)
        return path

    async def _ytdlp_probe(self, item: ParsedInput) -> dict:
        prefix = engine_command("yt-dlp")
        if not prefix:
            raise RuntimeError("yt-dlp 不可用")
        state = self.settings.data_dir / "engine-state" / item.platform / "parse"
        cookie_file = await self._cookie_file(item, "yt")
        cmd = [*prefix, "--ignore-config", "--no-warnings", "--skip-download", "--dump-single-json", "--no-playlist"]
        deno = os.getenv("F2MEDIA_DENO_BIN", "").strip()
        if deno and Path(deno).exists():
            cmd += ["--js-runtimes", f"deno:{deno}"]
        if cookie_file:
            cmd += ["--cookies", str(cookie_file)]
        cmd.append(item.url)
        try:
            rc, out, err = await self._capture(cmd, state_dir=state, timeout=75)
        finally:
            if cookie_file:
                cookie_file.unlink(missing_ok=True)
        if rc != 0:
            raise RuntimeError(redact_text(err.strip()[-1200:] or f"yt-dlp exit={rc}"))
        try:
            data = json.loads(out)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"yt-dlp JSON 解析失败: {exc}") from exc
        result = normalize_ytdlp(data, item.platform, item.url)
        if not result["ok"]:
            raise RuntimeError("yt-dlp 未返回可识别元数据")
        return result

    async def _gallery_probe(self, item: ParsedInput) -> dict:
        prefix = engine_command("gallery-dl")
        if not prefix:
            raise RuntimeError("gallery-dl 不可用")
        state = self.settings.data_dir / "engine-state" / item.platform / "parse"
        cookie_file = await self._cookie_file(item, "gdl")
        conf: dict[str, Any] = {"cache": {"file": ":memory:"}, "output": {"mode": "pipe", "progress": False}}
        if cookie_file:
            conf["extractor"] = {"cookies": str(cookie_file)}
        conf_path = self.settings.temp_dir / f"parse-{uuid.uuid4().hex[:10]}-gdl.json"
        conf_path.write_text(json.dumps(conf), encoding="utf-8")
        target = item.url
        if item.platform == "facebook" and "/share/" in urlparse(target).path.lower():
            headers = {"User-Agent": "Mozilla/5.0 Chrome/151 Safari/537.36"}
            cookie, _ = self.cookies.get("facebook")
            if cookie and not cookie.startswith("# Netscape"):
                headers["Cookie"] = cookie
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=headers) as client:
                    target = str((await client.get(target)).url)
            except Exception:
                pass
        cmd = [*prefix, "--config", str(conf_path), "--no-input", "-g", target]
        try:
            rc, out, err = await self._capture(cmd, state_dir=state, timeout=60)
        finally:
            conf_path.unlink(missing_ok=True)
            if cookie_file:
                cookie_file.unlink(missing_ok=True)
        urls = [line.strip() for line in out.splitlines() if line.strip().startswith(("http://", "https://"))]
        if rc != 0 or not urls:
            raise RuntimeError(redact_text(err.strip()[-1200:] or f"gallery-dl exit={rc}"))
        media = _unique([{"type": _media_kind(url), "url": url} for url in urls])
        return {
            "ok": True,
            "platform": item.platform,
            "source_url": item.url,
            "parser": "gallery-dl",
            "title": "",
            "author": {"id": "", "name": "", "avatar": ""},
            "cover_url": next((x["url"] for x in media if x["type"] == "image"), None),
            "media_type": "gallery" if any(x["type"] == "image" for x in media) else "video",
            "media": media,
            "live_photos": [],
            "counts": {
                "videos": sum(1 for x in media if x["type"] == "video"),
                "images": sum(1 for x in media if x["type"] == "image"),
                "live_photos": 0,
            },
        }
