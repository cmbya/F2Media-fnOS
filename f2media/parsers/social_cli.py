from __future__ import annotations

import json
import re
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
            if child and not child.startswith(("http://", "https://", "fb://")):
                return child
    return ""


def _url(value: Any) -> str:
    return clean_url(value) if isinstance(value, str) else ""


def _quality_score(stream: dict[str, Any]) -> tuple[int, int, int, int]:
    """Prefer highest MP4 video stream, then largest dimensions/quality label."""
    mime = str(stream.get("mime") or stream.get("mime_type") or stream.get("content_type") or "").lower()
    url = _url(stream.get("url"))
    mp4 = 1 if ("mp4" in mime or urlparse(url).path.lower().endswith(".mp4")) else 0
    try:
        height = int(stream.get("height") or 0)
    except (TypeError, ValueError):
        height = 0
    try:
        width = int(stream.get("width") or 0)
    except (TypeError, ValueError):
        width = 0
    quality = str(stream.get("quality") or "").lower()
    qnum = 0
    m = re.search(r"(\d{3,4})", quality)
    if m:
        qnum = int(m.group(1))
    elif "hd" in quality:
        qnum = 1080
    elif "sd" in quality:
        qnum = 480
    return mp4, height, width, qnum


def _x_variant_score(variant: dict[str, Any]) -> tuple[int, int]:
    """Prefer direct MP4 variants, then the highest bitrate."""
    url = _url(variant.get("url"))
    content_type = str(variant.get("content_type") or variant.get("mime_type") or "").lower()
    mp4 = 1 if ("mp4" in content_type or urlparse(url).path.lower().endswith(".mp4")) else 0
    try:
        bitrate = int(variant.get("bitrate") or variant.get("bit_rate") or 0)
    except (TypeError, ValueError):
        bitrate = 0
    return mp4, bitrate


def _best_x_variant(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    candidates: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, dict) or not _url(row.get("url")):
            continue
        content_type = str(row.get("content_type") or row.get("mime_type") or "").lower()
        # Skip HLS playlists when a direct MP4 variant is available.  If no MP4
        # exists, the scoring still permits the best remaining URL as fallback.
        candidates.append(row)
    if not candidates:
        return ""
    best = max(candidates, key=_x_variant_score)
    return _url(best.get("url"))


def _facebook_stream_media(payload: Any) -> list[dict[str, Any]]:
    """Normalize facebook-cli Video.Streams into one best playable video.

    facebook-cli v0.3.0 exposes reels/videos as a Video record with
    `streams: [{quality,mime,width,height,url,is_audio}]`.  Older F2Media
    normalization only walked generic URL-shaped fields and could miss this
    typed stream list.  Prefer the best non-audio stream and attach the best
    audio stream when Facebook exposes one separately.
    """
    video_streams: list[dict[str, Any]] = []
    audio_streams: list[dict[str, Any]] = []

    for row in _walk(payload):
        streams = row.get("streams")
        if not isinstance(streams, list):
            continue
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            url = _url(stream.get("url"))
            if not url:
                continue
            if bool(stream.get("is_audio")):
                audio_streams.append({**stream, "url": url})
            else:
                video_streams.append({**stream, "url": url})

    if not video_streams:
        return []

    best_video = max(video_streams, key=_quality_score)
    item: dict[str, Any] = {"type": "video", "url": best_video["url"]}

    if audio_streams:
        # Audio entries normally have no useful dimensions; MP4/M4A preference
        # plus the original ordering is sufficient for a parser result.  The
        # downloader may use audio_url when a separate track is required.
        best_audio = max(audio_streams, key=_quality_score)
        item["audio_url"] = best_audio["url"]

    return [item]


def _typed_media(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, list):
        for child in value:
            found.extend(_typed_media(child))
        return found
    if not isinstance(value, dict):
        return found

    kind = str(value.get("type") or value.get("media_type") or value.get("__typename") or "").lower()
    if any(token in kind for token in ("video", "animated_gif", "animatedgif", "gif", "reel")):
        # X/Twitter exposes videos as a variants list.  Keep the highest-bitrate
        # direct MP4 and never turn preview_image into a downloadable image.
        variant = _best_x_variant(value.get("variants") or value.get("video_variants"))
        direct = variant or _url(
            value.get("video_url")
            or value.get("playable_url")
            or value.get("playable_url_quality_hd")
            or value.get("browser_native_hd_url")
            or value.get("browser_native_sd_url")
            or value.get("url")
            or value.get("src")
        )
        if direct:
            found.append({"type": "video", "url": direct})
        for key, child in value.items():
            if str(key).lower() in {
                "preview_image", "preview_image_url", "thumbnail", "thumbnail_url",
                "thumb_url", "image", "photo", "cover", "cover_url",
                "url", "video_url", "playable_url", "playable_url_quality_hd",
                "browser_native_hd_url", "browser_native_sd_url", "src", "streams",
                "variants", "video_variants",
            }:
                continue
            found.extend(_typed_media(child))
        return found

    if any(token in kind for token in ("photo", "image", "picture")):
        direct = _url(
            value.get("full_url")
            or value.get("image_url")
            or value.get("media_url_https")
            or value.get("media_url")
            or value.get("url")
            or value.get("src")
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

    # facebook-cli Photo records do not need a `type` field.
    full_url = _url(value.get("full_url"))
    if full_url:
        found.append({"type": "image", "url": full_url})

    for key, child in value.items():
        if str(key).lower() == "streams":
            continue
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
        if host in {
            "x.com", "twitter.com", "www.x.com", "www.twitter.com",
            "facebook.com", "www.facebook.com", "m.facebook.com",
        }:
            return found
        joined = ".".join(path)
        if any(k in joined for k in ("preview", "thumbnail", "thumb", "cover", "avatar")):
            return found
        hint = ""
        if any(k in joined for k in ("video", "playable", "variant", "stream", "mp4", "gif")):
            hint = "video"
        elif any(k in joined for k in ("photo", "image", "picture", "full_url")):
            hint = "image"
        if not any(k in joined for k in ("url", "src", "source", "media", "image", "photo", "video", "stream", "playable", "variant")):
            return found
        found.append({"type": media_kind(url, hint), "url": url})
    return found


def _media_from_payload(payload: Any, *, facebook: bool = False) -> list[dict[str, Any]]:
    # Only Facebook should interpret a generic `streams` key as facebook-cli's
    # Video.Streams schema.  X/Twitter has its own typed `variants` schema.
    if facebook:
        streams = _facebook_stream_media(payload)
        if streams:
            return streams
    typed = unique_media(_typed_media(payload))
    return typed if typed else unique_media(_collect_urls(payload))


def normalize_x_cli(payload: Any, source_url: str) -> dict[str, Any]:
    media = _media_from_payload(payload, facebook=False)
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


def normalize_facebook_cli(payload: Any, source_url: str) -> dict[str, Any]:
    media = _media_from_payload(payload, facebook=True)
    title = _first_string(payload, ("title", "description", "caption", "text", "message"))
    author = _first_string(payload, ("owner_name", "author_name", "username", "handle", "name"))
    images = sum(1 for x in media if x.get("type") == "image")
    videos = sum(1 for x in media if x.get("type") != "image")
    return {
        "ok": bool(media), "platform": "facebook", "source_url": source_url,
        "parser": "facebook-cli", "title": title,
        "author": {"id": "", "name": author, "avatar": ""},
        # A video/reel thumbnail is metadata only and must not become a media item.
        "cover_url": None if videos else next((x["url"] for x in media if x.get("type") == "image"), None),
        "media_type": "mixed" if images and videos else ("gallery" if images > 1 else "image" if images else "video"),
        "media": media, "live_photos": [],
        "counts": {"videos": videos, "images": images, "live_photos": 0},
    }
