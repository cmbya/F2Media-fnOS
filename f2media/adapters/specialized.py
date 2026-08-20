from __future__ import annotations

from .base import Adapter, AdapterContext, AdapterResult
from f2media.core.cookie_format import cookie_header_for_engine
from f2media.core.engine import engine_command
from f2media.core.runner import run_process


class SpecializedCliAdapter(Adapter):
    """Dedicated GPL sidecars for platforms that yt-dlp does not cover reliably."""

    def __init__(self, platform: str):
        if platform == "kuaishou":
            self.platforms = {"kuaishou"}
            self.name = "ks-downloader"
        elif platform == "xiaohongshu":
            self.platforms = {"xiaohongshu"}
            self.name = "xhs-downloader"
        else:
            raise ValueError(platform)
        self.platform = platform

    def available(self) -> tuple[bool, str]:
        cmd = engine_command(self.name)
        return (bool(cmd), " ".join(cmd) if cmd else f"{self.name} sidecar not found")

    async def download(self, ctx: AdapterContext) -> AdapterResult:
        ok, reason = self.available()
        if not ok:
            return AdapterResult(self.name, False, reason)
        prefix = engine_command(self.name) or [self.name]
        cmd = [*prefix, "--url", ctx.url, "--output", str(ctx.output_dir)]
        child_env = {
            "HOME": str(ctx.state_dir),
            "XDG_CACHE_HOME": str(ctx.state_dir / "cache"),
            "XDG_CONFIG_HOME": str(ctx.state_dir / "config"),
            "F2MEDIA_VENDOR_COOKIE": cookie_header_for_engine(ctx.cookie) or "",
            "F2MEDIA_VENDOR_STATE": str(ctx.state_dir),
        }
        for key in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
            from pathlib import Path
            Path(child_env[key]).mkdir(parents=True, exist_ok=True)
        result = await run_process(cmd, ctx.task_log, cwd=ctx.state_dir, env=child_env, timeout=1800)
        return AdapterResult(self.name, result.returncode == 0, f"{self.name} exit={result.returncode}")
