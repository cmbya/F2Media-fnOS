from __future__ import annotations

import json
from typing import Any

from ..core.cookie_format import cookie_header_for_engine
from ..core.engine import engine_command
from ..core.platforms import ParsedInput
from ..core.redact import redact_text
from .common import normalize_external_result

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
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        response = None
        for line in reversed(lines):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                response = candidate
                break
        if response is None:
            detail = redact_text(err.strip()[-1200:] or out.strip()[-1200:])
            if not detail:
                detail = f"short_videos 进程没有输出 JSON（exit={rc}，请检查 PHP 运行时、cURL 扩展和启动器路径）"
            raise RuntimeError(
                f"short_videos 返回无效：{detail}"
            )
        if not response.get("ok"):
            detail = response.get("error") or f"进程失败（exit={rc}）"
            if err.strip() and "未输出 JSON" in str(detail):
                detail = f"{detail}：{redact_text(err.strip()[-1200:])}"
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
