from __future__ import annotations

import json
from typing import Any

from .db import Database

PLATFORMS = (
    "douyin", "kuaishou", "bilibili", "xiaohongshu", "instagram",
    "twitter", "youtube", "facebook", "tiktok",
)

BUILTINS: list[dict[str, Any]] = [
    {"key": "parse_shenzjd", "label": "parse.shenzjd.com（Docker）", "kind": "builtin", "cookie_supported": True, "recommended": {"douyin", "kuaishou", "xiaohongshu", "bilibili", "twitter"}},
    {"key": "short_videos_docker", "label": "short_videos（Docker）", "kind": "builtin", "cookie_supported": True, "recommended": {"kuaishou", "xiaohongshu", "bilibili"}},
    {"key": "douyin_parse", "label": "douyin_parse（需 Cookie）", "kind": "builtin", "cookie_supported": True, "recommended": {"douyin"}},
    {"key": "x-cli", "label": "x-cli", "kind": "builtin", "cookie_supported": True, "recommended": {"twitter"}},
    {"key": "short_videos", "label": "short_videos（本地 PHP）", "kind": "builtin", "cookie_supported": True, "recommended": {"douyin", "kuaishou", "xiaohongshu", "bilibili"}},
    {"key": "gallery-dl", "label": "gallery-dl", "kind": "builtin", "cookie_supported": True, "recommended": {"instagram", "twitter", "facebook", "tiktok", "bilibili"}},
    {"key": "yt-dlp", "label": "yt-dlp", "kind": "builtin", "cookie_supported": True, "recommended": {"douyin", "kuaishou", "tiktok", "twitter", "instagram", "facebook", "youtube", "bilibili", "xiaohongshu"}},
]

DEFAULT_BUILTIN_ORDER = {
    "douyin": ["parse_shenzjd", "short_videos_docker", "douyin_parse", "short_videos", "gallery-dl", "yt-dlp"],
    "kuaishou": ["short_videos_docker", "parse_shenzjd", "short_videos", "gallery-dl", "yt-dlp"],
    "bilibili": ["short_videos_docker", "parse_shenzjd", "short_videos", "gallery-dl", "yt-dlp"],
    "xiaohongshu": ["short_videos_docker", "parse_shenzjd", "short_videos", "gallery-dl", "yt-dlp"],
    "instagram": ["gallery-dl", "yt-dlp"],
    "twitter": ["parse_shenzjd", "x-cli", "gallery-dl", "yt-dlp"],
    "youtube": ["yt-dlp", "gallery-dl"],
    "facebook": ["gallery-dl", "yt-dlp"],
    "tiktok": ["gallery-dl", "yt-dlp"],
}


class ParserRouteStore:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _setting_key(platform: str) -> str:
        return f"parser_route:{platform}"

    def _all_items(self, platform: str) -> list[dict[str, Any]]:
        if platform not in PLATFORMS:
            raise ValueError("unsupported platform")
        builtins = []
        by_key = {x["key"]: x for x in BUILTINS}
        for key in DEFAULT_BUILTIN_ORDER[platform]:
            row = by_key[key]
            builtins.append({
                "key": key,
                "label": row["label"],
                "kind": "builtin",
                "recommended": platform in row["recommended"],
                "api_id": None,
                "api_enabled": True,
                "cookie_supported": bool(row.get("cookie_supported")),
            })

        apis = []
        for api in self.db.parser_apis(enabled_only=False):
            supported = platform in (api.get("platforms") or []) or "*" in (api.get("platforms") or [])
            apis.append({
                "key": f"free-api:{api['id']}",
                "label": api.get("name") or f"免费 API #{api['id']}",
                "kind": "free_api",
                "recommended": supported,
                "api_id": int(api["id"]),
                "api_enabled": bool(api.get("enabled")),
                "api_priority": int(api.get("priority") or 100),
                "cookie_supported": False,
            })
        apis.sort(key=lambda x: (0 if x["recommended"] else 1, x["api_priority"], x["api_id"]))

        # Docker engines are the primary routes for the domestic platforms.
        # Free APIs remain a later fallback. Keep x-cli available as an X fallback.
        if platform == "twitter":
            insert_at = 1
        elif platform == "douyin":
            insert_at = 2
        elif platform in {"kuaishou", "bilibili", "xiaohongshu"}:
            insert_at = 1
        elif platform in {"instagram", "youtube", "facebook", "tiktok"}:
            insert_at = 0
        else:
            insert_at = 0
        return builtins[:insert_at] + apis + builtins[insert_at:]

    def get(self, platform: str) -> dict[str, Any]:
        current = self._all_items(platform)
        by_key = {x["key"]: x for x in current}
        raw = self.db.get_setting(self._setting_key(platform))
        saved: list[dict[str, Any]] = []
        if raw:
            try:
                obj = json.loads(raw)
                if isinstance(obj, list):
                    saved = [x for x in obj if isinstance(x, dict) and isinstance(x.get("key"), str)]
            except Exception:
                saved = []

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in saved:
            key = item["key"]
            base = by_key.get(key)
            if not base or key in seen:
                continue
            enabled = bool(item.get("enabled", base["recommended"]))
            cookie_enabled = bool(item.get("cookie_enabled", False)) and bool(base.get("cookie_supported"))
            if base["kind"] == "free_api" and not base["api_enabled"]:
                enabled = False
            out.append({**base, "enabled": enabled, "cookie_enabled": cookie_enabled})
            seen.add(key)

        for base in current:
            if base["key"] in seen:
                continue
            enabled = bool(base["recommended"])
            if base["kind"] == "free_api" and not base["api_enabled"]:
                enabled = False
            out.append({**base, "enabled": enabled, "cookie_enabled": False})
        return {"platform": platform, "items": out}

    def all(self) -> list[dict[str, Any]]:
        return [self.get(p) for p in PLATFORMS]

    def save(self, platform: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        valid = {x["key"] for x in self._all_items(platform)}
        cleaned: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            key = str(item.get("key") or "")
            if key not in valid or key in seen:
                continue
            cleaned.append({
                "key": key,
                "enabled": bool(item.get("enabled")),
                "cookie_enabled": bool(item.get("cookie_enabled")),
            })
            seen.add(key)
        self.db.put_setting(self._setting_key(platform), json.dumps(cleaned, ensure_ascii=False))
        return self.get(platform)

    def reset(self, platform: str) -> dict[str, Any]:
        self.db.delete_setting(self._setting_key(platform))
        return self.get(platform)

    def enabled_keys(self, platform: str) -> list[str]:
        return [x["key"] for x in self.get(platform)["items"] if x.get("enabled")]

    def parser_options(self, platform: str) -> list[dict[str, Any]]:
        return self.get(platform)["items"]

    def cookie_enabled(self, platform: str, parser_key: str) -> bool:
        return any(
            x["key"] == parser_key and x.get("cookie_supported") and x.get("cookie_enabled")
            for x in self.parser_options(platform)
        )
