from __future__ import annotations

import os
from pathlib import Path

from .base import Adapter, AdapterContext, AdapterResult
from f2media.core.cookie_format import netscape_for_engine
from f2media.core.runner import run_process
from f2media.core.engine import engine_command


def _message(lines: list[str], rc: int) -> str:
    text = "\n".join(lines[-120:]).lower()
    if "cookies" in text and ("login" in text or "registered users" in text or "fresh cookies" in text):
        return "需要配置有效 Cookie 后重试"
    if "http error 403" in text or "403: forbidden" in text:
        return "远端返回 403；已尝试兼容客户端/重试策略"
    if "unsupported url" in text:
        return "当前 yt-dlp 不支持该链接"
    if "no video could be found" in text:
        return "该内容未检测到视频（图片内容应由图片适配器处理）"
    return f"yt-dlp exit={rc}"


class YtDlpAdapter(Adapter):
    name = "yt-dlp"
    platforms = {"youtube", "bilibili", "facebook", "instagram", "tiktok", "twitter", "kuaishou", "xiaohongshu", "douyin"}

    def available(self) -> tuple[bool, str]:
        cmd = engine_command("yt-dlp")
        return (bool(cmd), " ".join(cmd) if cmd else "yt-dlp sidecar not found")

    async def _run(self, ctx: AdapterContext, extra: list[str], cookie_file: Path | None):
        prefix = engine_command("yt-dlp") or ["yt-dlp"]
        cmd = [
            *prefix,
            "--verbose", "--newline", "--no-color", "--ignore-config", "--no-mtime", "--no-update",
            "--windows-filenames", "--merge-output-format", "mp4",
            "--retries", "3", "--fragment-retries", "3", "--retry-sleep", "http:1:3",
            "-P", str(ctx.output_dir),
            "-o", "%(uploader|unknown)s/%(upload_date|unknown)s_%(id)s_%(title).120B.%(ext)s",
            *extra,
        ]
        ffmpeg_dir = os.getenv("F2MEDIA_FFMPEG_DIR", "").strip()
        if ffmpeg_dir and Path(ffmpeg_dir, "ffmpeg").exists():
            cmd += ["--ffmpeg-location", ffmpeg_dir]
        deno = os.getenv("F2MEDIA_DENO_BIN", "").strip()
        if deno and Path(deno).exists():
            cmd += ["--js-runtimes", f"deno:{deno}"]
        if cookie_file:
            cmd += ["--cookies", str(cookie_file)]
        cmd.append(ctx.url)
        child_env = {
            "HOME": str(ctx.state_dir),
            "XDG_CACHE_HOME": str(ctx.state_dir / "cache"),
            "XDG_CONFIG_HOME": str(ctx.state_dir / "config"),
        }
        for key in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
            Path(child_env[key]).mkdir(parents=True, exist_ok=True)
        return await run_process(cmd, ctx.task_log, cwd=ctx.state_dir, env=child_env, timeout=1800)

    async def download(self, ctx: AdapterContext) -> AdapterResult:
        ok, reason = self.available()
        if not ok:
            return AdapterResult(self.name, False, reason)
        cookie_file = None
        if ctx.cookie:
            try:
                jar = netscape_for_engine(ctx.platform, ctx.cookie)
                cookie_file = ctx.temp_dir / f"{ctx.task_id}-cookies.txt"
                cookie_file.write_text(jar or "", encoding="utf-8")
                cookie_file.chmod(0o600)
            except Exception as exc:
                ctx.task_log.write("WARNING", f"Cookie 转换失败，本次 yt-dlp 不传 Cookie: {type(exc).__name__}: {exc}")

        # YouTube enforcement changes frequently. web_embedded currently avoids GVS PO-token
        # requirements for embeddable videos; if that fails, try the normal extractor and then
        # a conservative single-file fallback. Each attempt creates a fresh signed media URL.
        attempts: list[tuple[str, list[str]]]
        if ctx.platform == "youtube":
            attempts = [
                ("web_embedded 无 PO-Token客户端", ["--extractor-args", "youtube:player_client=web_embedded"]),
                ("默认客户端", []),
                ("兼容单文件格式", ["-f", "18/best[height<=720]/best"]),
            ]
        else:
            attempts = [("默认", [])]

        last = None
        try:
            for idx, (label, extra) in enumerate(attempts, 1):
                if len(attempts) > 1:
                    ctx.task_log.write("INFO", f"yt-dlp 第 {idx}/{len(attempts)} 次尝试: {label}")
                last = await self._run(ctx, extra, cookie_file)
                if last.returncode == 0:
                    return AdapterResult(self.name, True, f"yt-dlp {label} success")
                ctx.task_log.write("WARNING", f"yt-dlp 尝试失败: {label}; {_message(last.lines, last.returncode)}")
        finally:
            if cookie_file:
                cookie_file.unlink(missing_ok=True)
        assert last is not None
        return AdapterResult(self.name, False, _message(last.lines, last.returncode))
