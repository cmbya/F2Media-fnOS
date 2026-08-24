from __future__ import annotations

import json
from typing import Any

from ..core.cookie_format import cookie_header_for_engine
from ..core.engine import engine_command
from ..core.platforms import ParsedInput
from ..core.redact import redact_text
from .common import clean_url, normalize_external_result

SUPPORTED_PLATFORMS = {"douyin", "kuaishou", "xiaohongshu", "bilibili"}


class ShortVideosAdapter:
    """Run the bundled short_videos PHP classes through their local adapter."""

    name = "short_videos"

    async def parse(self, item: ParsedInput, cookie: str | None, capture) -> dict[str, Any]:
        if item.platform not in SUPPORTED_PLATFORMS:
            raise RuntimeError(f"short_videos 不支持 {item.platform}")
        prefix = engine_command(self.name)
        if not prefix:
            raise RuntimeError("short_videos 引擎不可用：PHP 运行时或启动器未打包")

        payload = json.dumps(
            {
                "platform": item.platform,
                "url": item.url,
                # Cookie has already passed F2Media's route switch and platform
                # allow-list before it reaches this adapter.
                "cookie": cookie_header_for_engine(cookie) or "",
            },
            ensure_ascii=False,
        )
        state = capture.settings.data_dir / "engine-state" / item.platform / "short_videos"
        rc, out, err = await capture._capture(
            [*prefix], state_dir=state, timeout=90, input_text=payload
        )
        try:
            response = json.loads(out.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as exc:
            raise RuntimeError(
                redact_text(err.strip()[-1200:] or out.strip()[-1200:] or "short_videos 没有返回 JSON")
            ) from exc
        if not isinstance(response, dict) or not response.get("ok"):
            detail = response.get("error") if isinstance(response, dict) else "无效响应"
            raise RuntimeError(redact_text(str(detail)))

        raw = response.get("data")
        result = normalize_external_result(
            {"data": raw}, item.platform, item.url, self.name,
            download_plan={"strategy": self.name, "source": "jiuhunwl/short_videos"},
        )
        if not result.get("ok"):
            raise RuntimeError("short_videos 没有返回可下载媒体")
        return result


def available() -> tuple[bool, str]:
    prefix = engine_command("short_videos")
    return (bool(prefix), " ".join(prefix or []) or "short_videos 未打包")
