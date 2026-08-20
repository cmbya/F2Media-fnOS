from __future__ import annotations

import json
import os
import shutil

from .base import Adapter, AdapterContext, AdapterResult
from f2media.core.cookie_format import cookie_header_for_engine
from f2media.core.runner import run_process
from f2media.core.engine import engine_command


class F2CliAdapter(Adapter):
    name = "f2"
    platforms = {"douyin", "tiktok", "twitter"}
    alias = {"douyin": "dy", "tiktok": "tk", "twitter": "x"}

    def available(self) -> tuple[bool, str]:
        cmd = engine_command("f2")
        return (bool(cmd), " ".join(cmd) if cmd else "F2 sidecar not found")

    async def download(self, ctx: AdapterContext) -> AdapterResult:
        ok, reason = self.available()
        if not ok:
            return AdapterResult(self.name, False, reason)

        cookie = cookie_header_for_engine(ctx.cookie) or ""
        if not cookie:
            ctx.task_log.write("WARNING", f"F2 {ctx.platform} 未配置 Cookie；公开内容也可能因风控失败")
            if ctx.platform == "tiktok":
                # F2 0.0.1.7 currently tries to generate msToken while importing the TikTok app.
                # Anonymous server/NAS traffic frequently fails before a URL is parsed. Avoid a
                # noisy traceback and let Cookie-aware fallbacks run instead.
                return AdapterResult(self.name, False, "F2 TikTok 建议先配置 Cookie；未配置时跳过 msToken 自生成")
        if ctx.platform == "twitter" and not (ctx.extra_secret or "").strip():
            return AdapterResult(self.name, False, "F2 X/Twitter 需要同时配置 X-Csrf-Token")

        cfg = {
            ctx.platform: {
                "cookie": cookie,
                "path": str(ctx.output_dir),
                "folderize": True,
                "mode": "one" if ctx.platform != "twitter" else "post",
                "max_retries": 5,
                "timeout": 20,
                "max_connections": 5,
                "max_tasks": 5,
                "max_counts": 0,
                "page_counts": 20 if ctx.platform == "douyin" else 5,
                "naming": "{create}_{desc}" if ctx.platform != "twitter" else "{create}_{tweet_id}_{desc}",
            }
        }
        # JSON is accepted by the YAML loader and avoids adding YAML as a main-runtime dependency.
        cfg_path = ctx.temp_dir / f"{ctx.task_id}-f2.yaml"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(cfg_path, 0o600)
        except OSError:
            pass

        prefix = engine_command("f2") or ["f2"]
        cmd = [
            *prefix, "-d", "DEBUG", self.alias[ctx.platform],
            "-c", str(cfg_path), "-M", cfg[ctx.platform]["mode"], "-u", ctx.url,
            "-p", str(ctx.output_dir),
        ]
        child_env: dict[str, str] = {}
        if ctx.platform == "twitter" and ctx.extra_secret:
            # The bundled F2 sidecar wrapper injects this into ClientConfManager at runtime.
            child_env["F2MEDIA_X_CSRF_TOKEN"] = ctx.extra_secret.strip()

        work_dir = ctx.temp_dir / f"{ctx.task_id}-f2-work"
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(work_dir, 0o700)
        except OSError:
            pass
        try:
            # F2 can create its own debug logs. Keep them in an ephemeral task directory so
            # raw upstream logs (which may contain cookies) are never persisted. Our captured
            # stdout/stderr is redacted before it reaches the task log.
            result = await run_process(cmd, ctx.task_log, cwd=work_dir, env=child_env, timeout=900)
        finally:
            cfg_path.unlink(missing_ok=True)
            shutil.rmtree(work_dir, ignore_errors=True)
        if result.returncode == 0:
            return AdapterResult(self.name, True, "F2 success")
        text = "\n".join(result.lines[-100:]).lower()
        if "qrcode" in text and "modulenotfounderror" in text:
            message = "F2 sidecar 缺少 qrcode（构建自检本应阻止发布）"
        elif "mstoken" in text:
            message = "F2 TikTok msToken 生成失败；建议配置有效 Cookie"
        elif "cookie" in text:
            message = "F2 鉴权/风控失败；请配置有效 Cookie"
        else:
            message = f"F2 exit={result.returncode}"
        return AdapterResult(self.name, False, message)
