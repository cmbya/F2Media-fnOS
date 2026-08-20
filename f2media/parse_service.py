from __future__ import annotations

import asyncio
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
from .core.cookie_format import cookie_header_for_engine, netscape_for_engine
from .core.cookies import CookieStore
from .core.db import Database
from .core.engine import engine_command
from .core.platforms import ParsedInput, parse_input
from .core.redact import redact_text
from .parsers.common import clean_url, looks_downloadable, media_kind, safe_title, unique_media
from .parsers.douyin_parse import DouyinParseAdapter
from .parsers.free_api import FreeApiStore
from .parsers.short_videos import ShortVideosLocalParser

GALLERY_PLATFORMS = {"instagram", "twitter", "facebook", "tiktok", "bilibili"}
YTDLP_PLATFORMS = {"douyin", "tiktok", "twitter", "instagram", "facebook", "youtube", "bilibili", "xiaohongshu", "kuaishou"}
YTDLP_COMPAT_FORMAT = (
    "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/"
    "b[ext=mp4][vcodec^=avc1]/"
    "bv*[vcodec^=avc1]+ba/"
    "b[ext=mp4]/bestvideo*+bestaudio/best"
)


class ParseService:
    def __init__(
        self,
        settings,
        app_settings: AppSettingsStore,
        cookies: CookieStore,
        db: Database,
        free_apis: FreeApiStore,
        logger: logging.Logger,
    ):
        self.settings = settings
        self.app_settings = app_settings
        self.cookies = cookies
        self.db = db
        self.free_apis = free_apis
        self.logger = logger
        self.douyin = DouyinParseAdapter()
        self.short_videos = ShortVideosLocalParser()

    async def parse_text(self, text: str, *, persist: bool = True) -> list[dict[str, Any]]:
        return [await self.parse_item(item, source_text=text, persist=persist) for item in parse_input(text)]

    async def parse_item(
        self, item: ParsedInput, *, source_text: str | None = None, persist: bool = True
    ) -> dict[str, Any]:
        if item.platform == "unknown":
            return {"ok": False, "platform": "unknown", "source_url": item.url, "attempts": [], "error": "无法识别平台"}

        cookie, _ = self.cookies.get(item.platform)
        attempts: list[dict[str, Any]] = []
        self.logger.info(
            "parse start platform=%s url=%s cookie_configured=%s cookie_format=%s",
            item.platform, item.url, bool(cookie), "netscape" if cookie and cookie.lstrip().startswith("# Netscape") else ("header" if cookie else "none"),
        )

        pipeline: list[tuple[str, Any]] = []
        if item.platform == "douyin":
            pipeline.append(("douyin_parse", lambda: self.douyin.parse(item.url, cookie)))
        if item.platform in ShortVideosLocalParser.SUPPORTED:
            pipeline.append(("short_videos-local", lambda: self.short_videos.parse(item.platform, item.url, cookie)))
        # User-defined/public API always comes before gallery-dl/yt-dlp.
        pipeline.append(("free-api", lambda: self._free_api_probe(item)))
        if item.platform in GALLERY_PLATFORMS:
            pipeline.append(("gallery-dl", lambda: self._gallery_probe(item)))
        if item.platform in YTDLP_PLATFORMS:
            pipeline.append(("yt-dlp", lambda: self._ytdlp_probe(item)))

        for parser_name, call in pipeline:
            try:
                raw_result = await call()
                result = await self._strict_media_result(raw_result)
                if not result.get("ok"):
                    raise RuntimeError("没有取得可下载媒体资源")
                attempts.append({"parser": parser_name, "ok": True})
                result["attempts"] = attempts
                result["cookie_configured"] = bool(cookie)
                result["title"] = safe_title(result.get("title"), self._fallback_title(item))
                if persist:
                    parse_id = uuid.uuid4().hex[:16]
                    result["parse_id"] = parse_id
                    self.db.put_parse_result(parse_id, source_text or item.url, result)
                self.logger.info(
                    "parse success platform=%s parser=%s type=%s videos=%s images=%s live=%s",
                    item.platform, result.get("parser"), result.get("media_type"),
                    result.get("counts", {}).get("videos"), result.get("counts", {}).get("images"),
                    result.get("counts", {}).get("live_photos"),
                )
                return result
            except Exception as exc:
                error = redact_text(f"{type(exc).__name__}: {exc}")
                attempts.append({"parser": parser_name, "ok": False, "error": error})
                self.logger.info("parse fallback platform=%s parser=%s error=%s", item.platform, parser_name, error)

        error = attempts[-1].get("error") if attempts else "没有可用解析器"
        self.logger.warning("parse failed platform=%s url=%s attempts=%s", item.platform, item.url, attempts)
        return {
            "ok": False,
            "platform": item.platform,
            "source_url": item.url,
            "attempts": attempts,
            "cookie_configured": bool(cookie),
            "error": error or "所有解析器均失败",
        }

    async def _free_api_probe(self, item: ParsedInput) -> dict[str, Any]:
        result, config = await self.free_apis.parse(item.platform, item.url)
        result["free_api_id"] = config.get("id")
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

    async def _ytdlp_probe(self, item: ParsedInput) -> dict[str, Any]:
        prefix = engine_command("yt-dlp")
        if not prefix:
            raise RuntimeError("yt-dlp 不可用")
        state = self.settings.data_dir / "engine-state" / item.platform / "parse"
        cookie_file = await self._cookie_file(item, "yt")
        cmd = [
            *prefix, "--ignore-config", "--no-warnings", "--skip-download", "--dump-single-json",
            "--no-playlist", "-f", YTDLP_COMPAT_FORMAT,
        ]
        deno = os.getenv("F2MEDIA_DENO_BIN", "").strip()
        if deno and Path(deno).exists():
            cmd += ["--js-runtimes", f"deno:{deno}"]
        if cookie_file:
            cmd += ["--cookies", str(cookie_file)]
        cmd.append(item.url)
        try:
            rc, out, err = await self._capture(cmd, state_dir=state, timeout=90)
        finally:
            if cookie_file:
                cookie_file.unlink(missing_ok=True)
        if rc != 0:
            raise RuntimeError(redact_text(err.strip()[-1800:] or f"yt-dlp exit={rc}"))
        try:
            data = json.loads(out)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"yt-dlp JSON 解析失败: {exc}") from exc
        result = self._normalize_ytdlp(data, item)
        if not result["ok"]:
            raise RuntimeError("yt-dlp 只返回了元数据，没有可下载视频资源")
        return result

    @staticmethod
    def _normalize_ytdlp(data: dict[str, Any], item: ParsedInput) -> dict[str, Any]:
        entry: dict[str, Any] = data
        entries = data.get("entries") if isinstance(data, dict) else None
        if isinstance(entries, list) and entries:
            entry = next((x for x in entries if isinstance(x, dict)), data)
        chosen: list[dict[str, Any]] = []
        requested = entry.get("requested_formats") or entry.get("requested_downloads") or []
        if isinstance(requested, list):
            for fmt in requested:
                if not isinstance(fmt, dict):
                    continue
                url = clean_url(fmt.get("url"))
                if not url:
                    continue
                vcodec = str(fmt.get("vcodec") or "none")
                acodec = str(fmt.get("acodec") or "none")
                if vcodec != "none":
                    chosen.append({
                        "type": "video", "url": url, "format_id": fmt.get("format_id"),
                        "vcodec": vcodec, "acodec": acodec,
                        "height": fmt.get("height"), "width": fmt.get("width"),
                    })
        direct = clean_url(entry.get("url"))
        if direct and str(entry.get("vcodec") or "none") != "none":
            chosen.append({
                "type": "video", "url": direct, "format_id": entry.get("format_id"),
                "vcodec": entry.get("vcodec"), "acodec": entry.get("acodec"),
                "height": entry.get("height"), "width": entry.get("width"),
            })
        media = unique_media(chosen)
        cover = clean_url(entry.get("thumbnail"))
        return {
            "ok": bool(media),
            "platform": item.platform,
            "source_url": item.url,
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
            "counts": {"videos": 1 if media else 0, "images": 0, "live_photos": 0},
            "download_plan": {"strategy": "yt-dlp", "format": YTDLP_COMPAT_FORMAT},
        }

    async def _gallery_probe(self, item: ParsedInput) -> dict[str, Any]:
        prefix = engine_command("gallery-dl")
        if not prefix:
            raise RuntimeError("gallery-dl 不可用")
        state = self.settings.data_dir / "engine-state" / item.platform / "parse"
        cookie_file = await self._cookie_file(item, "gdl")
        conf_path = self.settings.temp_dir / f"parse-{uuid.uuid4().hex[:10]}-gdl.json"
        target = await self._normalize_share_url(item, cookie_header_for_engine(self.cookies.get(item.platform)[0]))
        rows: list[dict[str, Any]] = []
        media: list[dict[str, Any]] = []
        rc, out, err = 1, "", ""
        try:
            # Metadata JSONL returns the final media URL (_url) without writing the media.
            conf: dict[str, Any] = {
                "extractor": {
                    "download": False,
                    "skip": False,
                    "postprocessors": {"name": "metadata", "mode": "jsonl", "event": "prepare", "filename": "-"},
                },
                "output": {"mode": "null", "progress": False},
                "cache": {"file": ":memory:"},
            }
            if cookie_file:
                conf["extractor"]["cookies"] = str(cookie_file)
            conf_path.write_text(json.dumps(conf, ensure_ascii=False), encoding="utf-8")
            rc, out, err = await self._capture(
                [*prefix, "--config", str(conf_path), "--no-input", target],
                state_dir=state, timeout=75,
            )
            for line in out.splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
            for row in rows:
                url = clean_url(row.get("_url")) or clean_url(row.get("url"))
                if url:
                    media.append({"type": media_kind(url), "url": url})

            # Some extractors cannot emit metadata JSONL but do support -g. Reuse the
            # same Cookie file until both probes finish; do not delete it between probes.
            if not media:
                simple = {"cache": {"file": ":memory:"}, "extractor": {}}
                if cookie_file:
                    simple["extractor"]["cookies"] = str(cookie_file)
                conf_path.write_text(json.dumps(simple, ensure_ascii=False), encoding="utf-8")
                rc2, out2, err2 = await self._capture(
                    [*prefix, "--config", str(conf_path), "--no-input", "-g", target],
                    state_dir=state, timeout=75,
                )
                if rc2 == 0:
                    for line in out2.splitlines():
                        url = clean_url(line.strip())
                        if url:
                            media.append({"type": media_kind(url), "url": url})
                else:
                    rc, err = rc2, err2 or err
        finally:
            conf_path.unlink(missing_ok=True)
            if cookie_file:
                cookie_file.unlink(missing_ok=True)

        media = unique_media(media)
        if rc != 0 and not media:
            raise RuntimeError(redact_text(err.strip()[-1800:] or f"gallery-dl exit={rc}"))
        if not media:
            raise RuntimeError("gallery-dl 没有返回媒体 URL")
        first = rows[0] if rows else {}
        title = next((str(first.get(k) or "") for k in ("title", "caption", "description", "content", "post_text") if first.get(k)), "")
        author = next((str(first.get(k) or "") for k in ("username", "user", "author", "owner") if first.get(k)), "")
        images = sum(1 for x in media if x["type"] == "image")
        videos = sum(1 for x in media if x["type"] == "video")
        return {
            "ok": True,
            "platform": item.platform,
            "source_url": item.url,
            "canonical_url": target,
            "parser": "gallery-dl",
            "title": title,
            "author": {"id": "", "name": author, "avatar": ""},
            "cover_url": next((x["url"] for x in media if x["type"] == "image"), None),
            "media_type": "mixed" if images and videos else ("gallery" if images > 1 else "image" if images else "video"),
            "media": media,
            "live_photos": [],
            "counts": {"videos": videos, "images": images, "live_photos": 0},
        }

    async def _normalize_share_url(self, item: ParsedInput, cookie_header: str | None) -> str:
        # Normalize share wrappers before handing them to extractors. Keep this generic and
        # only follow redirects; no page data is downloaded into the media library.
        if item.platform not in {"facebook", "tiktok", "bilibili", "kuaishou", "xiaohongshu", "douyin"}:
            return item.url
        headers = {"User-Agent": "Mozilla/5.0 Chrome/143 Safari/537.36"}
        if cookie_header:
            headers["Cookie"] = cookie_header
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=headers) as client:
                response = await client.get(item.url)
                final = str(response.url)
                return final if final.startswith(("http://", "https://")) else item.url
        except Exception:
            return item.url

    async def _strict_media_result(self, result: dict[str, Any]) -> dict[str, Any]:
        raw_media = result.get("media") or []
        checked: list[dict[str, Any]] = []
        for raw in raw_media if isinstance(raw_media, list) else []:
            if not isinstance(raw, dict):
                continue
            url = clean_url(raw.get("url"))
            if not url:
                continue
            hint = str(raw.get("type") or "")
            if looks_downloadable(url, hint):
                checked.append({**raw, "url": url, "type": media_kind(url, hint)})
                continue
            probed = await self._probe_media_type(url, result.get("source_url"))
            if probed:
                checked.append({**raw, "url": url, "type": probed})
        checked = unique_media(checked)

        live_pairs: list[dict[str, str]] = []
        for pair in result.get("live_photos") or []:
            if not isinstance(pair, dict):
                continue
            image = clean_url(pair.get("image_url") or pair.get("image"))
            video = clean_url(pair.get("video_url") or pair.get("video"))
            if not image or not video:
                continue
            image_ok = looks_downloadable(image, "image") or await self._probe_media_type(image, result.get("source_url")) == "image"
            video_ok = looks_downloadable(video, "video") or await self._probe_media_type(video, result.get("source_url")) == "video"
            if image_ok and video_ok:
                live_pairs.append({"image_url": image, "video_url": video})
                if not any(x.get("url") == image for x in checked):
                    checked.append({"type": "image", "url": image, "live_pair": True})
                if not any(x.get("url") == video for x in checked):
                    checked.append({"type": "live_video", "url": video, "live_pair": True})

        result = dict(result)
        result["media"] = unique_media(checked)
        result["live_photos"] = live_pairs
        images = sum(1 for x in result["media"] if x["type"] == "image")
        videos = sum(1 for x in result["media"] if x["type"] in {"video", "video_track"})
        result["counts"] = {"videos": videos or (1 if result.get("download_plan", {}).get("strategy") == "yt-dlp" and result["media"] else 0), "images": images, "live_photos": len(live_pairs)}
        if live_pairs:
            result["media_type"] = "live_photo"
        elif images and videos:
            result["media_type"] = "mixed"
        elif images > 1:
            result["media_type"] = "gallery"
        elif images == 1:
            result["media_type"] = "image"
        elif result["media"]:
            result["media_type"] = "video"
        else:
            result["media_type"] = "metadata" if result.get("title") else "unknown"
        result["ok"] = bool(result["media"])
        return result

    async def _probe_media_type(self, url: str, referer: str | None) -> str | None:
        if urlparse(url).hostname in {"www.tiktok.com", "www.instagram.com", "x.com", "twitter.com", "www.facebook.com", "www.youtube.com", "youtu.be"}:
            return None
        headers = {"User-Agent": "Mozilla/5.0 Chrome/143 Safari/537.36", "Range": "bytes=0-0"}
        if referer:
            headers["Referer"] = referer
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=headers) as client:
                response = await client.get(url)
            content_type = response.headers.get("content-type", "").lower()
            if content_type.startswith("video/") or "mpegurl" in content_type:
                return "video"
            if content_type.startswith("image/"):
                return "image"
        except Exception:
            pass
        return None

    @staticmethod
    def _fallback_title(item: ParsedInput) -> str:
        path = urlparse(item.url).path.strip("/")
        token = re.sub(r"[^0-9A-Za-z_-]+", "_", path.split("/")[-1] if path else "")[:60]
        labels = {
            "douyin": "抖音", "kuaishou": "快手", "bilibili": "哔哩哔哩", "xiaohongshu": "小红书",
            "instagram": "Instagram", "twitter": "X", "youtube": "YouTube", "facebook": "Facebook", "tiktok": "TikTok",
        }
        return f"{labels.get(item.platform, item.platform)}_{token or uuid.uuid4().hex[:8]}"
