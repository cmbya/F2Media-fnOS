from __future__ import annotations

import os
from typing import Any

import httpx

from ..core.cookie_format import cookie_header_for_engine
from ..core.platforms import ParsedInput
from ..core.redact import redact_text
from .common import normalize_external_result


SHENZJD_BASE = "http://192.168.100.125:18083"
SHORT_VIDEOS_BASE = "http://192.168.100.125:18084"

SHENZJD_PATHS = {
    "douyin": ("douyin",),
    "kuaishou": ("kuaishou",),
    "xiaohongshu": ("xhs", "xiaohongshu"),
    "bilibili": ("bilibili",),
    "twitter": ("twitter", "x"),
}

SHORT_VIDEOS_PATHS = {
    "douyin": "douyin.php",
    "kuaishou": "kuaishou.php",
    "xiaohongshu": "xhsjx.php",
    "bilibili": "bilibili.php",
}


class DockerParserAdapter:
    """Call a parser deployed as an HTTP service on the NAS."""

    def __init__(self, name: str, base_url: str, paths: dict[str, Any], suffix: str = ""):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.paths = paths
        self.suffix = suffix

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/{path}{self.suffix}"

    async def parse(self, item: ParsedInput, cookie: str | None) -> dict[str, Any]:
        paths = self.paths.get(item.platform)
        if not paths:
            raise RuntimeError(f"{self.name} 不支持 {item.platform}")
        if isinstance(paths, str):
            paths = (paths,)
        header = cookie_header_for_engine(cookie)
        headers = {
            "User-Agent": "F2Media/0.5 DockerParser",
            "Accept": "application/json,text/plain,*/*",
        }
        if header:
            headers["Cookie"] = header

        last_error = ""
        async with httpx.AsyncClient(follow_redirects=True, timeout=90, headers=headers) as client:
            for path in paths:
                endpoint = self._url(path)
                try:
                    response = await client.get(endpoint, params={"url": item.url})
                    if response.status_code >= 400:
                        last_error = f"HTTP {response.status_code}"
                        continue
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        last_error = f"返回不是 JSON：{redact_text(response.text[-500:])}"
                        continue
                    if not isinstance(payload, dict):
                        last_error = "返回 JSON 不是对象"
                        continue
                    code = payload.get("code")
                    if code not in (None, 0, 200, "0", "200") and not payload.get("ok"):
                        last_error = str(payload.get("msg") or payload.get("message") or f"接口 code={code}")
                        continue
                    if payload.get("ok") is False:
                        last_error = str(payload.get("error") or payload.get("msg") or "接口返回失败")
                        continue
                    result = normalize_external_result(
                        payload,
                        item.platform,
                        item.url,
                        self.name,
                        download_plan={"strategy": self.name, "source": endpoint},
                    )
                    if result.get("ok"):
                        return result
                    last_error = "接口没有返回可下载媒体"
                except (httpx.HTTPError, ValueError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"

        raise RuntimeError(f"{self.name} 解析失败：{redact_text(last_error or '接口无响应')}")


class ParseShenzjdAdapter(DockerParserAdapter):
    name = "parse_shenzjd"

    def __init__(self):
        super().__init__(
            self.name,
            os.getenv("F2MEDIA_PARSE_SHENZJD_URL", SHENZJD_BASE),
            SHENZJD_PATHS,
        )


class ShortVideosDockerAdapter(DockerParserAdapter):
    name = "short_videos_docker"

    def __init__(self):
        super().__init__(
            self.name,
            os.getenv("F2MEDIA_SHORT_VIDEOS_DOCKER_URL", SHORT_VIDEOS_BASE),
            SHORT_VIDEOS_PATHS,
            suffix="",
        )
