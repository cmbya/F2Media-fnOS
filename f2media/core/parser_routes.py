from __future__ import annotations

import json
from typing import Any

from .db import Database

PLATFORMS = (
    "douyin", "kuaishou", "bilibili", "xiaohongshu", "instagram",
    "twitter", "youtube", "facebook", "tiktok",
)

BUILTINS: list[dict[str, Any]] = [
    {"key": "douyin_parse", "label": "douyin_parse", "kind": "builtin", "recommended": {"douyin"}},
    {"key": "short_videos-local", "label": "short_videos 本地逻辑", "kind": "builtin", "recommended": {"douyin", "kuaishou", "bilibili", "xiaohongshu"}},
    {"key": "x-cli", "label": "x-cli", "kind": "builtin", "recommended": {"twitter"}},
    {"key": "facebook-extractor", "label": "Facebook 专用解析器", "kind": "builtin", "recommended": {"facebook"}},
    {"key": "facebook-cli", "label": "facebook-cli", "kind": "builtin", "recommended": {"facebook"}},
    {"key": "gallery-dl", "label": "gallery-dl", "kind": "builtin", "recommended": {"instagram", "twitter", "facebook", "tiktok", "bilibili"}},
    {"key": "yt-dlp", "label": "yt-dlp", "kind": "builtin", "recommended": {"douyin", "tiktok", "twitter", "instagram", "facebook", "youtube", "bilibili", "xiaohongshu"}},
    {"key": "vidbee", "label": "VidBee Engine", "kind": "builtin", "recommended": {"twitter", "instagram", "facebook", "youtube", "tiktok", "bilibili"}},
    {"key": "iiilab", "label": "iiilab Engine", "kind": "builtin", "recommended": {"twitter", "instagram", "facebook", "youtube"}},
]

# Keeps the existing architecture as the default while still showing every parser.
DEFAULT_BUILTIN_ORDER = {
    "douyin": ["douyin_parse", "short_videos-local", "gallery-dl", "yt-dlp", "x-cli", "facebook-cli"],
    "kuaishou": ["short_videos-local", "gallery-dl", "yt-dlp", "douyin_parse", "x-cli", "facebook-cli"],
    "bilibili": ["short_videos-local", "gallery-dl", "yt-dlp", "douyin_parse", "x-cli", "facebook-cli"],
    "xiaohongshu": ["short_videos-local", "gallery-dl", "yt-dlp", "douyin_parse", "x-cli", "facebook-cli"],
    "instagram": ["gallery-dl", "vidbee", "iiilab", "yt-dlp", "short_videos-local", "douyin_parse", "x-cli", "facebook-cli"],
    "twitter": ["x-cli", "gallery-dl", "yt-dlp", "short_videos-local", "douyin_parse", "facebook-cli"],
    "youtube": ["yt-dlp", "vidbee", "iiilab", "gallery-dl", "short_videos-local", "douyin_parse", "x-cli", "facebook-cli"],
    "facebook": ["vidbee", "facebook-extractor", "iiilab", "gallery-dl", "yt-dlp", "facebook-cli", "short_videos-local", "douyin_parse", "x-cli"],
    "tiktok": ["gallery-dl", "yt-dlp", "short_videos-local", "douyin_parse", "x-cli", "facebook-cli"],
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
            })

        # Free APIs are real route entries, not one aggregate pseudo parser.
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
            })
        apis.sort(key=lambda x: (0 if x["recommended"] else 1, x["api_priority"], x["api_id"]))

        # Preserve the desired stage: supported free APIs sit before generic engines.
        insert_at = 0
        if platform == "douyin":
            insert_at = 2
        elif platform in {"kuaishou", "bilibili", "xiaohongshu"}:
            insert_at = 1
        elif platform in {"instagram", "twitter", "youtube", "facebook", "tiktok"}:
            insert_at = 1 if platform in {"twitter", "facebook"} else 0
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
            if base["kind"] == "free_api" and not base["api_enabled"]:
                enabled = False
            out.append({**base, "enabled": enabled})
            seen.add(key)

        for base in current:
            if base["key"] in seen:
                continue
            enabled = bool(base["recommended"])
            if base["kind"] == "free_api" and not base["api_enabled"]:
                enabled = False
            out.append({**base, "enabled": enabled})
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
            cleaned.append({"key": key, "enabled": bool(item.get("enabled"))})
            seen.add(key)
        # Missing entries are appended automatically on read, so the UI cannot orphan a parser.
        self.db.put_setting(self._setting_key(platform), json.dumps(cleaned, ensure_ascii=False))
        return self.get(platform)

    def reset(self, platform: str) -> dict[str, Any]:
        self.db.delete_setting(self._setting_key(platform))
        return self.get(platform)

    def enabled_keys(self, platform: str) -> list[str]:
        return [x["key"] for x in self.get(platform)["items"] if x.get("enabled")]

    def parser_options(self, platform: str) -> list[dict[str, Any]]:
        return self.get(platform)["items"]
