from __future__ import annotations

from http.cookies import SimpleCookie

PLATFORM_COOKIE_DOMAIN = {
    "douyin": ".douyin.com",
    "tiktok": ".tiktok.com",
    "twitter": ".x.com",
    "instagram": ".instagram.com",
    "facebook": ".facebook.com",
    "youtube": ".youtube.com",
    "bilibili": ".bilibili.com",
    "kuaishou": ".kuaishou.com",
    "xiaohongshu": ".xiaohongshu.com",
}


def is_netscape_cookie(text: str | None) -> bool:
    if not text:
        return False
    head = text.lstrip()[:160].lower()
    return "netscape http cookie file" in head


def netscape_to_header(text: str) -> str:
    pairs: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 7:
            cols = line.split(None, 6)
        if len(cols) >= 7:
            name, value = cols[5].strip(), cols[6].strip()
            if name:
                pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def header_to_netscape(platform: str, text: str) -> str:
    domain = PLATFORM_COOKIE_DOMAIN.get(platform)
    if not domain:
        raise ValueError(f"没有 {platform} 的 Cookie 域名映射")
    jar = SimpleCookie()
    jar.load(text.strip())
    lines = ["# Netscape HTTP Cookie File", "# Generated locally by F2Media from Cookie Header"]
    for name, morsel in jar.items():
        value = morsel.value
        # Session cookies use expiry=0. TRUE makes the cookie available to subdomains.
        lines.append("\t".join([domain, "TRUE", "/", "TRUE", "0", name, value]))
    if len(lines) == 2:
        raise ValueError("无法从 Cookie Header 解析出键值")
    return "\n".join(lines) + "\n"


def cookie_header_for_engine(text: str | None) -> str | None:
    if not text:
        return None
    if is_netscape_cookie(text):
        value = netscape_to_header(text)
        return value or None
    return text.strip()


def netscape_for_engine(platform: str, text: str | None) -> str | None:
    if not text:
        return None
    if is_netscape_cookie(text):
        return text.replace("\r\n", "\n").strip() + "\n"
    return header_to_netscape(platform, text)
