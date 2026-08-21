from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from ..core.cookie_format import cookie_header_for_engine
from .common import clean_url, normalize_external_result

UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
UA_MOBILE = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Mobile Safari/537.36"
)


def _headers(cookie: str | None, *, mobile: bool = False) -> dict[str, str]:
    headers = {
        "User-Agent": UA_MOBILE if mobile else UA_DESKTOP,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    }
    value = cookie_header_for_engine(cookie)
    if value:
        headers["Cookie"] = value
    return headers


def _script_json(html: str, name: str) -> Any | None:
    patterns = [
        rf"(?:window\.)?{re.escape(name)}\s*=\s*(.*?)</script>",
        rf"<script[^>]*>\s*(?:window\.)?{re.escape(name)}\s*=\s*(.*?)</script>",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I | re.S)
        if not match:
            continue
        raw = match.group(1).strip().rstrip(";")
        raw = re.sub(r"\bundefined\b", "null", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # INIT_STATE occasionally contains doubly escaped JSON fragments.  Keep the
            # port intentionally conservative rather than executing JavaScript.
            try:
                return json.loads(raw.encode("utf-8").decode("unicode_escape"))
            except Exception:
                continue
    return None


def _find_dict_with_key(value: Any, key: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if key in value:
            return value
        for child in value.values():
            found = _find_dict_with_key(child, key)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_dict_with_key(child, key)
            if found:
                return found
    return None


def _find_first_photo(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        photo = value.get("photo")
        if isinstance(photo, dict):
            return photo
        for child in value.values():
            found = _find_first_photo(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_first_photo(child)
            if found:
                return found
    return None


def _xhs_image_url(raw: Any) -> str | None:
    url = clean_url(raw)
    if not url:
        return None
    # Port of short_videos' processImageUrl: prefer a raw, full-size xhscdn URL.
    m = re.search(r"/oss-sg/([A-Za-z0-9_]+)/([A-Za-z0-9]+)!", url)
    if m and not re.fullmatch(r"[a-f0-9]{32}|\d+", m.group(1)):
        return f"https://sns-img-hw.xhscdn.com/oss-sg/{m.group(1)}/{m.group(2)}?imageView2/2/w/0/format/jpg"
    m = re.search(r"/(notes_pre_post|spectrum|notes_uhdr)/([A-Za-z0-9]+)", url)
    if m:
        return f"https://sns-img-hw.xhscdn.com/{m.group(1)}/{m.group(2)}?imageView2/2/w/0/format/jpg"
    return url


def _stream_url(stream: dict[str, Any]) -> str | None:
    return clean_url(stream.get("masterUrl")) or clean_url(stream.get("backupUrls"))


def _stream_bitrate(stream: dict[str, Any]) -> int:
    for key in ("avgBitrate", "videoBitrate", "bitrate", "bitRate"):
        try:
            return int(stream.get(key) or 0)
        except (TypeError, ValueError):
            pass
    return 0


class ShortVideosLocalParser:
    """Python port of the useful parser logic in jiuhunwl/short_videos.

    No PHP server is embedded.  Only platform extraction logic is kept locally.
    """

    SUPPORTED = {"douyin", "kuaishou", "xiaohongshu", "bilibili"}

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    async def parse(self, platform: str, url: str, cookie: str | None = None) -> dict[str, Any]:
        if platform not in self.SUPPORTED:
            raise ValueError(f"short_videos 本地逻辑不支持 {platform}")
        method = getattr(self, f"_parse_{platform}")
        payload = await method(url, cookie)
        result = normalize_external_result(payload, platform, url, "short_videos-local")
        if not result["ok"]:
            raise RuntimeError("short_videos 本地逻辑没有返回可下载媒体")
        return result

    async def _client_get(self, url: str, cookie: str | None, *, mobile: bool = False) -> httpx.Response:
        async with httpx.AsyncClient(
            headers=_headers(cookie, mobile=mobile), follow_redirects=True, timeout=self.timeout
        ) as client:
            return await client.get(url)

    async def _parse_kuaishou(self, url: str, cookie: str | None) -> dict[str, Any]:
        response = await self._client_get(url, cookie)
        response.raise_for_status()
        html = response.text
        state = _script_json(html, "INIT_STATE")
        photo = _find_first_photo(state) if state is not None else None
        if not photo:
            apollo = _script_json(html, "__APOLLO_STATE__")
            if isinstance(apollo, dict):
                content_id = self._kuaishou_content_id(str(response.url))
                default = apollo.get("defaultClient") or {}
                if isinstance(default, dict) and content_id:
                    candidate = default.get(f"VisionVideoDetailPhoto:{content_id}")
                    if isinstance(candidate, dict):
                        video_url = clean_url(candidate.get("photoUrl"))
                        return {
                            "code": 200,
                            "data": {
                                "type": "video" if video_url else "unknown",
                                "title": candidate.get("caption") or "",
                                "url": video_url,
                            },
                        }
            raise RuntimeError("未从快手页面找到 INIT_STATE/APOLLO_STATE 媒体数据")

        title = str(photo.get("caption") or "")
        author = {
            "name": str(photo.get("userName") or ""),
            "avatar": str(photo.get("headUrl") or ""),
        }
        atlas = (((photo.get("ext_params") or {}).get("atlas") or {}).get("list") or [])
        if isinstance(atlas, list) and atlas:
            images = [f"https://tx2.a.yximgs.com/{x}" for x in atlas if isinstance(x, str) and x]
            return {"code": 200, "data": {"type": "image", "title": title, "author": author, "images": images}}

        if photo.get("photoType") == "SINGLE_PICTURE" or photo.get("singlePicture") is True:
            covers = photo.get("coverUrls") or []
            image = clean_url(covers[0]) if isinstance(covers, list) and covers else None
            if image:
                return {"code": 200, "data": {"type": "image", "title": title, "author": author, "url": image, "images": [image]}}

        main = photo.get("mainMvUrls") or []
        video = clean_url(main[0]) if isinstance(main, list) and main else None
        if not video:
            manifest = photo.get("manifest") or {}
            try:
                video = clean_url(manifest["adaptationSet"][0]["representation"][0].get("url"))
            except (KeyError, IndexError, TypeError, AttributeError):
                pass
        if video:
            return {"code": 200, "data": {"type": "video", "title": title, "author": author, "url": video}}
        raise RuntimeError("快手页面中没有找到图片或视频资源")

    @staticmethod
    def _kuaishou_content_id(url: str) -> str | None:
        m = re.search(r"/(?:short-video|long-video|photo)/([^?/#]+)", url)
        return m.group(1) if m else None

    async def _parse_xiaohongshu(self, url: str, cookie: str | None) -> dict[str, Any]:
        # Preserve the real note URL even when xhslink ultimately redirects to a
        # website-login/captcha wrapper. That wrapper carries the original work URL
        # in its redirectPath query parameter.
        async with httpx.AsyncClient(headers=_headers(cookie), follow_redirects=False, timeout=self.timeout) as client:
            current = url.replace("xhs.com", "xhslink.com")
            resolved = current
            for _ in range(8):
                response = await client.get(current)
                location = response.headers.get("location")
                if location:
                    next_url = str(httpx.URL(current).join(location))
                    work_url = self._xhs_redirect_work_url(next_url)
                    if work_url:
                        resolved = work_url
                        current = work_url
                        break
                    if self._xhs_id(next_url):
                        resolved = next_url
                    current = next_url
                    continue
                work_url = self._xhs_redirect_work_url(str(response.url))
                resolved = work_url or current
                break
        note_id = self._xhs_id(resolved) or self._xhs_id(current)
        if not note_id:
            raise RuntimeError("小红书短链跳转后仍无法提取作品 ID")
        response = await self._client_get(resolved, cookie)
        if "website-login/captcha" in str(response.url):
            raise RuntimeError("小红书返回验证码页面，请更新 Cookie 后重试")
        note = self._xhs_note(response.text, note_id)
        if not note:
            # Retry once with the mobile UA, matching short_videos' current fallback.
            response = await self._client_get(resolved, cookie, mobile=True)
            note = self._xhs_note(response.text, note_id)
        if not note:
            raise RuntimeError("未从小红书 __INITIAL_STATE__ 找到笔记数据")
        return {"code": 200, "data": self._format_xhs_note(note)}

    @staticmethod
    def _xhs_redirect_work_url(url: str) -> str | None:
        if "website-login/captcha" not in url:
            return None
        try:
            values = parse_qs(urlparse(url).query).get("redirectPath") or []
        except Exception:
            return None
        for value in values:
            candidate = unquote(str(value)).strip()
            if candidate.startswith(("http://", "https://")) and ShortVideosLocalParser._xhs_id(candidate):
                return candidate
        return None

    @staticmethod
    def _xhs_id(url: str) -> str | None:
        for pattern in (
            r"/discovery/item/([A-Za-z0-9]+)", r"/explore/([A-Za-z0-9]+)",
            r"/item/([A-Za-z0-9]+)", r"/note/([A-Za-z0-9]+)",
        ):
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _xhs_note(html: str, note_id: str) -> dict[str, Any] | None:
        state = _script_json(html, "__INITIAL_STATE__")
        if not isinstance(state, dict):
            return None
        try:
            note = state["note"]["noteDetailMap"][note_id]["note"]
            if isinstance(note, dict):
                return note
        except (KeyError, TypeError):
            pass
        try:
            note = state["noteData"]["data"]["noteData"]
            if isinstance(note, dict):
                return note
        except (KeyError, TypeError):
            pass
        # Site shapes change; a recursive note with imageList/user is a safe structural fallback.
        def walk(value: Any) -> dict[str, Any] | None:
            if isinstance(value, dict):
                if isinstance(value.get("imageList"), list) and isinstance(value.get("user"), dict):
                    return value
                for child in value.values():
                    found = walk(child)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = walk(child)
                    if found:
                        return found
            return None
        return walk(state)

    @staticmethod
    def _format_xhs_note(note: dict[str, Any]) -> dict[str, Any]:
        raw_type = str(note.get("type") or "unknown")
        result: dict[str, Any] = {
            "type": "image" if raw_type == "normal" else raw_type,
            "title": str(note.get("title") or note.get("desc") or ""),
            "author": {
                "name": str((note.get("user") or {}).get("nickname") or (note.get("user") or {}).get("nickName") or ""),
                "id": str((note.get("user") or {}).get("userId") or ""),
                "avatar": str((note.get("user") or {}).get("avatar") or ""),
            },
            "images": [],
            "live_photo": [],
        }
        if result["type"] == "video":
            media = (((note.get("video") or {}).get("media") or {}).get("stream") or {})
            # User requirement: H.264 compatibility first, then highest bitrate. H.265 is fallback.
            candidates: list[tuple[int, int, str]] = []
            for preference, codec in ((2, "h264"), (1, "h265")):
                streams = media.get(codec) or []
                if isinstance(streams, list):
                    for stream in streams:
                        if not isinstance(stream, dict):
                            continue
                        u = _stream_url(stream)
                        if u:
                            candidates.append((preference, _stream_bitrate(stream), u))
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            if candidates:
                result["url"] = candidates[0][2]
                result["video_backup"] = [x[2] for x in candidates[1:]]
            else:
                key = ((note.get("video") or {}).get("consumer") or {}).get("originVideoKey")
                if key:
                    result["url"] = f"https://sns-video-bd.xhscdn.com/{key}"

        image_list = note.get("imageList") or []
        if isinstance(image_list, list):
            for image in image_list:
                if not isinstance(image, dict):
                    continue
                image_url = _xhs_image_url(image.get("url") or image.get("urlDefault") or image.get("urlPre"))
                if image_url:
                    result["images"].append(image_url)
                streams = image.get("stream") or {}
                live = None
                for codec in ("h264", "h265"):
                    rows = streams.get(codec) or [] if isinstance(streams, dict) else []
                    if isinstance(rows, list) and rows:
                        live = _stream_url(rows[0]) if isinstance(rows[0], dict) else clean_url(rows[0])
                        if live:
                            break
                if image_url and live:
                    result["live_photo"].append({"image": image_url, "video": live})
        if result["live_photo"]:
            result["type"] = "live"
        return result

    async def _parse_bilibili(self, url: str, cookie: str | None) -> dict[str, Any]:
        response = await self._client_get(url, cookie)
        final_url = str(response.url)
        bvid_match = re.search(r"/video/(BV[0-9A-Za-z]+)", final_url)
        if not bvid_match:
            raise RuntimeError("无法从 Bilibili 链接提取 BV 号")
        bvid = bvid_match.group(1)
        headers = _headers(cookie)
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=self.timeout) as client:
            view = await client.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid})
            view.raise_for_status()
            obj = view.json()
            if obj.get("code") != 0 or not isinstance(obj.get("data"), dict):
                raise RuntimeError(f"Bilibili view API 失败: {obj.get('message') or obj.get('code')}")
            info = obj["data"]
            videos: list[dict[str, Any]] = []
            for index, page in enumerate(info.get("pages") or []):
                if not isinstance(page, dict) or not page.get("cid"):
                    continue
                play = await client.get(
                    "https://api.bilibili.com/x/player/playurl",
                    params={
                        "otype": "json", "fnver": 0, "fnval": 3, "player": 3,
                        "qn": 112, "bvid": bvid, "cid": page["cid"],
                        "platform": "html5", "high_quality": 1,
                    },
                )
                play.raise_for_status()
                pdata = play.json().get("data") or {}
                rows = pdata.get("durl") or []
                video = clean_url(rows[0]) if isinstance(rows, list) and rows else None
                if video:
                    videos.append({"url": video, "title": page.get("part") or f"P{index + 1}", "index": index + 1})
            if not videos:
                raise RuntimeError("Bilibili playurl API 未返回媒体 URL")
            owner = info.get("owner") or {}
            return {
                "code": 200,
                "data": {
                    "type": "video",
                    "title": info.get("title") or "",
                    "cover": info.get("pic") or "",
                    "author": {"name": owner.get("name") or "", "id": owner.get("mid") or "", "avatar": owner.get("face") or ""},
                    "url": videos[0]["url"],
                    "videos": videos,
                },
            }

    async def _parse_douyin(self, url: str, cookie: str | None) -> dict[str, Any]:
        # short_videos' Douyin algorithm is intentionally only a secondary path.  Prefer
        # conservative extraction from SSR/page JSON; the dedicated douyin_parse adapter
        # runs first and owns current signature logic.
        response = await self._client_get(url, cookie)
        response.raise_for_status()
        html = response.text
        candidates: list[Any] = []
        for name in ("_ROUTER_DATA", "__INITIAL_STATE__", "RENDER_DATA"):
            value = _script_json(html, name)
            if value is not None:
                candidates.append(value)
        # RENDER_DATA is sometimes URI encoded; parse a large JSON script if present.
        for pattern in (r'<script[^>]+id="RENDER_DATA"[^>]*>(.*?)</script>', r'"aweme_detail"\s*:\s*(\{.*?\})'):
            match = re.search(pattern, html, re.I | re.S)
            if match:
                raw = httpx.URL("https://x.invalid/?d=" + match.group(1)).params.get("d", match.group(1))
                try:
                    candidates.append(json.loads(raw))
                except Exception:
                    pass
        for obj in candidates:
            detail = self._find_douyin_detail(obj)
            if detail:
                payload = self._format_douyin_detail(detail)
                if payload:
                    return {"code": 200, "data": payload}
        raise RuntimeError("short_videos 本地抖音逻辑未找到可用作品数据")

    @staticmethod
    def _find_douyin_detail(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            if (value.get("aweme_id") or value.get("awemeId")) and (value.get("video") or value.get("images")):
                return value
            for child in value.values():
                found = ShortVideosLocalParser._find_douyin_detail(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = ShortVideosLocalParser._find_douyin_detail(child)
                if found:
                    return found
        return None

    @staticmethod
    def _format_douyin_detail(detail: dict[str, Any]) -> dict[str, Any] | None:
        author = detail.get("author") or {}
        title = detail.get("desc") or detail.get("title") or ""
        images = detail.get("images") or []
        if isinstance(images, list) and images:
            static: list[str] = []
            live: list[dict[str, str]] = []
            for image in images:
                if not isinstance(image, dict):
                    continue
                image_url = clean_url(image.get("url_list")) or clean_url(image.get("origin_url_list")) or clean_url(image.get("download_url_list")) or clean_url(image)
                video_obj = image.get("video") or {}
                video_url = clean_url((video_obj.get("play_addr") or {}).get("url_list")) or clean_url((video_obj.get("download_addr") or {}).get("url_list"))
                if image_url:
                    static.append(image_url)
                if image_url and video_url:
                    live.append({"image": image_url, "video": video_url})
            return {"type": "live" if live else "image", "title": title, "author": author, "images": static, "live_photo": live}
        video = detail.get("video") or {}
        url = clean_url((video.get("play_addr") or {}).get("url_list")) or clean_url((video.get("download_addr") or {}).get("url_list"))
        if url:
            return {"type": "video", "title": title, "author": author, "url": url}
        return None
