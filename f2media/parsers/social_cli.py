from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from .common import clean_url, media_kind, unique_media


def parse_cli_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows if rows else None


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _first_string(value: Any, keys: tuple[str, ...]) -> str:
    wanted = set(keys)
    for row in _walk(value):
        for key, child in row.items():
            if str(key).lower() not in wanted or not isinstance(child, str):
                continue
            child = child.strip()
            if child and not child.startswith(("http://", "https://")):
                return child
    return ""


def _url(value: Any) -> str:
    return clean_url(value) if isinstance(value, str) else ""


def _variant_score(variant: dict[str, Any]) -> tuple[int, int]:
    url = _url(variant.get("url"))
    content_type = str(variant.get("content_type") or variant.get("mime_type") or "").lower()
    mp4 = 1 if ("mp4" in content_type or urlparse(url).path.lower().endswith(".mp4")) else 0
    try:
        bitrate = int(variant.get("bitrate") or variant.get("bit_rate") or 0)
    except (TypeError, ValueError):
        bitrate = 0
    return mp4, bitrate


def _best_variant(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    candidates = [row for row in value if isinstance(row, dict) and _url(row.get("url"))]
    if not candidates:
        return ""
    return _url(max(candidates, key=_variant_score).get("url"))


def _typed_media(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, list):
        for child in value:
            found.extend(_typed_media(child))
        return found
    if not isinstance(value, dict):
        return found

    kind = str(value.get("type") or value.get("media_type") or value.get("__typename") or "").lower()
    if any(token in kind for token in ("video", "animated_gif", "animatedgif", "gif")):
        direct = _best_variant(value.get("variants") or value.get("video_variants")) or _url(
            value.get("video_url") or value.get("url") or value.get("src")
        )
        if direct:
            found.append({"type": "video", "url": direct})
        for key, child in value.items():
            if str(key).lower() in {
                "preview_image", "preview_image_url", "thumbnail", "thumbnail_url",
                "thumb_url", "image", "photo", "cover", "cover_url",
                "url", "video_url", "src", "variants", "video_variants",
            }:
                continue
            found.extend(_typed_media(child))
        return found

    if any(token in kind for token in ("photo", "image", "picture")):
        direct = _url(
            value.get("full_url") or value.get("image_url") or value.get("media_url_https")
            or value.get("media_url") or value.get("url") or value.get("src")
        )
        if direct:
            found.append({"type": "image", "url": direct})
        for key, child in value.items():
            if str(key).lower() in {
                "url", "full_url", "image_url", "media_url_https", "media_url",
                "src", "thumbnail", "thumbnail_url", "thumb_url", "cover_url",
            }:
                continue
            found.extend(_typed_media(child))
        return found

    for child in value.values():
        found.extend(_typed_media(child))
    return found


def _collect_urls(value: Any, path: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_collect_urls(child, (*path, str(key).lower())))
    elif isinstance(value, list):
        for child in value:
            found.extend(_collect_urls(child, path))
    elif isinstance(value, str):
        url = clean_url(value)
        if not url:
            return found
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
        if host in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}:
            return found
        joined = ".".join(path)
        if any(k in joined for k in ("preview", "thumbnail", "thumb", "cover", "avatar")):
            return found
        hint = ""
        if any(k in joined for k in ("video", "variant", "stream", "mp4", "gif")):
            hint = "video"
        elif any(k in joined for k in ("photo", "image", "picture", "full_url")):
            hint = "image"
        if not any(k in joined for k in ("url", "src", "source", "media", "image", "photo", "video", "stream", "variant")):
            return found
        found.append({"type": media_kind(url, hint), "url": url})
    return found


def normalize_x_cli(payload: Any, source_url: str) -> dict[str, Any]:
    typed = unique_media(_typed_media(payload))
    media = typed if typed else unique_media(_collect_urls(payload))
    title = _first_string(payload, ("text", "full_text", "title", "description", "caption"))
    author = _first_string(payload, ("username", "screen_name", "name", "author_name"))
    images = sum(1 for x in media if x.get("type") == "image")
    videos = sum(1 for x in media if x.get("type") != "image")
    return {
        "ok": bool(media), "platform": "twitter", "source_url": source_url,
        "parser": "x-cli", "title": title,
        "author": {"id": "", "name": author, "avatar": ""},
        "cover_url": next((x["url"] for x in media if x.get("type") == "image"), None),
        "media_type": "mixed" if images and videos else ("gallery" if images > 1 else "image" if images else "video"),
        "media": media, "live_photos": [],
        "counts": {"videos": videos, "images": images, "live_photos": 0},
    }
