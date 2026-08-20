from __future__ import annotations

import json
from typing import Any

import httpx

from ..core.db import Database
from .common import normalize_external_result

DEFAULT_BUGPK = {
    "name": "BugPK 聚合解析",
    "platforms": ["douyin", "kuaishou", "bilibili", "xiaohongshu", "instagram", "twitter", "youtube", "tiktok"],
    "url": "https://api.bugpk.com/api/short_videos",
    "method": "GET",
    "url_param": "url",
    "headers": {},
    "params": {},
    "mapping": {},
    "timeout": 15,
    "enabled": True,
    "priority": 100,
}


def dot_get(value: Any, path: str | None) -> Any:
    if not path:
        return None
    current = value
    for piece in path.split("."):
        if isinstance(current, dict):
            current = current.get(piece)
        elif isinstance(current, list) and piece.isdigit():
            idx = int(piece)
            current = current[idx] if idx < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def apply_mapping(payload: Any, mapping: dict[str, Any]) -> Any:
    if not mapping:
        return payload
    root = dot_get(payload, mapping.get("root")) if mapping.get("root") else payload
    if root is None:
        root = payload
    data: dict[str, Any] = {}
    for key in ("type", "title", "author", "cover", "url", "images", "videos", "live_photo"):
        path = mapping.get(key)
        if path:
            data[key] = dot_get(root, str(path))
    return {"data": data}


class FreeApiStore:
    def __init__(self, db: Database):
        self.db = db
        self.db.seed_parser_api(DEFAULT_BUGPK)

    def list(self) -> list[dict[str, Any]]:
        return self.db.parser_apis()

    def save(self, config: dict[str, Any], api_id: int | None = None) -> dict[str, Any]:
        return self.db.put_parser_api(config, api_id=api_id)

    def delete(self, api_id: int) -> None:
        self.db.delete_parser_api(api_id)

    async def parse(self, platform: str, source_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
        errors: list[str] = []
        for config in self.db.parser_apis(platform=platform, enabled_only=True):
            try:
                result = await self.call(config, platform, source_url)
                if result.get("ok"):
                    return result, config
                errors.append(f"{config['name']}: 未返回媒体")
            except Exception as exc:
                errors.append(f"{config['name']}: {type(exc).__name__}: {exc}")
        raise RuntimeError("; ".join(errors) if errors else "没有为该平台配置可用的免费解析 API")

    async def call(self, config: dict[str, Any], platform: str, source_url: str) -> dict[str, Any]:
        method = str(config.get("method") or "GET").upper()
        if method not in {"GET", "POST"}:
            raise ValueError("免费 API 只支持 GET/POST")
        params = dict(config.get("params") or {})
        params[str(config.get("url_param") or "url")] = source_url
        headers = {str(k): str(v) for k, v in (config.get("headers") or {}).items()}
        timeout = max(3, min(int(config.get("timeout") or 15), 120))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = await (client.get(config["url"], params=params) if method == "GET" else client.post(config["url"], data=params))
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError("API 返回的不是 JSON") from exc
        mapped = apply_mapping(payload, config.get("mapping") or {})
        result = normalize_external_result(mapped, platform, source_url, f"free-api:{config['name']}")
        if not result["ok"]:
            code = payload.get("code") if isinstance(payload, dict) else None
            msg = payload.get("msg") if isinstance(payload, dict) else None
            raise RuntimeError(f"API 未返回可下载媒体 code={code!r} msg={msg!r}")
        return result
