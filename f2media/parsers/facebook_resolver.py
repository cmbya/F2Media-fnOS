from __future__ import annotations

import html
import logging
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse, urlunparse

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

# Ordered from the most useful permalink shapes to weaker fallbacks.
_ABSOLUTE_URL_PATTERNS = [
    re.compile(r'https?://(?:www\.|m\.|mbasic\.|web\.|touch\.)?facebook\.com/groups/[^/?"<\\s]+/(?:posts|permalink)/\d+[^"<\\s]*', re.I),
    re.compile(r'https?://(?:www\.|m\.|mbasic\.|web\.|touch\.)?facebook\.com/(?:reel|reels)/\d+[^"<\\s]*', re.I),
    re.compile(r'https?://(?:www\.|m\.|mbasic\.|web\.|touch\.)?facebook\.com/[^/?"<\\s]+/posts/(?:pfbid[A-Za-z0-9]+|\d+)[^"<\\s]*', re.I),
    re.compile(r'https?://(?:www\.|m\.|mbasic\.|web\.|touch\.)?facebook\.com/[^/?"<\\s]+/(?:videos|video)/\d+[^"<\\s]*', re.I),
    re.compile(r'https?://(?:www\.|m\.|mbasic\.|web\.|touch\.)?facebook\.com/(?:story|permalink)\.php\?[^"<\\s]+', re.I),
    re.compile(r'https?://(?:www\.|m\.|mbasic\.|web\.|touch\.)?facebook\.com/watch/\?[^"<\\s]*\bv=\d+[^"<\\s]*', re.I),
    re.compile(r'https?://(?:www\.|m\.|mbasic\.|web\.|touch\.)?facebook\.com/photo(?:\.php)?\?[^"<\\s]*\bfbid=\d+[^"<\\s]*', re.I),
]

_RELATIVE_URL_PATTERNS = [
    re.compile(r'/(?:groups/[^/?"<\\s]+/(?:posts|permalink)/\d+)(?:[^"<\\s]*)?', re.I),
    re.compile(r'/(?:reel|reels)/\d+(?:[^"<\\s]*)?', re.I),
    re.compile(r'/[^/?"<\\s]+/posts/(?:pfbid[A-Za-z0-9]+|\d+)(?:[^"<\\s]*)?', re.I),
    re.compile(r'/(?:story|permalink)\.php\?[^"<\\s]+', re.I),
    re.compile(r'/watch/\?[^"<\\s]*\bv=\d+[^"<\\s]*', re.I),
    re.compile(r'/photo(?:\.php)?\?[^"<\\s]*\bfbid=\d+[^"<\\s]*', re.I),
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


def facebook_url_kind(url: str) -> str:
    try:
        path = urlparse(url).path.lower().rstrip("/")
    except Exception:
        return "other"
    if "/share/r/" in path:
        return "share_reel"
    if "/share/p/" in path:
        return "share_post"
    if "/share/" in path:
        return "share"
    if re.search(r"/(?:reel|reels)/\d+$", path):
        return "reel"
    if "/groups/" in path and ("/posts/" in path or "/permalink/" in path):
        return "group_post"
    return "direct"


def normalize_known_facebook_url(url: str) -> str:
    """Normalize Facebook URL shapes that already contain enough information."""
    if not is_facebook_url(url):
        return url
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)

        # Date links from a Facebook group page.
        m = re.fullmatch(r"/groups/([^/]+)", path, re.I)
        post_ids = query.get("multi_permalinks") or []
        if m and post_ids:
            post_id = str(post_ids[0]).strip()
            if post_id.isdigit():
                return f"https://www.facebook.com/groups/{m.group(1)}/posts/{post_id}/"

        # gallery-dl is happier with /posts/ than /permalink/ for group posts.
        m = re.fullmatch(r"/groups/([^/]+)/permalink/(\d+)", path, re.I)
        if m:
            return f"https://www.facebook.com/groups/{m.group(1)}/posts/{m.group(2)}/"

        # Canonicalize /reels/<id> to the singular URL accepted by facebook-cli.
        m = re.fullmatch(r"/reels/(\d+)", path, re.I)
        if m:
            return f"https://www.facebook.com/reel/{m.group(1)}"

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
    """Extract c_user/xs without logging or returning unrelated cookies."""
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


def _decode_blob(body: str) -> str:
    decoded = body or ""
    for _ in range(3):
        newer = (
            html.unescape(decoded)
            .replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\u003A", ":")
            .replace("\\u003a", ":")
            .replace("\\u0026", "&")
        )
        try:
            newer = unquote(newer)
        except Exception:
            pass
        if newer == decoded:
            break
        decoded = newer
    return decoded


def _usable_candidate(url: str) -> str | None:
    candidate = clean_url(html.unescape(unquote(url)).replace("\\/", "/"))
    if not candidate:
        return None
    if candidate.startswith("/"):
        candidate = urljoin("https://www.facebook.com", candidate)
    if not is_facebook_url(candidate):
        return None
    candidate = normalize_known_facebook_url(candidate)
    parsed = urlparse(candidate)
    path = parsed.path.lower()
    if any(x in path for x in ("/login", "/checkpoint", "/recover", "/privacy/", "/help/")):
        return None
    if "/share/" in path:
        return None
    # Reject home/profile-only URLs. The resolver must return an actual content permalink.
    if path in {"", "/"}:
        return None
    if not (
        "/groups/" in path and ("/posts/" in path or "/permalink/" in path)
        or "/posts/" in path
        or "/reel/" in path
        or "/reels/" in path
        or "/videos/" in path
        or "/video/" in path
        or path.endswith("/story.php")
        or path.endswith("/permalink.php")
        or path.endswith("/photo.php")
        or path == "/watch/"
        or path == "/watch"
    ):
        return None
    return candidate


def _candidate_rank(url: str) -> int:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if "/groups/" in path and "/posts/" in path:
        return 100
    if "/reel/" in path:
        return 95
    if "/posts/" in path:
        return 92
    if path.endswith("/permalink.php") or path.endswith("/story.php"):
        return 90
    if "/videos/" in path or path in {"/watch", "/watch/"}:
        return 88
    if path.endswith("/photo.php"):
        return 85
    return 1


def _story_permalink_from_blob(decoded: str) -> str | None:
    post_patterns = [
        re.compile(r'"top_level_post_id"\s*:\s*"?(\d{8,})"?', re.I),
        re.compile(r'"story_fbid"\s*:\s*"?(\d{8,})"?', re.I),
        re.compile(r'"post_id"\s*:\s*"?(\d{8,})"?', re.I),
    ]
    owner_pattern = re.compile(
        r'"(?:owning_profile_id|owner_id|actor_id|profile_id)"\s*:\s*"?(\d{5,})"?', re.I
    )
    for pattern in post_patterns:
        for match in pattern.finditer(decoded):
            lo = max(0, match.start() - 5000)
            hi = min(len(decoded), match.end() + 5000)
            owner = owner_pattern.search(decoded[lo:hi])
            if owner:
                return (
                    "https://www.facebook.com/permalink.php?"
                    f"story_fbid={match.group(1)}&id={owner.group(1)}"
                )
    return None


def _reel_from_blob(decoded: str) -> str | None:
    for pattern in (
        re.compile(r'"video_id"\s*:\s*"?(\d{8,})"?', re.I),
        re.compile(r'"videoID"\s*:\s*"?(\d{8,})"?', re.I),
        re.compile(r'"videoId"\s*:\s*"?(\d{8,})"?', re.I),
    ):
        match = pattern.search(decoded)
        if match:
            return f"https://www.facebook.com/reel/{match.group(1)}"
    return None


def _extract_candidate(body: str, *, source_kind: str = "share") -> tuple[str | None, str | None]:
    candidates: list[tuple[int, str, str]] = []

    for pattern in _META_PATTERNS:
        match = pattern.search(body)
        if match:
            candidate = _usable_candidate(match.group(1))
            if candidate:
                candidates.append((_candidate_rank(candidate), candidate, "meta"))

    decoded = _decode_blob(body)

    # JSON/Relay keys commonly carry an already-canonical permalink.
    for key in ("permalink_url", "canonical_url", "shareable_url"):
        pattern = re.compile(rf'"{key}"\s*:\s*"([^"<>]+)"', re.I)
        for match in pattern.finditer(decoded):
            candidate = _usable_candidate(match.group(1))
            if candidate:
                candidates.append((_candidate_rank(candidate) + 3, candidate, key))

    for pattern in _ABSOLUTE_URL_PATTERNS:
        for match in pattern.finditer(decoded):
            candidate = _usable_candidate(match.group(0))
            if candidate:
                candidates.append((_candidate_rank(candidate), candidate, "absolute"))

    # m/mbasic pages often expose the permalink as a relative href.
    for pattern in _RELATIVE_URL_PATTERNS:
        for match in pattern.finditer(decoded):
            candidate = _usable_candidate(match.group(0))
            if candidate:
                candidates.append((_candidate_rank(candidate) - 1, candidate, "relative"))

    synthetic = _story_permalink_from_blob(decoded)
    if synthetic:
        candidates.append((_candidate_rank(synthetic) - 2, synthetic, "story_ids"))

    if source_kind == "share_reel":
        reel = _reel_from_blob(decoded)
        if reel:
            candidates.append((_candidate_rank(reel) - 2, reel, "video_id"))

    if not candidates:
        return None, None

    candidates.sort(key=lambda x: x[0], reverse=True)
    _, url, source = candidates[0]
    return url, source


async def resolve_facebook_url(url: str, cookie_header: str | None = None) -> str:
    """Always-on Facebook-only URL preprocessor.

    It converts deterministic Facebook URL shapes and resolves /share/* wrappers.
    It never runs for other platforms and never downloads media itself.
    """
    if not is_facebook_url(url):
        return url

    normalized = normalize_known_facebook_url(url)
    kind = facebook_url_kind(normalized)

    # Direct posts/reels are already valid content URLs. The resolver stays visible
    # in logs but does not rewrite them just for the sake of rewriting.
    if not kind.startswith("share"):
        logger.info("facebook resolver kind=%s action=passthrough", kind)
        return normalized

    headers_base = {
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if cookie_header:
        headers_base["Cookie"] = cookie_header

    variants = [
        (normalized, "desktop"),
        (normalized.replace("www.facebook.com", "m.facebook.com"), "mobile"),
        (normalized.replace("www.facebook.com", "mbasic.facebook.com"), "mbasic"),
    ]
    user_agents = {
        "desktop": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0 Safari/537.36",
        "mobile": "Mozilla/5.0 (Linux; Android 14; SM-S9280) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0 Mobile Safari/537.36",
        "mbasic": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/143 Mobile Safari/537.36",
    }

    logger.info(
        "facebook resolver start kind=%s cookie_configured=%s variants=%s",
        kind, bool(cookie_header), len(variants),
    )
    for attempt, (candidate_url, variant) in enumerate(variants, 1):
        headers = dict(headers_base)
        headers["User-Agent"] = user_agents[variant]
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20, headers=headers) as client:
                response = await client.get(candidate_url)
            final = normalize_known_facebook_url(str(response.url))
            direct = _usable_candidate(final)
            logger.info(
                "facebook resolver attempt=%s variant=%s status=%s redirects=%s final_kind=%s",
                attempt, variant, response.status_code, len(response.history), facebook_url_kind(final),
            )
            if direct:
                logger.info("facebook resolver success source=redirect kind=%s", facebook_url_kind(direct))
                return direct

            extracted, source = _extract_candidate(response.text[:6_000_000], source_kind=kind)
            if extracted:
                logger.info(
                    "facebook resolver success source=%s kind=%s",
                    source or "page", facebook_url_kind(extracted),
                )
                return extracted
            logger.info("facebook resolver attempt=%s candidate_found=false", attempt)
        except Exception as exc:
            logger.info(
                "facebook resolver attempt=%s variant=%s failed=%s",
                attempt, variant, type(exc).__name__,
            )

    logger.warning("facebook resolver unresolved kind=%s; keeping original wrapper", kind)
    return normalized
