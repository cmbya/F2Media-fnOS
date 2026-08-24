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

# parse.shenzjd.com 同时提供平台专用路由和统一 /api/parse 入口。
# 专用路由优先，统一入口作为服务版本差异或单个平台路由异常时的兜底。
SHENZJD_PATHS = {
    "douyin": ("douyin", "parse"),
    "kuaishou": ("kuaishou", "parse"),
    "xiaohongshu": ("xhs", "parse"),
    "bilibili": ("bilibili", "parse"),
    "twitter": ("twitter", "parse"),
}

# short_videos 的 PHP 文件位于各平台子目录中，而不是 api 根目录。
SHORT_VIDEOS_PATHS = {
    "douyin": "douyin/douyin.php",
    "kuaishou": "kuaishou/ksjx.php",
    "xiaohongshu": "xiaohongshu/xhsjx.php",
    "bilibili": "bilibili/bilibili.php",
}

# 不同 Docker 部署可能把仓库根目录或 api 目录作为 Apache 文档根。
# 两种前缀都尝试，兼容这两种部署方式。
SHORT_VIDEOS_PREFIXES = ("/api", "")

_URL_KEYS = {
    "url",
    "src",
    "image",
    "image_url",
    "imageUrl",
    "video",
    "video_url",
    "videoUrl",
    "cover",
    "cover_url",
    "coverUrl",
    "images",
    "videos",
    "masterUrl",
    "backupUrls",
    "audioUrl",
}


class DockerParserAdapter:
    """Call a parser deployed as an HTTP service on the NAS."""

    def __init__(
        self,
        name: str,
        base_url: str,
        paths: dict[str, Any],
        suffix: str = "",
        path_prefixes: tuple[str, ...] = ("/api",),
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.paths = paths
        self.suffix = suffix
        self.path_prefixes = path_prefixes

    def _urls(self, path: str) -> list[str]:
        return [
            f"{self.base_url}{prefix}/{path}{self.suffix}"
            for prefix in self.path_prefixes
        ]

    def _absolutize_relative_urls(self, value: Any, force_url: bool = False) -> Any:
        """把 Docker 服务返回的相对代理地址补成可访问的绝对地址。"""
        if isinstance(value, str):
            if force_url and value.startswith("/"):
                return f"{self.base_url}{value}"
            return value
        if isinstance(value, list):
            return [
                self._absolutize_relative_urls(item, force_url)
                for item in value
            ]
        if isinstance(value, dict):
            return {
                key: self._absolutize_relative_urls(
                    item, force_url or key in _URL_KEYS
                )
                for key, item in value.items()
            }
        return value

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
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=90,
            headers=headers,
        ) as client:
            for path in paths:
                for endpoint in self._urls(path):
                    try:
                        response = await client.get(
                            endpoint,
                            params={"url": item.url},
                        )
                        if response.status_code >= 400:
                            last_error = f"HTTP {response.status_code} ({endpoint})"
                            continue
                        try:
                            payload = response.json()
                        except ValueError:
                            last_error = (
                                f"返回不是 JSON："
                                f"{redact_text(response.text[-500:])}"
                            )
                            continue
                        if not isinstance(payload, dict):
                            last_error = "返回 JSON 不是对象"
                            continue

                        payload = self._absolutize_relative_urls(payload)
                        code = payload.get("code")
                        if (
                            code not in (None, 0, 200, "0", "200")
                            and not payload.get("ok")
                        ):
                            last_error = str(
                                payload.get("msg")
                                or payload.get("message")
                                or f"接口 code={code}"
                            )
                            continue
                        if payload.get("ok") is False:
                            last_error = str(
                                payload.get("error")
                                or payload.get("msg")
                                or "接口返回失败"
                            )
                            continue

                        result = normalize_external_result(
                            payload,
                            item.platform,
                            item.url,
                            self.name,
                            download_plan={
                                "strategy": self.name,
                                "source": endpoint,
                            },
                        )
                        if result.get("ok"):
                            return result
                        last_error = "接口没有返回可下载媒体"
                    except (httpx.HTTPError, ValueError) as exc:
                        last_error = f"{type(exc).__name__}: {exc}"

        raise RuntimeError(
            f"{self.name} 解析失败："
            f"{redact_text(last_error or '接口无响应')}"
        )


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
            path_prefixes=SHORT_VIDEOS_PREFIXES,
        )
