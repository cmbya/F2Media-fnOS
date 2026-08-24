from __future__ import annotations

import json
import time
from typing import Any

import httpx

from ..core.db import Database
from .common import normalize_external_result

# Built-in public endpoints supplied by the user / BugPK docs.  They are seeded
# once into the database and remain fully editable/deletable from WebUI.
DEFAULT_BUGPK_DOUYIN = {
    "name": "BugPK 抖音原画/实况",
    "platforms": ["douyin"],
    "url": "https://api.bugpk.com/api/douyin",
    "method": "GET",
    "url_param": "url",
    "headers": {},
    "params": {},
    "mapping": {},
    "timeout": 15,
    "enabled": True,
    "priority": 10,
}

DEFAULT_BUGPK_KSJX = {
    "name": "BugPK 快手全类型/动图",
    "platforms": ["kuaishou"],
    "url": "https://api.bugpk.com/api/ksjx",
    "method": "GET",
    "url_param": "url",
    "headers": {},
    "params": {},
    "mapping": {},
    "timeout": 15,
    "enabled": True,
    "priority": 10,
}

DEFAULT_BUGPK_SVPARSE = {
    "name": "BugPK 电脑端聚合解析",
    "platforms": ["douyin", "kuaishou", "bilibili", "xiaohongshu", "tiktok"],
    "url": "https://api.bugpk.com/api/svparse",
    "method": "GET",
    "url_param": "url",
    "headers": {},
    "params": {},
    "mapping": {},
    "timeout": 15,
    "enabled": True,
    "priority": 20,
}

DEFAULT_IFPHP_SVPARSE = {
    "name": "IFPHP 聚合解析（需 API Key）",
    "platforms": ["douyin", "kuaishou", "bilibili", "xiaohongshu", "instagram", "twitter", "youtube", "facebook", "tiktok"],
    "url": "https://api-new.ifphp.com/api/svparse",
    "method": "GET",
    "url_param": "url",
    "headers": {"X-API-Key": ""},
    "params": {},
    "mapping": {},
    "timeout": 30,
    "enabled": False,
    "priority": 5,
}

DEFAULT_BUGPK_DYZY = {
    "name": "BugPK 抖音主页解析",
    "platforms": ["douyin"],
    "url": "https://api.bugpk.com/api/dyzy",
    "method": "GET",
    "url_param": "url",
    "headers": {},
    "params": {},
    "mapping": {},
    "timeout": 15,
    "enabled": True,
    "priority": 30,
}

# Keep the aggregate parser last inside the free-API stage.  The current
# BugPK documentation says it covers 20+ platforms, including these F2Media
# targets. Facebook is intentionally omitted because it is not documented.
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

BUILTIN_APIS = [
    DEFAULT_BUGPK_DOUYIN,
    DEFAULT_BUGPK_KSJX,
    DEFAULT_IFPHP_SVPARSE,
    DEFAULT_BUGPK_SVPARSE,
    DEFAULT_BUGPK_DYZY,
    DEFAULT_BUGPK,
]
BUILTIN_DEFAULTS_VERSION = "3"


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


def _expand_placeholders(value: Any, platform: str, source_url: str) -> Any:
    """Allow simple WebUI configs without requiring JSON-aware templates."""
    if isinstance(value, str):
        return value.replace("{platform}", platform).replace("{url}", source_url)
    if isinstance(value, dict):
        return {str(k): _expand_placeholders(v, platform, source_url) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_placeholders(v, platform, source_url) for v in value]
    return value


class FreeApiStore:
    def __init__(self, db: Database):
        self.db = db
        self._cooldown_until: dict[int, float] = {}
        self._seed_defaults_once()

    def _seed_defaults_once(self) -> None:
        if self.db.get_setting("parser_api_defaults_version") == BUILTIN_DEFAULTS_VERSION:
            return
        for config in BUILTIN_APIS:
            self.db.seed_parser_api(config)
        self.db.put_setting("parser_api_defaults_version", BUILTIN_DEFAULTS_VERSION)

    def list(self) -> list[dict[str, Any]]:
        return self.db.parser_apis()

    def save(self, config: dict[str, Any], api_id: int | None = None) -> dict[str, Any]:
        return self.db.put_parser_api(config, api_id=api_id)

    def delete(self, api_id: int) -> None:
        self.db.delete_parser_api(api_id)
        self._cooldown_until.pop(api_id, None)

    def get(self, api_id: int) -> dict[str, Any] | None:
        return next((x for x in self.db.parser_apis(enabled_only=False) if int(x.get("id") or 0) == int(api_id)), None)

    async def call_by_id(self, api_id: int, platform: str, source_url: str) -> dict[str, Any]:
        config = self.get(api_id)
        if not config:
            raise RuntimeError("免费 API 配置不存在")
        if not config.get("enabled"):
            raise RuntimeError(f"免费 API 已停用: {config.get('name')}")
        if self._cooling_down(config):
            raise RuntimeError(f"{config.get('name')}: 429 冷却中")
        try:
            return await self.call(config, platform, source_url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                self._start_cooldown(config)
            raise

    @staticmethod
    def _source_matches(config: dict[str, Any], source_url: str) -> bool:
        # dyzy is a homepage endpoint. Do not waste a request on normal works or a
        # /user/... URL that only exists because Douyin opened a modal_id work.
        if str(config.get("url") or "").rstrip("/").endswith("/dyzy"):
            return "/user/" in source_url and "modal_id=" not in source_url
        return True

    def _cooling_down(self, config: dict[str, Any]) -> bool:
        api_id = int(config.get("id") or 0)
        return bool(api_id and self._cooldown_until.get(api_id, 0) > time.monotonic())

    def _start_cooldown(self, config: dict[str, Any], seconds: int = 45) -> None:
        api_id = int(config.get("id") or 0)
        if api_id:
            self._cooldown_until[api_id] = time.monotonic() + seconds

    async def parse(self, platform: str, source_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
        errors: list[str] = []
        for config in self.db.parser_apis(platform=platform, enabled_only=True):
            if not self._source_matches(config, source_url):
                continue
            if self._cooling_down(config):
                errors.append(f"{config['name']}: 429 冷却中")
                continue
            try:
                result = await self.call(config, platform, source_url)
                if result.get("ok"):
                    return result, config
                errors.append(f"{config['name']}: 未返回媒体")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    self._start_cooldown(config)
                errors.append(f"{config['name']}: {type(exc).__name__}: {exc}")
            except Exception as exc:
                errors.append(f"{config['name']}: {type(exc).__name__}: {exc}")
        raise RuntimeError("; ".join(errors) if errors else "没有为该平台配置可用的免费解析 API")

    async def _request(
        self,
        config: dict[str, Any],
        platform: str,
        source_url: str,
        *,
        add_platform_hint: bool = False,
    ) -> Any:
        method = str(config.get("method") or "GET").upper()
        if method not in {"GET", "POST"}:
            raise ValueError("免费 API 只支持 GET/POST")
        params = _expand_placeholders(dict(config.get("params") or {}), platform, source_url)
        params[str(config.get("url_param") or "url")] = source_url
        if add_platform_hint and "platform" not in params:
            params["platform"] = platform
        headers = {
            str(k): str(v)
            for k, v in _expand_placeholders(dict(config.get("headers") or {}), platform, source_url).items()
        }
        timeout = max(3, min(int(config.get("timeout") or 15), 120))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = await (
                client.get(config["url"], params=params)
                if method == "GET"
                else client.post(config["url"], data=params)
            )
            response.raise_for_status()
            try:
                return response.json()
            except ValueError as exc:
                raise RuntimeError("API 返回的不是 JSON") from exc

    async def call(self, config: dict[str, Any], platform: str, source_url: str) -> dict[str, Any]:
        payload = await self._request(config, platform, source_url)
        mapped = apply_mapping(payload, config.get("mapping") or {})
        result = normalize_external_result(mapped, platform, source_url, f"free-api:{config['name']}")
        if result["ok"]:
            return result

        code = payload.get("code") if isinstance(payload, dict) else None
        msg = str(payload.get("msg") or "") if isinstance(payload, dict) else ""
        # BugPK's aggregate endpoint may explicitly request a platform hint for
        # ambiguous x.com-style URLs. Retry once only when the server asks for it.
        if "platform" in msg.lower() or "platform 参数" in msg:
            payload = await self._request(config, platform, source_url, add_platform_hint=True)
            mapped = apply_mapping(payload, config.get("mapping") or {})
            result = normalize_external_result(mapped, platform, source_url, f"free-api:{config['name']}")
            if result["ok"]:
                return result
            code = payload.get("code") if isinstance(payload, dict) else code
            msg = str(payload.get("msg") or "") if isinstance(payload, dict) else msg

        raise RuntimeError(f"API 未返回可下载媒体 code={code!r} msg={msg!r}")
