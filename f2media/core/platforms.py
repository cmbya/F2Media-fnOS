from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ParsedInput:
    url: str
    platform: str


URL_RE = re.compile(r"https?://[^\\s<>\\"'，。！？、；;）)\\]】》」』]+", re.I)

DOMAIN_PLATFORM = {
    "douyin.com": "douyin",
    "iesdouyin.com": "douyin",
    "tiktok.com": "tiktok",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "fb.watch": "facebook",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "bilibili.com": "bilibili",
    "b23.tv": "bilibili",
    "kuaishou.com": "kuaishou",
    "kuaishou.cn": "kuaishou",
    "xiaohongshu.com": "xiaohongshu",
    "xhslink.com": "xiaohongshu",
    "xhslink.cn": "xiaohongshu",
}


def extract_urls(text: str) -> list[str]:
    urls = []
    for m in URL_RE.finditer(text or ""):
        # 抖音/快手分享文案会在短链后继续附带分享码，只保留真正的 URL。
        if u not in urls:
            urls.append(u)
    return urls


def platform_for_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for domain, platform in DOMAIN_PLATFORM.items():
        if host == domain or host.endswith("." + domain):
            return platform
    return "unknown"


def parse_input(text: str) -> list[ParsedInput]:
    urls = extract_urls(text)
    if not urls:
        raise ValueError("没有从输入内容中找到 http/https 链接")
    return [ParsedInput(url=u, platform=platform_for_url(u)) for u in urls]
