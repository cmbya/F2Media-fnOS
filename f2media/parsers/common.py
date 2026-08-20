from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".m3u8", ".m4s", ".ts"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic", ".heif"}

# A URL on one of these hosts is normally a *post/page* URL, not a downloadable
# media resource.  CDN subdomains such as scontent-*.cdninstagram.com, kwimgs.com,
# bilivideo.com, googlevideo.com, xhscdn.com, etc. are intentionally not blocked.
PAGE_HOSTS = {
    "douyin.com", "www.douyin.com", "v.douyin.com",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com",
    "instagram.com", "www.instagram.com",
    "twitter.com", "www.twitter.com", "x.com", "www.x.com",
    "facebook.com", "www.facebook.com", "m.facebook.com",
    "youtube.com", "www.youtube.com", "youtu.be",
    "bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv",
    "kuaishou.com", "www.kuaishou.com", "v.kuaishou.com",
    "xiaohongshu.com", "www.xiaohongshu.com", "xhslink.com", "xhslink.cn",
}


def clean_url(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        if value.startswith(("http://", "https://")):
            return value
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            out = clean_url(item)
            if out:
                return out
        return None
    if isinstance(value, dict):
        for key in (
            "url", "src", "image", "image_url", "imageUrl", "video", "video_url",
            "videoUrl", "masterUrl", "urlDefault", "urlPre",
        ):
            out = clean_url(value.get(key))
            if out:
                return out
    return None


def media_kind(url: str, hint: str | None = None) -> str:
    hint = (hint or "").lower()
    if hint in {"image", "video", "live_video", "video_track", "audio_track"}:
        return hint
    parsed = urlparse(url)
    suffix = Path(parsed.path.lower()).suffix
    if suffix in VIDEO_EXTS:
        return "video"
    if suffix in IMAGE_EXTS:
        return "image"
    low = url.lower()
    if any(x in low for x in ("mime_type=video", "videoplayback", "/video/tos/", ".m4s?", "video_mp4")):
        return "video"
    if any(x in low for x in ("imageview", "imageview2", "format=jpg", "format=webp")):
        return "image"
    return "unknown"


def is_page_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in PAGE_HOSTS


def looks_downloadable(url: str, hint: str | None = None) -> bool:
    if not clean_url(url) or is_page_url(url):
        return False
    kind = media_kind(url, hint)
    if kind != "unknown":
        return True
    # Many signed CDN URLs have no useful extension.  Known media/CDN host markers
    # are accepted; ParseService performs a HEAD/Range content-type probe for other
    # ambiguous URLs before declaring media parsing successful.
    host = (urlparse(url).hostname or "").lower()
    markers = (
        "cdn", "scontent", "kwimgs", "kwaicdn", "bilivideo", "googlevideo",
        "xhscdn", "365yg", "byte", "douyinvod", "tiktokcdn", "tiktokv",
        "fbcdn", "twimg", "akamaized", "muscdn", "ibytedtos",
    )
    return any(marker in host for marker in markers)


def unique_media(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in items:
        url = clean_url(raw.get("url"))
        if not url:
            continue
        kind = str(raw.get("type") or media_kind(url))
        key = (kind, url)
        if key in seen:
            continue
        seen.add(key)
        item = dict(raw)
        item["url"] = url
        item["type"] = kind
        output.append(item)
    return output


def _author(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {"id": "", "name": str(value or ""), "avatar": ""}
    return {
        "id": str(value.get("id") or value.get("uid") or value.get("userId") or value.get("user_id") or ""),
        "name": str(value.get("name") or value.get("nickname") or value.get("nickName") or value.get("author") or ""),
        "avatar": str(value.get("avatar") or value.get("avatar_url") or value.get("face") or ""),
    }


def normalize_external_result(
    payload: Any,
    platform: str,
    source_url: str,
    parser: str,
    *,
    download_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize short_videos/BugPK-like results into F2Media's media schema."""
    if not isinstance(payload, dict):
        raise ValueError("解析器返回值不是对象")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        raise ValueError("解析器没有返回 data 对象")

    media: list[dict[str, Any]] = []
    live_photos: list[dict[str, str]] = []

    raw_type = str(data.get("type") or "").lower()
    video = clean_url(data.get("video_url")) or clean_url(data.get("url"))
    if video and raw_type not in {"image", "gallery", "live"}:
        media.append({"type": "video", "url": video})

    raw_videos = data.get("videos") or data.get("video_backup") or []
    if isinstance(raw_videos, (str, dict)):
        raw_videos = [raw_videos]
    if isinstance(raw_videos, list):
        for value in raw_videos:
            url = clean_url(value)
            if url:
                media.append({"type": "video", "url": url})

    raw_images = data.get("images") or []
    if isinstance(raw_images, (str, dict)):
        raw_images = [raw_images]
    if isinstance(raw_images, list):
        for value in raw_images:
            url = clean_url(value)
            if url:
                media.append({"type": "image", "url": url})

    raw_live = data.get("live_photo") or data.get("live_photos") or []
    if isinstance(raw_live, dict):
        raw_live = [raw_live]
    if isinstance(raw_live, list):
        for pair in raw_live:
            if not isinstance(pair, dict):
                continue
            image_url = clean_url(pair.get("image")) or clean_url(pair.get("image_url"))
            video_url = clean_url(pair.get("video")) or clean_url(pair.get("video_url"))
            if image_url and video_url:
                live_photos.append({"image_url": image_url, "video_url": video_url})
                media.append({"type": "image", "url": image_url, "live_pair": True})
                media.append({"type": "live_video", "url": video_url, "live_pair": True})

    # Some APIs use a single `url` for an image post.
    if raw_type in {"image", "gallery", "live"} and not raw_images:
        image = clean_url(data.get("url"))
        if image:
            media.append({"type": "image", "url": image})

    media = unique_media(media)
    pair_seen: set[tuple[str, str]] = set()
    unique_pairs: list[dict[str, str]] = []
    for pair in live_photos:
        key = (pair["image_url"], pair["video_url"])
        if key not in pair_seen:
            pair_seen.add(key)
            unique_pairs.append(pair)
    live_photos = unique_pairs

    image_count = sum(1 for x in media if x["type"] == "image")
    video_count = sum(1 for x in media if x["type"] in {"video", "video_track"})
    if live_photos:
        media_type = "live_photo"
    elif image_count and video_count:
        media_type = "mixed"
    elif image_count > 1:
        media_type = "gallery"
    elif image_count == 1:
        media_type = "image"
    elif video_count:
        media_type = "video"
    else:
        media_type = raw_type or "unknown"

    title = data.get("title") or data.get("desc") or data.get("description") or ""
    author_value = data.get("author") or data.get("user") or data.get("auther") or ""
    result = {
        "ok": bool(media),
        "platform": platform,
        "source_url": source_url,
        "parser": parser,
        "title": str(title).strip(),
        "author": _author(author_value),
        "cover_url": clean_url(data.get("cover")) or clean_url(data.get("cover_url")),
        "media_type": media_type,
        "media": media,
        "live_photos": live_photos,
        "counts": {"videos": video_count, "images": image_count, "live_photos": len(live_photos)},
    }
    if download_plan:
        result["download_plan"] = download_plan
    return result


def has_downloadable_media(result: dict[str, Any]) -> bool:
    return bool(result.get("media")) and bool(result.get("ok"))


def safe_title(value: str | None, fallback: str = "无标题") -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", " ", (value or "").strip())
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value or fallback)[:180]
