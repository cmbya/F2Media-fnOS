from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from .adapters.base import AdapterContext
from .adapters.registry import AdapterRegistry
from .core.config import Settings
from .core.app_settings import AppSettingsStore
from .core.cookies import CookieStore
from .core.db import Database, now_iso
from .core.logging import TaskLog
from .core.platforms import parse_input
from .core.validate import new_media, snapshot, validate_output


class DownloadService:
    def __init__(self, settings: Settings, app_settings: AppSettingsStore, db: Database, cookies: CookieStore, registry: AdapterRegistry, logger: logging.Logger):
        self.settings = settings
        self.app_settings = app_settings
        self.db = db
        self.cookies = cookies
        self.registry = registry
        self.logger = logger
        self._running: set[asyncio.Task] = set()

    async def submit(self, text: str) -> list[dict]:
        parsed = parse_input(text)
        created = []
        for item in parsed:
            task_id = uuid.uuid4().hex[:12]
            out = self.app_settings.effective_download_dir() / item.platform
            out.mkdir(parents=True, exist_ok=True)
            row = {
                "id": task_id, "source_text": text, "url": item.url,
                "platform": item.platform, "status": "queued",
                "output_dir": str(out), "created_at": now_iso(),
            }
            self.db.create_task(row)
            task = asyncio.create_task(self._run(task_id), name=f"download-{task_id}")
            self._running.add(task)
            task.add_done_callback(lambda done, tid=task_id: self._task_done(tid, done))
            created.append(self.db.task(task_id))
        return created

    def _task_done(self, task_id: str, task: asyncio.Task) -> None:
        self._running.discard(task)
        if task.cancelled():
            self.logger.warning("task %s cancelled", task_id)
            return
        exc = task.exception()
        if exc is None:
            return
        self.logger.exception("task %s escaped worker: %s", task_id, exc, exc_info=exc)
        row = self.db.task(task_id)
        if row and row.get("status") in {"queued", "running"}:
            self.db.update_task(
                task_id,
                status="failed",
                message=f"未捕获异常: {type(exc).__name__}: {exc}",
                finished_at=now_iso(),
            )
        TaskLog(self.settings.task_log_dir / f"{task_id}.log").write(
            "ERROR", f"未捕获异常: {type(exc).__name__}: {exc}"
        )

    async def _run(self, task_id: str) -> None:
        row = self.db.task(task_id)
        if not row:
            return
        log = TaskLog(self.settings.task_log_dir / f"{task_id}.log")
        self.db.update_task(task_id, status="running", started_at=now_iso())
        log.write("INFO", f"task_id={task_id} platform={row['platform']} url={row['url']}")
        if row["platform"] == "unknown":
            self.db.update_task(task_id, status="failed", message="不支持或无法识别的平台", finished_at=now_iso())
            log.write("ERROR", "无法识别平台")
            return

        cookie, extra = self.cookies.get(row["platform"])
        log.write("INFO", f"Cookie状态: {'已配置' if cookie else '未配置'}; extra={'已配置' if extra else '未配置'}")
        out = Path(row["output_dir"])
        before = snapshot(out)
        adapters = self.registry.for_platform(row["platform"])
        if not adapters:
            self.db.update_task(task_id, status="failed", message="没有可用适配器", finished_at=now_iso())
            log.write("ERROR", "没有可用适配器")
            return

        last_message = ""
        best_partial_files: list[str] = []
        best_partial_message = ""
        for adapter in adapters:
            available, detail = adapter.available()
            log.write("INFO", f"尝试适配器 {adapter.name}: available={available} detail={detail}")
            if not available:
                last_message = detail
                continue
            self.db.update_task(task_id, adapter=adapter.name)
            ctx = AdapterContext(
                task_id=task_id, platform=row["platform"], url=row["url"],
                output_dir=out, temp_dir=self.settings.temp_dir,
                state_dir=self.settings.data_dir / "engine-state" / row["platform"],
                cookie=cookie, extra_secret=extra, task_log=log,
            )
            ctx.state_dir.mkdir(parents=True, exist_ok=True)
            try:
                result = await adapter.download(ctx)
            except Exception as e:
                self.logger.exception("task %s adapter %s crashed", task_id, adapter.name)
                log.write("ERROR", f"适配器异常: {type(e).__name__}: {e}")
                last_message = str(e)
                continue

            files = new_media(out, before)
            status, validation = validate_output(row["platform"], files)
            log.write("INFO", f"结果校验: engine_ok={result.ok}; status={status}; {validation}")
            if result.ok and status == "success":
                self.db.update_task(
                    task_id, status="success", message=validation,
                    files_json=json.dumps(files, ensure_ascii=False), finished_at=now_iso(),
                )
                return

            # Keep partial files, but still try later adapters. This fixes the old failure mode
            # where an engine created only a thumbnail/static image and blocked a better fallback.
            if files:
                best_partial_files = files
                best_partial_message = validation if result.ok else f"适配器异常但生成了文件：{validation}"
                log.write("WARNING", f"当前仅部分成功，继续 fallback: {best_partial_message}")
            else:
                log.write("WARNING", f"适配器 {adapter.name} 未生成文件，继续 fallback")
            last_message = result.message

        if best_partial_files:
            self.db.update_task(
                task_id, status="partial", message=best_partial_message or "仅生成部分文件",
                files_json=json.dumps(best_partial_files, ensure_ascii=False), finished_at=now_iso(),
            )
            log.write("WARNING", "所有 fallback 已尝试，保留部分成功结果")
            return

        self.db.update_task(task_id, status="failed", message=last_message or "所有适配器均失败", finished_at=now_iso())
        log.write("ERROR", "所有适配器均失败")
