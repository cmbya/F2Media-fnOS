from __future__ import annotations

import html
import re
from urllib.parse import urlparse

import httpx

from .common import clean_url

_FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "mbasic.facebook.com"}
_META_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:url["\']', re.I),
    re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', re.I),
    re.compile(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']', re.I),
]


def is_facebook_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host in _FACEBOOK_HOSTS or host.endswith(".facebook.com")
    except Exception:
        return False


def _usable(url: str) -> bool:
    if not url or not is_facebook_url(url):
        return False
    path = urlparse(url).path.lower()
    return not any(x in path for x in ("/login", "/checkpoint", "/recover"))


async def resolve_facebook_url(url: str, cookie_header: str | None = None) -> str:
    """Resolve Facebook /share/* wrappers. Called only for platform=facebook."""
    if not is_facebook_url(url):
        return url
    path = urlparse(url).path.lower()
    if "/share/" not in path:
        return url
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/143 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20, headers=headers) as client:
            response = await client.get(url)
            final = clean_url(str(response.url)) or url
            if _usable(final) and "/share/" not in urlparse(final).path.lower():
                return final
            body = response.text[:2_000_000]
            for pattern in _META_PATTERNS:
                match = pattern.search(body)
                if not match:
                    continue
                candidate = clean_url(html.unescape(match.group(1)))
                if candidate and _usable(candidate) and "/share/" not in urlparse(candidate).path.lower():
                    return candidate
    except Exception:
        return url
    return url
