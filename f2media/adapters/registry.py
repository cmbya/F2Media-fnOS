from __future__ import annotations

from .base import Adapter
from .f2_cli import F2CliAdapter
from .gallerydl import GalleryDlAdapter
from .specialized import SpecializedCliAdapter
from .ytdlp import YtDlpAdapter


class AdapterRegistry:
    def __init__(self, vendor_root=None):
        f2 = F2CliAdapter()
        ytdlp = YtDlpAdapter()
        gdl = GalleryDlAdapter()
        self._map: dict[str, list[Adapter]] = {
            "douyin": [f2, ytdlp],
            "tiktok": [f2, ytdlp, gdl],
            "twitter": [gdl, f2, ytdlp],
            "instagram": [gdl, ytdlp],
            "facebook": [gdl, ytdlp],
            "youtube": [ytdlp],
            "bilibili": [ytdlp],
            "kuaishou": [SpecializedCliAdapter("kuaishou"), ytdlp],
            "xiaohongshu": [SpecializedCliAdapter("xiaohongshu"), ytdlp],
        }

    def for_platform(self, platform: str) -> list[Adapter]:
        return self._map.get(platform, [])

    def doctor(self) -> list[dict]:
        seen = set()
        rows = []
        for adapters in self._map.values():
            for a in adapters:
                key = (a.name, getattr(a, "platform", None))
                if key in seen:
                    continue
                seen.add(key)
                ok, detail = a.available()
                rows.append({"adapter": a.name, "ok": ok, "detail": detail})
        return rows
