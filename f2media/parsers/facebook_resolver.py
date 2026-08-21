from __future__ import annotations

import html
import logging
import re
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

import httpx

from ..core.cookie_format import cookie_header_for_engine
from .common import clean_url

logger = logging.getLogger("f2media")

_FACEBOOK_HOSTS = {
    "facebook.com", "www.facebook.com", "m.facebook.com", "mbasic.facebook.com",
    "web.facebook.com", "touch.facebook.com",
}
_META_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\\\']og:url["\\\'][^>]+content=["\\\']([^"\\\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\\\']([^"\\\']+)["\\\'][^>]+property=["\\\']og:url["\\\']', re.I),
    re.compile(r'<link[^>]+rel=["\\\']canonical["\\\'][^>]+href=["\\\']([^"\\\']+)', re.I),
    re.compile(r'<link[^>]+href=["\\\']([^"\\\']+)["\\\'][^>]+rel=["\\\']canonical["\\\']', re.I),
]
_URL_PATTERNS = [
    re.compile(r'https?://(?:www\.|m\.|mbasic\.|web\.|touch\.)?facebook\.com/reel/\d+[^"<\s]*', re.I),
    re.compile(r'https?://(?:www\.|m\.|mbasic\.|web\.|touch\.)?facebook\.com/groups/[^/?"<\s]+/(?:posts|permalink)/\d+[^"<\s]*', re.I),
    re.compile(r'https?://(?:www\.|m\.|mbasic\.|web\.|touch\.)?facebook\.com/[^/?"<\s]+/(?:posts|videos)/[^?"<\s]+', re.I),
    re.compile(r'https?://(?:www\.|m\.|mbasic\.|web\.|touch\.)?facebook\.com/(?:story|permalink)\.php\?[^"<\s]+', re.I),
]


def is_facebook_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host in _FACEBOOK_HOSTS or host.endswith(".facebook.com")
    except Exception:
        return False


def _to_www(url: str) -> str:
    try:
        parsed = urlparse(url)
        if not is_facebook_url(url):
            return url
        return urlunparse(parsed._replace(netloc="www.facebook.com", scheme="https"))
    except Exception:
        return url


def normalize_known_facebook_url(url: str) -> str:
    """Normalize URL shapes that contain enough information without a network request."""
    if not is_facebook_url(url):
        return url
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)

        # Facebook group date links often look like:
        # /groups/<gid>?multi_permalinks=<postid>&...
        m = re.fullmatch(r"/groups/([^/]+)", path, re.I)
        post_ids = query.get("multi_permalinks") or []
        if m and post_ids:
            post_id = str(post_ids[0]).strip()
            if post_id.isdigit():
                return f"https://www.facebook.com/groups/{m.group(1)}/posts/{post_id}/"

        # Normalize supported mobile subdomains, preserving the actual content path.
        return _to_www(url)
    except Exception:
        return url


def facebook_cli_target(url: str) -> tuple[str, str]:
    """Return facebook-cli command + argument for a canonical Facebook media URL."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)

    m = re.search(r"/(?:reel|reels)/(\d+)$", path, re.I)
    if m:
        return "reel", m.group(1)

    # Direct media URLs use the dedicated media surfaces.
    m = re.search(r"/(?:videos|video)/(\d+)$", path, re.I)
    if m:
        return "video", m.group(1)
    if path.lower() in {"/watch", "/watch/"}:
        v = (query.get("v") or [""])[0]
        if str(v).isdigit():
            return "video", str(v)

    if path.lower() in {"/photo", "/photo.php"}:
        fbid = (query.get("fbid") or [""])[0]
        if str(fbid).isdigit():
            return "photo", str(fbid)

    return "post", url


def facebook_cookie_credentials(cookie: str | None) -> tuple[str | None, str | None]:
    """Extract c_user/xs without ever logging or returning unrelated cookies."""
    if not cookie:
        return None, None
    values: dict[str, str] = {}

    if cookie.lstrip().startswith("# Netscape"):
        for raw in cookie.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            cols = raw.split("\t")
            if len(cols) >= 7 and cols[5] in {"c_user", "xs"}:
                values[cols[5]] = cols[6].strip()
    else:
        header = cookie_header_for_engine(cookie) or cookie
        for piece in header.split(";"):
            key, sep, value = piece.strip().partition("=")
            if sep and key in {"c_user", "xs"}:
                values[key] = value.strip()
    return values.get("c_user") or None, values.get("xs") or None


def _usable_candidate(url: str) -> str | None:
    candidate = clean_url(html.unescape(unquote(url)).replace("\\/", "/"))
    if not candidate or not is_facebook_url(candidate):
        return None
    candidate = normalize_known_facebook_url(candidate)
    path = urlparse(candidate).path.lower()
    if any(x in path for x in ("/login", "/checkpoint", "/recover", "/privacy/", "/help/")):
        return None
    # A share wrapper is not canonical enough for facebook-cli.
    if "/share/" in path:
        return None
    return candidate


def _extract_candidate(body: str) -> str | None:
    for pattern in _META_PATTERNS:
        match = pattern.search(body)
        if match:
            candidate = _usable_candidate(match.group(1))
            if candidate:
                return candidate

    # Facebook frequently stores URLs escaped inside Relay/JSON script blocks.
    decoded = html.unescape(body).replace("\\/", "/").replace("\\u002F", "/").replace("\\u003A", ":")
    for pattern in _URL_PATTERNS:
        for match in pattern.finditer(decoded):
            candidate = _usable_candidate(match.group(0))
            if candidate:
                return candidate
    return None


async def resolve_facebook_url(url: str, cookie_header: str | None = None) -> str:
    """Resolve Facebook-only wrappers. Non-Facebook URLs return immediately untouched."""
    if not is_facebook_url(url):
        return url

    normalized = normalize_known_facebook_url(url)
    parsed = urlparse(normalized)
    if "/share/" not in parsed.path.lower():
        return normalized

    headers_base = {
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if cookie_header:
        headers_base["Cookie"] = cookie_header

    variants = [
        (normalized, "Mozilla/5.0 (Linux; Android 14; SM-S9280) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0 Mobile Safari/537.36"),
        (normalized.replace("www.facebook.com", "m.facebook.com"), "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/143 Mobile Safari/537.36"),
        (normalized.replace("www.facebook.com", "mbasic.facebook.com"), "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/143 Mobile Safari/537.36"),
        (normalized, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0 Safari/537.36"),
    ]

    logger.info("facebook resolver start kind=share cookie_configured=%s", bool(cookie_header))
    for attempt, (candidate_url, ua) in enumerate(variants, 1):
        headers = dict(headers_base)
        headers["User-Agent"] = ua
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20, headers=headers) as client:
                response = await client.get(candidate_url)
            final = normalize_known_facebook_url(str(response.url))
            history = len(response.history)
            logger.info(
                "facebook resolver attempt=%s status=%s redirects=%s final_is_share=%s",
                attempt, response.status_code, history, "/share/" in urlparse(final).path.lower(),
            )
            direct = _usable_candidate(final)
            if direct:
                logger.info("facebook resolver success attempt=%s source=redirect", attempt)
                return direct
            extracted = _extract_candidate(response.text[:3_000_000])
            if extracted:
                logger.info("facebook resolver success attempt=%s source=page", attempt)
                return extracted
        except Exception as exc:
            logger.info("facebook resolver attempt=%s failed=%s", attempt, type(exc).__name__)

    logger.warning("facebook resolver unresolved share_url=true")
    return normalized
