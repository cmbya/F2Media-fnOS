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


def _first_string(value: Any, keys: tuple[str, ...]) -> str:
    if isinstance(value, dict):
        for key in keys:
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for child in value.values():
            found = _first_string(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_string(child, keys)
            if found:
                return found
    return ""


def _valid_url(value: Any) -> str:
    return clean_url(value) if isinstance(value, str) else ""


def _best_video_variant(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    candidates: list[tuple[int, str]] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        url = _valid_url(row.get("url") or row.get("src"))
        if not url:
            continue
        ctype = str(row.get("content_type") or row.get("mime_type") or row.get("type") or "").lower()
        if ctype and "mp4" not in ctype and not urlparse(url).path.lower().endswith(".mp4"):
            continue
        try:
            bitrate = int(row.get("bitrate") or row.get("bit_rate") or 0)
        except (TypeError, ValueError):
            bitrate = 0
        candidates.append((bitrate, url))
    return max(candidates, default=(0, ""), key=lambda x: x[0])[1]


def _typed_media(value: Any) -> list[dict[str, Any]]:
    """Prefer typed media objects so thumbnails/covers are not downloaded as content."""
    found: list[dict[str, Any]] = []
    if isinstance(value, list):
        for child in value:
            found.extend(_typed_media(child))
        return found
    if not isinstance(value, dict):
        return found

    kind = str(value.get("type") or value.get("media_type") or value.get("__typename") or "").lower()
    if any(token in kind for token in ("video", "animated_gif", "animatedgif", "gif")):
        best = _best_video_variant(value.get("variants") or value.get("video_variants"))
        direct = _valid_url(
            value.get("video_url") or value.get("playable_url") or value.get("playable_url_quality_hd")
            or value.get("url") or value.get("src")
        )
        url = best or direct
        if url:
            found.append({"type": "video", "url": url})
        # Do not recurse through preview_image/thumbnail for a video object.
        for key, child in value.items():
            if key.lower() in {"preview_image", "preview_image_url", "thumbnail", "thumbnail_url", "image", "photo"}:
                continue
            if key.lower() in {"variants", "video_variants", "url", "video_url", "playable_url", "playable_url_quality_hd", "src"}:
                continue
            found.extend(_typed_media(child))
        return found

    if any(token in kind for token in ("photo", "image", "picture")):
        direct = _valid_url(
            value.get("image_url") or value.get("media_url_https") or value.get("media_url")
            or value.get("url") or value.get("src")
        )
        if direct:
            found.append({"type": "image", "url": direct})
        for key, child in value.items():
            if key.lower() in {"url", "image_url", "media_url_https", "media_url", "src", "thumbnail", "thumbnail_url"}:
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
        # Source/permalink URLs are metadata, not media bytes.
        if host in {"x.com", "twitter.com", "www.x.com", "www.twitter.com", "facebook.com", "www.facebook.com", "m.facebook.com"}:
            return found
        joined = ".".join(path)
        hint = ""
        if any(k in joined for k in ("video", "playable", "variant", "stream", "mp4", "gif")):
            hint = "video"
        elif any(k in joined for k in ("photo", "image", "picture")):
            hint = "image"
        # Generic fallback deliberately ignores preview/thumbnail/cover keys; videos
        # must not cause their cover image to be downloaded as a content image.
        if any(k in joined for k in ("preview", "thumbnail", "cover")):
            return found
        if not any(k in joined for k in ("url", "src", "source", "media", "image", "photo", "video", "stream", "playable", "variant")):
            return found
        found.append({"type": media_kind(url, hint), "url": url})
    return found


def _media_from_payload(payload: Any) -> list[dict[str, Any]]:
    typed = unique_media(_typed_media(payload))
    return typed if typed else unique_media(_collect_urls(payload))

def normalize_x_cli(payload: Any, source_url: str) -> dict[str, Any]:
    media = _media_from_payload(payload)
    title = _first_string(payload, ("text", "full_text", "title", "description", "caption"))
    author = _first_string(payload, ("username", "screen_name", "name", "author_name"))
    images = sum(1 for x in media if x["type"] == "image")
    videos = sum(1 for x in media if x["type"] != "image")
    return {
        "ok": bool(media), "platform": "twitter", "source_url": source_url,
        "parser": "x-cli", "title": title,
        "author": {"id": "", "name": author, "avatar": ""},
        "cover_url": next((x["url"] for x in media if x["type"] == "image"), None),
        "media_type": "mixed" if images and videos else ("gallery" if images > 1 else "image" if images else "video"),
        "media": media, "live_photos": [],
        "counts": {"videos": videos, "images": images, "live_photos": 0},
    }


def normalize_facebook_cli(payload: Any, source_url: str) -> dict[str, Any]:
    media = _media_from_payload(payload)
    title = _first_string(payload, ("text", "message", "title", "description", "caption"))
    author = _first_string(payload, ("author_name", "username", "handle", "name"))
    images = sum(1 for x in media if x["type"] == "image")
    videos = sum(1 for x in media if x["type"] != "image")
    return {
        "ok": bool(media), "platform": "facebook", "source_url": source_url,
        "parser": "facebook-cli", "title": title,
        "author": {"id": "", "name": author, "avatar": ""},
        "cover_url": next((x["url"] for x in media if x["type"] == "image"), None),
        "media_type": "mixed" if images and videos else ("gallery" if images > 1 else "image" if images else "video"),
        "media": media, "live_photos": [],
        "counts": {"videos": videos, "images": images, "live_photos": 0},
    }
