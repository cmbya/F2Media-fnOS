from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx

from .base import Adapter, AdapterContext, AdapterResult
from f2media.core.cookie_format import cookie_header_for_engine, netscape_for_engine
from f2media.core.runner import run_process
from f2media.core.engine import engine_command


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36"


async def _normalize_facebook_url(ctx: AdapterContext) -> str:
    url = ctx.url
    path = urlparse(url).path.lower()
    if "/share/" not in path:
        return url
    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"}
    cookie = cookie_header_for_engine(ctx.cookie)
    if cookie:
        headers["Cookie"] = cookie
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20, headers=headers) as client:
            response = await client.get(url)
        final = str(response.url)
        if final and final != url:
            ctx.task_log.write("INFO", f"Facebook 分享链接规范化: {url} -> {final}")
            return final
    except Exception as exc:
        ctx.task_log.write("WARNING", f"Facebook 分享链接规范化失败，继续使用原链接: {type(exc).__name__}: {exc}")
    return url


class GalleryDlAdapter(Adapter):
    name = "gallery-dl"
    platforms = {"instagram", "facebook", "twitter", "tiktok"}

    def available(self) -> tuple[bool, str]:
        cmd = engine_command("gallery-dl")
        return (bool(cmd), " ".join(cmd) if cmd else "gallery-dl sidecar not found")

    async def download(self, ctx: AdapterContext) -> AdapterResult:
        ok, reason = self.available()
        if not ok:
            return AdapterResult(self.name, False, reason)
        conf = {
            "extractor": {"base-directory": str(ctx.output_dir)},
            "output": {"mode": "terminal", "progress": False},
            # Do not let gallery-dl try ~/.cache under fnOS package users.
            "cache": {"file": ":memory:"},
        }
        # Explicitly ask gallery-dl to include Facebook videos as well as images.
        if ctx.platform == "facebook":
            conf["extractor"]["facebook"] = {"videos": True}
        cookie_file = None
        if ctx.cookie:
            try:
                jar = netscape_for_engine(ctx.platform, ctx.cookie)
                cookie_file = ctx.temp_dir / f"{ctx.task_id}-gdl-cookies.txt"
                cookie_file.write_text(jar or "", encoding="utf-8")
                cookie_file.chmod(0o600)
                conf["extractor"]["cookies"] = str(cookie_file)
            except Exception as exc:
                ctx.task_log.write("WARNING", f"Cookie 转换失败，本次 gallery-dl 不传 Cookie: {type(exc).__name__}: {exc}")
        conf_path = ctx.temp_dir / f"{ctx.task_id}-gallery.json"
        conf_path.write_text(json.dumps(conf, ensure_ascii=False), encoding="utf-8")
        conf_path.chmod(0o600)
        prefix = engine_command("gallery-dl") or ["gallery-dl"]
        target_url = await _normalize_facebook_url(ctx) if ctx.platform == "facebook" else ctx.url
        cmd = [*prefix, "--config", str(conf_path), "--verbose", target_url]
        child_env = {
            "HOME": str(ctx.state_dir),
            "XDG_CACHE_HOME": str(ctx.state_dir / "cache"),
            "XDG_CONFIG_HOME": str(ctx.state_dir / "config"),
        }
        for key in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
            from pathlib import Path
            Path(child_env[key]).mkdir(parents=True, exist_ok=True)
        try:
            result = await run_process(cmd, ctx.task_log, cwd=ctx.state_dir, env=child_env, timeout=1800)
        finally:
            conf_path.unlink(missing_ok=True)
            if cookie_file:
                cookie_file.unlink(missing_ok=True)
        if result.returncode == 0:
            return AdapterResult(self.name, True, "gallery-dl success")
        text = "\n".join(result.lines[-120:]).lower()
        if "redirect to login" in text or "registered users" in text or "login" in text and "cookie" in text:
            message = "需要配置有效 Cookie 后重试"
        elif "403 forbidden" in text:
            message = "远端返回 403；建议配置 Cookie 后重试"
        elif "unsupported url" in text:
            message = "gallery-dl 不支持该链接形式"
        else:
            message = f"gallery-dl exit={result.returncode}"
        return AdapterResult(self.name, False, message)
