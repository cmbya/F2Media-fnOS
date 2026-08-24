from __future__ import annotations

import asyncio
import json
import html as html_lib
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import httpx

from .core.app_settings import AppSettingsStore
from .core.cookie_format import cookie_header_for_engine, netscape_for_engine
from .core.cookies import CookieStore
from .core.db import Database
from .core.engine import engine_command
from .core.platforms import ParsedInput, parse_input
from .core.parser_routes import ParserRouteStore
from .core.redact import redact_text
from .parsers.common import clean_url, looks_downloadable, media_kind, safe_title, unique_media
from .parsers.douyin_parse import DouyinParseAdapter
from .parsers.free_api import FreeApiStore
from .parsers.social_cli import parse_cli_json, normalize_x_cli

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
        routes: ParserRouteStore,
        logger: logging.Logger,
    ):
        self.settings = settings
        self.app_settings = app_settings
        self.cookies = cookies
        self.db = db
        self.free_apis = free_apis
        self.routes = routes
        self.logger = logger
        self.douyin = DouyinParseAdapter()

    async def parse_text(
        self, text: str, *, persist: bool = True, parser: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            await self.parse_item(item, source_text=text, persist=persist, parser=parser)
            for item in parse_input(text)
        ]

    async def parse_item(
        self,
        item: ParsedInput,
        *,
        source_text: str | None = None,
        persist: bool = True,
        parser: str | None = None,
    ) -> dict[str, Any]:
        if item.platform == "unknown":
            return {"ok": False, "platform": "unknown", "source_url": item.url, "attempts": [], "error": "无法识别平台"}

        source_item = item
        item = self._normalize_routing_item(item)
        cookie, _ = self.cookies.get(item.platform)
        cookie_header = cookie_header_for_engine(cookie)
        if item.platform == "facebook":
            canonical = await self._normalize_facebook_url(item.url, cookie_header)
            if canonical != item.url:
                item = ParsedInput(url=canonical, platform=item.platform)

        attempts: list[dict[str, Any]] = []
        self.logger.info(
            "parse start platform=%s url=%s cookie_configured=%s cookie_format=%s parser=%s",
            item.platform, source_item.url, bool(cookie),
            "netscape" if cookie and cookie.lstrip().startswith("# Netscape") else ("header" if cookie else "none"),
            parser or "auto",
        )
        if item.url != source_item.url:
            self.logger.info("parse normalized platform=%s source=%s canonical=%s", item.platform, source_item.url, item.url)

        available = {x["key"] for x in self.routes.parser_options(item.platform)}
        if parser:
            if parser not in available:
                return {
                    "ok": False, "platform": item.platform, "source_url": source_item.url,
                    "canonical_url": item.url, "attempts": [], "cookie_configured": bool(cookie),
                    "error": f"指定解析器不存在: {parser}",
                }
            pipeline = [parser]
        else:
            pipeline = self.routes.enabled_keys(item.platform)

        if not pipeline:
            return {
                "ok": False, "platform": item.platform, "source_url": source_item.url,
                "canonical_url": item.url, "attempts": [], "cookie_configured": bool(cookie),
                "error": "该平台没有启用任何解析器，请到 设置 → 平台解析路由 启用",
            }

        for parser_key in pipeline:
            try:
                raw_result = await self._call_parser(parser_key, item, cookie)
                result = await self._strict_media_result(raw_result)
                if not result.get("ok"):
                    raise RuntimeError("没有取得可下载媒体资源")
                attempts.append({"parser": parser_key, "ok": True})
                result["attempts"] = attempts
                result["route_parser"] = parser_key
                result["cookie_configured"] = bool(cookie)
                result["title"] = safe_title(result.get("title"), self._fallback_title(source_item))
                result["source_url"] = source_item.url
                if item.url != source_item.url:
                    result["canonical_url"] = item.url
                if persist:
                    parse_id = uuid.uuid4().hex[:16]
                    result["parse_id"] = parse_id
                    self.db.put_parse_result(parse_id, source_text or source_item.url, result)
                self.logger.info(
                    "parse success platform=%s parser=%s route=%s type=%s videos=%s images=%s live=%s",
                    item.platform, result.get("parser"), parser_key, result.get("media_type"),
                    result.get("counts", {}).get("videos"), result.get("counts", {}).get("images"),
                    result.get("counts", {}).get("live_photos"),
                )
                return result
            except Exception as exc:
                error = redact_text(f"{type(exc).__name__}: {exc}")
                attempts.append({"parser": parser_key, "ok": False, "error": error})
                self.logger.info("parse fallback platform=%s parser=%s error=%s", item.platform, parser_key, error)

        error = attempts[-1].get("error") if attempts else "没有可用解析器"
        self.logger.warning("parse failed platform=%s url=%s attempts=%s", item.platform, source_item.url, attempts)
        return {
            "ok": False,
            "platform": item.platform,
            "source_url": source_item.url,
            "canonical_url": item.url if item.url != source_item.url else source_item.url,
            "attempts": attempts,
            "cookie_configured": bool(cookie),
            "error": error or "所有解析器均失败",
        }

    async def _call_parser(self, parser_key: str, item: ParsedInput, cookie: str | None) -> dict[str, Any]:
        if parser_key == "douyin_parse":
            if item.platform != "douyin":
                raise RuntimeError("douyin_parse 不支持该平台")
            return await self.douyin.parse(item.url, cookie)
        if parser_key == "x-cli":
            if item.platform != "twitter":
                raise RuntimeError("x-cli 只支持 X / Twitter")
            return await self._xcli_probe(item)
        if parser_key == "gallery-dl":
            return await self._gallery_probe(item)
        if parser_key == "yt-dlp":
            return await self._ytdlp_probe(item)
        if parser_key.startswith("free-api:"):
            try:
                api_id = int(parser_key.split(":", 1)[1])
            except ValueError as exc:
                raise RuntimeError("无效免费 API 路由") from exc
            return await self.free_apis.call_by_id(api_id, item.platform, item.url)
        raise RuntimeError(f"未知解析器: {parser_key}")

    @staticmethod
    def _normalize_routing_item(item: ParsedInput) -> ParsedInput:
        if item.platform == "douyin":
            try:
                parsed = urlparse(item.url)
                modal_id = (parse_qs(parsed.query).get("modal_id") or [""])[0].strip()
            except Exception:
                modal_id = ""
            if modal_id.isdigit():
                return ParsedInput(url=f"https://www.douyin.com/video/{modal_id}", platform=item.platform)
        return item

    async def _xcli_probe(self, item: ParsedInput) -> dict[str, Any]:
        prefix = engine_command("x-cli")
        if not prefix:
            raise RuntimeError("x-cli 不可用")
        state = self.settings.data_dir / "engine-state" / "twitter" / "x-cli"
        rc, out, err = await self._capture([*prefix, "media", item.url, "-o", "json"], state_dir=state, timeout=75)
        if rc != 0:
            raise RuntimeError(redact_text(err.strip()[-1800:] or out.strip()[-800:] or f"x-cli exit={rc}"))
        payload = parse_cli_json(out)
        if payload is None:
            raise RuntimeError("x-cli 没有返回 JSON 媒体数据")
        result = normalize_x_cli(payload, item.url)
        if not result.get("ok"):
            raise RuntimeError("x-cli 没有返回可下载媒体 URL")
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
        # Facebook URLs are normalized once in parse_item(). Re-running the
        # share resolver here causes duplicate network requests and can turn a
        # good canonical URL back into an unresolved share wrapper.
        if item.platform == "facebook":
            target = item.url
        else:
            target = await self._normalize_share_url(
                item, cookie_header_for_engine(self.cookies.get(item.platform)[0])
            )
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

    @staticmethod
    def _canonicalize_facebook_url(url: str) -> str:
        value = html_lib.unescape(str(url or "").strip())
        value = value.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
        value = value.strip(" \t\r\n\"'\\")
        if value.startswith("/"):
            value = urljoin("https://www.facebook.com", value)
        if not value.startswith(("http://", "https://")):
            return str(url or "")
        try:
            parsed = urlparse(value)
        except Exception:
            return value
        host = (parsed.hostname or "").lower()
        if host not in {"facebook.com", "www.facebook.com", "m.facebook.com", "mbasic.facebook.com"}:
            return value
        path = re.sub(r"/{2,}", "/", parsed.path or "/")
        query = parse_qs(parsed.query)

        group_query = re.fullmatch(r"/groups/([^/]+)/?", path, re.I)
        multi = (query.get("multi_permalinks") or [""])[0]
        if group_query and str(multi).isdigit():
            return f"https://www.facebook.com/groups/{group_query.group(1)}/posts/{multi}/"

        m = re.search(r"/groups/([^/]+)/permalink/(\d+)", path, re.I)
        if m:
            return f"https://www.facebook.com/groups/{m.group(1)}/posts/{m.group(2)}/"

        m = re.search(r"/reels?/(\d+)", path, re.I)
        if m:
            return f"https://www.facebook.com/watch/?v={m.group(1)}"

        if path.rstrip("/").lower() == "/watch":
            video_id = (query.get("v") or [""])[0]
            m = re.match(r"(\d+)", str(video_id))
            if m:
                return f"https://www.facebook.com/watch/?v={m.group(1)}"

        # yt-dlp's generic extractor often resolves /share/p/ wrappers to
        # permalink.php?story_fbid=... URLs.  gallery-dl can handle the
        # canonical permalink form, so keep only the useful query fields and
        # drop tracking/fragment noise.
        if path.rstrip("/").lower() == "/permalink.php":
            story = (query.get("story_fbid") or query.get("fbid") or [""])[0]
            owner = (query.get("id") or [""])[0]
            if story:
                kept = f"story_fbid={story}"
                if owner:
                    kept += f"&id={owner}"
                return f"https://www.facebook.com/permalink.php?{kept}"

        return urlunparse(("https", "www.facebook.com", path, "", parsed.query, ""))

    @classmethod
    def _facebook_candidates_from_html(cls, body: str) -> list[str]:
        decoded = html_lib.unescape(str(body or ""))
        decoded = decoded.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
        candidates: list[str] = []
        patterns = [
            r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
            r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
            r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:url["\']',
            r'https?://(?:www\.|m\.|mbasic\.)?facebook\.com/(?:groups/[^"\'<>\s]+|watch/\?v=\d+|reels?/\d+[^"\'<>\s]*|permalink\.php\?[^"\'<>\s]+|[^/"\'<>\s]+/posts/[^"\'<>\s]+)',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, decoded, flags=re.I):
                value = match if isinstance(match, str) else match[0]
                canonical = cls._canonicalize_facebook_url(value)
                if canonical.startswith("https://www.facebook.com/") and "/share/" not in canonical.lower():
                    if canonical not in candidates:
                        candidates.append(canonical)
        return candidates

    @classmethod
    def _facebook_candidates_from_ytdlp_output(cls, text: str) -> list[str]:
        """Extract the redirect target that yt-dlp's generic extractor saw.

        Facebook's /share/p/ and /share/r/ wrappers frequently return 400 to
        plain httpx clients while yt-dlp still follows the browser-style
        redirect chain.  We only use yt-dlp as a URL resolver here; media is
        still parsed by gallery-dl afterwards.
        """
        decoded = html_lib.unescape(str(text or ""))
        decoded = decoded.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
        candidates: list[str] = []
        patterns = [
            r"(?:Following redirect to|Redirecting to|redirect(?:ed)? to)\s*[:=]?\s*(https?://[^\s\]\)>'\"]+)",
            r"(https?://(?:www\.|m\.|mbasic\.)?facebook\.com/(?:groups/[^\s\]\)>'\"]+|watch/\?v=\d+|reels?/\d+[^\s\]\)>'\"]*|permalink\.php\?[^\s\]\)>'\"]+|[^/\s]+/posts/[^\s\]\)>'\"]+))",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, decoded, flags=re.I):
                value = match if isinstance(match, str) else match[0]
                value = value.rstrip(".,;:")
                canonical = cls._canonicalize_facebook_url(value)
                if canonical.startswith("https://www.facebook.com/") and "/share/" not in canonical.lower():
                    if canonical not in candidates:
                        candidates.append(canonical)
        return candidates

    async def _resolve_facebook_share_with_ytdlp(self, url: str) -> list[str]:
        prefix = engine_command("yt-dlp")
        if not prefix:
            return []
        item = ParsedInput(url=url, platform="facebook")
        cookie_file = await self._cookie_file(item, "fb-redirect")
        state = self.settings.data_dir / "engine-state" / "facebook" / "redirect"
        cmd = [
            *prefix,
            "--ignore-config",
            "--verbose",
            "--skip-download",
            "--no-playlist",
            "--force-generic-extractor",
            "--print",
            "%(webpage_url)s",
        ]
        if cookie_file:
            cmd += ["--cookies", str(cookie_file)]
        cmd.append(url)
        try:
            rc, out, err = await self._capture(cmd, state_dir=state, timeout=45)
        except Exception as exc:
            self.logger.info("facebook normalizer ytdlp error=%s", type(exc).__name__)
            return []
        finally:
            if cookie_file:
                cookie_file.unlink(missing_ok=True)
        rows = self._facebook_candidates_from_ytdlp_output(out + "\n" + err)
        self.logger.info(
            "facebook normalizer ytdlp rc=%s candidates=%s",
            rc,
            len(rows),
        )
        return rows

    @staticmethod
    def _facebook_candidate_score(url: str, *, prefer_video: bool = False) -> int:
        low = url.lower()
        if prefer_video:
            if "/watch/?v=" in low:
                return 100
            if "/groups/" in low and "/posts/" in low:
                return 90
            if "/posts/" in low:
                return 85
        else:
            if "/groups/" in low and "/posts/" in low:
                return 100
            if "/posts/" in low:
                return 95
            if "/watch/?v=" in low:
                return 80
        if "/photo" in low or "/videos/" in low:
            return 75
        return 10

    async def _normalize_facebook_url(self, url: str, cookie_header: str | None) -> str:
        original = self._canonicalize_facebook_url(url)
        if "/share/" not in original.lower():
            return original

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/143 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        }
        if cookie_header:
            headers["Cookie"] = cookie_header
        variants = [
            ("desktop", original),
            ("mobile", re.sub(r"https://www\.facebook\.com", "https://m.facebook.com", original, count=1, flags=re.I)),
            ("mbasic", re.sub(r"https://www\.facebook\.com", "https://mbasic.facebook.com", original, count=1, flags=re.I)),
        ]
        found: list[str] = []
        for label, candidate_url in variants:
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=18, headers=headers) as client:
                    response = await client.get(candidate_url)
                final = self._canonicalize_facebook_url(str(response.url))
                self.logger.info(
                    "facebook normalizer variant=%s status=%s final=%s cookie_configured=%s",
                    label, response.status_code, final, bool(cookie_header),
                )
                if final != original and "/share/" not in final.lower():
                    found.append(final)
                found.extend(self._facebook_candidates_from_html(response.text))
            except Exception as exc:
                self.logger.info("facebook normalizer variant=%s error=%s", label, type(exc).__name__)

        # Facebook frequently gives plain HTTP clients a 400 page for share
        # wrappers, while yt-dlp's generic extractor can still see the actual
        # redirect target.  Use that capability only as a resolver, then hand
        # the canonical URL to gallery-dl for the real media extraction.
        if not found:
            found.extend(await self._resolve_facebook_share_with_ytdlp(original))

        if found:
            found = list(dict.fromkeys(found))
            prefer_video = "/share/r/" in original.lower() or "/share/v/" in original.lower()
            chosen = max(found, key=lambda value: self._facebook_candidate_score(value, prefer_video=prefer_video))
            self.logger.info("facebook normalizer resolved source=%s canonical=%s", url, chosen)
            return chosen
        self.logger.warning("facebook normalizer unresolved source=%s; keep original", url)
        return original

    async def _normalize_share_url(self, item: ParsedInput, cookie_header: str | None) -> str:
        if item.platform == "facebook":
            return await self._normalize_facebook_url(item.url, cookie_header)
        if item.platform not in {"tiktok", "bilibili", "kuaishou", "xiaohongshu", "douyin"}:
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
