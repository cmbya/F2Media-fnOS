from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image

from .core.app_settings import AppSettingsStore
from .core.cookie_format import cookie_header_for_engine, netscape_for_engine
from .core.cookies import CookieStore
from .core.db import Database, now_iso, today_local
from .core.engine import engine_command
from .core.logging import TaskLog
from .core.redact import redact_command, redact_text
from .parsers.common import clean_url, safe_title
from .parse_service import ParseService, YTDLP_COMPAT_FORMAT

PLATFORM_DIR = {
    "douyin": "抖音",
    "kuaishou": "快手",
    "bilibili": "哔哩哔哩",
    "xiaohongshu": "小红书",
    "instagram": "Instagram",
    "twitter": "X",
    "youtube": "YouTube",
    "facebook": "Facebook",
    "tiktok": "TikTok",
}


@dataclass
class TransferResult:
    ok: bool
    path: str | None = None
    message: str = ""


class DownloadService:
    def __init__(
        self,
        settings,
        app_settings: AppSettingsStore,
        db: Database,
        cookies: CookieStore,
        parse_service: ParseService,
        logger: logging.Logger,
    ):
        self.settings = settings
        self.app_settings = app_settings
        self.db = db
        self.cookies = cookies
        self.parse_service = parse_service
        self.logger = logger
        self._running: dict[str, asyncio.Task] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    async def submit_parse_id(self, parse_id: str, *, force: bool = False) -> dict[str, Any]:
        result = self.db.parse_result(parse_id)
        if not result or not result.get("ok"):
            raise ValueError("parse_id 不存在或解析结果不可下载")
        source_key = str(result.get("canonical_url") or result.get("source_url") or "")
        duplicate = self.db.duplicate_today(source_key)
        if duplicate and not force:
            return {
                "ok": False,
                "duplicate": True,
                "downloaded_today": True,
                "message": "今天已经下载过该作品",
                "existing_task": duplicate,
                "parse_id": parse_id,
            }
        task_id = uuid.uuid4().hex[:12]
        row = {
            "id": task_id,
            "source_text": result.get("source_url") or source_key,
            "url": result.get("source_url") or source_key,
            "platform": result.get("platform") or "unknown",
            "status": "queued",
            "output_dir": "",
            "created_at": now_iso(),
            "parse_id": parse_id,
            "title": safe_title(result.get("title"), "无标题"),
            "progress": 0,
            "source_key": source_key,
        }
        self.db.create_task(row)
        self._spawn(task_id)
        return {"ok": True, "duplicate": False, "task": self.db.task(task_id)}

    async def parse_and_submit(self, text: str, *, force: bool = False) -> list[dict[str, Any]]:
        parsed = await self.parse_service.parse_text(text, persist=True)
        output: list[dict[str, Any]] = []
        for result in parsed:
            if not result.get("ok"):
                output.append({"ok": False, "parse": result})
                continue
            submitted = await self.submit_parse_id(str(result["parse_id"]), force=force)
            submitted["parse"] = result
            output.append(submitted)
        return output

    async def retry(self, task_id: str) -> dict[str, Any]:
        row = self.db.task(task_id)
        if not row:
            raise ValueError("task not found")
        parse_id = row.get("parse_id")
        if not parse_id:
            raise ValueError("旧任务没有 parse_id，无法直接重试；请重新解析链接")
        return await self.submit_parse_id(str(parse_id), force=True)

    async def cancel(self, task_id: str) -> bool:
        row = self.db.task(task_id)
        if not row:
            return False
        proc = self._processes.get(task_id)
        if proc and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        task = self._running.get(task_id)
        if task and not task.done():
            task.cancel()
        self.db.update_task(task_id, status="cancelled", message="用户取消任务", finished_at=now_iso())
        TaskLog(self.settings.task_log_dir / f"{task_id}.log").write("WARNING", "用户取消任务")
        return True

    def _spawn(self, task_id: str) -> None:
        task = asyncio.create_task(self._run(task_id), name=f"download-{task_id}")
        self._running[task_id] = task
        task.add_done_callback(lambda done, tid=task_id: self._task_done(tid, done))

    def _task_done(self, task_id: str, task: asyncio.Task) -> None:
        self._running.pop(task_id, None)
        self._processes.pop(task_id, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        self.logger.exception("task %s escaped worker: %s", task_id, exc, exc_info=exc)
        row = self.db.task(task_id)
        if row and row.get("status") not in {"success", "partial", "failed", "cancelled"}:
            self.db.update_task(
                task_id, status="failed", message=f"未捕获异常: {type(exc).__name__}: {exc}",
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
        result = self.db.parse_result(str(row.get("parse_id") or ""))
        if not result:
            self.db.update_task(task_id, status="failed", message="解析结果不存在", finished_at=now_iso())
            log.write("ERROR", "解析结果不存在")
            return

        cookie, _ = self.cookies.get(row["platform"])
        log.write("INFO", f"task_id={task_id} platform={row['platform']} url={row['url']}")
        log.write("INFO", f"parser={result.get('parser')} parse_id={row.get('parse_id')}")
        log.write(
            "INFO",
            f"Cookie状态: {'已配置' if cookie else '未配置'}; format="
            f"{'netscape' if cookie and cookie.lstrip().startswith('# Netscape') else ('header' if cookie else 'none')}",
        )
        self.db.update_task(task_id, status="downloading", adapter=result.get("parser"), started_at=now_iso(), progress=1)

        out_dir = self._allocate_output_dir(result)
        self.db.update_task(task_id, output_dir=str(out_dir), title=out_dir.name)
        log.write("INFO", f"下载目录: {out_dir}")

        try:
            files, expected, failed = await self._download_result(task_id, result, out_dir, cookie, log)
        except asyncio.CancelledError:
            self.db.update_task(task_id, status="cancelled", message="用户取消任务", finished_at=now_iso())
            raise
        except Exception as exc:
            self.logger.exception("download task %s failed", task_id)
            self.db.update_task(task_id, status="failed", message=str(exc), finished_at=now_iso())
            log.write("ERROR", f"下载异常: {type(exc).__name__}: {exc}")
            return

        files = [str(Path(x)) for x in files if Path(x).exists() and Path(x).stat().st_size > 0]
        if expected <= 0:
            status = "failed"
            message = "解析结果没有可下载媒体"
        elif not files:
            status = "failed"
            message = f"0/{expected} 个媒体文件下载成功"
        elif failed == 0 and len(files) >= expected:
            status = "success"
            message = f"{len(files)}/{expected} 个媒体文件下载成功"
        else:
            status = "partial"
            message = f"{len(files)}/{expected} 个媒体文件下载成功，{failed} 个失败"
        self.db.update_task(
            task_id,
            status=status,
            message=message,
            files_json=json.dumps(files, ensure_ascii=False),
            progress=100,
            finished_at=now_iso(),
        )
        log.write("INFO" if status == "success" else "WARNING", f"结果校验: status={status}; {message}")

    def _allocate_output_dir(self, result: dict[str, Any]) -> Path:
        root = self.app_settings.effective_download_dir()
        date_dir = root / today_local()
        platform_dir = date_dir / PLATFORM_DIR.get(str(result.get("platform")), str(result.get("platform") or "其他"))
        title = safe_title(result.get("title"), "无标题")
        candidate = platform_dir / title
        index = 1
        while candidate.exists():
            index += 1
            candidate = platform_dir / f"{title} ({index})"
        candidate.mkdir(parents=True, exist_ok=False)
        return candidate

    async def _download_result(
        self,
        task_id: str,
        result: dict[str, Any],
        out_dir: Path,
        cookie: str | None,
        log: TaskLog,
    ) -> tuple[list[str], int, int]:
        title = safe_title(result.get("title"), out_dir.name)
        files: list[str] = []
        failed = 0
        expected = 0

        live_pairs = [x for x in (result.get("live_photos") or []) if isinstance(x, dict)]
        paired_urls: set[str] = set()
        for pair in live_pairs:
            image_url = clean_url(pair.get("image_url") or pair.get("image"))
            video_url = clean_url(pair.get("video_url") or pair.get("video"))
            if image_url:
                paired_urls.add(image_url)
            if video_url:
                paired_urls.add(video_url)

        for idx, pair in enumerate(live_pairs, start=1):
            image_url = clean_url(pair.get("image_url") or pair.get("image"))
            video_url = clean_url(pair.get("video_url") or pair.get("video"))
            if not image_url or not video_url:
                expected += 2
                failed += 2
                continue
            base = title if idx == 1 else f"{title}{idx}"
            expected += 2
            image = await self._download_image(task_id, image_url, out_dir / f"{base}.jpg", result, cookie, log)
            video = await self._download_video(task_id, video_url, out_dir / f"{base}.mp4", result, cookie, log)
            if image.ok and image.path:
                files.append(image.path)
            else:
                failed += 1
            if video.ok and video.path:
                files.append(video.path)
            else:
                failed += 1
            self._set_progress(task_id, len(files), expected + max(0, len(result.get("media") or []) - len(paired_urls)))

        media = []
        seen: set[tuple[str, str]] = set()
        for raw in result.get("media") or []:
            if not isinstance(raw, dict):
                continue
            url = clean_url(raw.get("url"))
            kind = str(raw.get("type") or "")
            if not url or url in paired_urls or kind in {"audio_track", "live_video"}:
                continue
            key = (kind, url)
            if key in seen:
                continue
            seen.add(key)
            media.append({**raw, "url": url, "type": kind})

        # yt-dlp parse results carry a download plan so separated video/audio are merged by yt-dlp.
        if result.get("download_plan", {}).get("strategy") == "yt-dlp" and result.get("media_type") == "video":
            expected += 1
            transfer = await self._download_with_ytdlp(task_id, result, out_dir, title, cookie, log)
            if transfer.ok and transfer.path:
                files.append(transfer.path)
            else:
                failed += 1
            return files, expected, failed

        image_index = 0
        video_index = 0
        for raw in media:
            kind = raw.get("type")
            expected += 1
            if kind == "image":
                image_index += 1
                base = title if image_index == 1 else f"{title}{image_index}"
                transfer = await self._download_image(task_id, raw["url"], out_dir / f"{base}.jpg", result, cookie, log)
            else:
                video_index += 1
                base = title if video_index == 1 else f"{title}{video_index}"
                transfer = await self._download_video(task_id, raw["url"], out_dir / f"{base}.mp4", result, cookie, log)
            if transfer.ok and transfer.path:
                files.append(transfer.path)
            else:
                failed += 1
            self._set_progress(task_id, len(files), max(expected, len(media) + 2 * len(live_pairs)))
        return files, expected, failed

    def _set_progress(self, task_id: str, completed: int, expected: int) -> None:
        if expected <= 0:
            return
        value = max(1, min(99, int(completed * 100 / expected)))
        self.db.update_task(task_id, progress=value)

    def _request_headers(self, result: dict[str, Any], cookie: str | None) -> dict[str, str]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/143 Safari/537.36"}
        source = clean_url(result.get("source_url"))
        if source:
            headers["Referer"] = source
        cookie_header = cookie_header_for_engine(cookie)
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    async def _download_http(
        self,
        url: str,
        target: Path,
        result: dict[str, Any],
        cookie: str | None,
        log: TaskLog,
    ) -> tuple[Path | None, str]:
        last = ""
        headers = self._request_headers(result, cookie)
        for attempt in range(1, 4):
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.unlink(missing_ok=True)
            try:
                log.write("INFO", f"HTTP 下载第 {attempt}/3 次: {url}")
                async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60, read=180), headers=headers) as client:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        ctype = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        with tmp.open("wb") as fp:
                            async for chunk in response.aiter_bytes(1024 * 512):
                                if chunk:
                                    fp.write(chunk)
                if tmp.exists() and tmp.stat().st_size > 0:
                    return tmp, ctype
                last = "下载结果为空"
            except asyncio.CancelledError:
                tmp.unlink(missing_ok=True)
                raise
            except Exception as exc:
                last = redact_text(f"{type(exc).__name__}: {exc}")
                log.write("WARNING", f"HTTP 下载失败: {last}")
                tmp.unlink(missing_ok=True)
                if attempt < 3:
                    await asyncio.sleep(attempt)
        log.write("ERROR", f"HTTP 下载最终失败: {last}")
        return None, ""

    async def _download_image(
        self,
        task_id: str,
        url: str,
        target: Path,
        result: dict[str, Any],
        cookie: str | None,
        log: TaskLog,
    ) -> TransferResult:
        temp, _ = await self._download_http(url, target, result, cookie, log)
        if not temp:
            return TransferResult(False, message="图片下载失败")
        try:
            await asyncio.to_thread(self._to_jpeg, temp, target)
            if target.exists() and target.stat().st_size > 0:
                log.write("INFO", f"图片完成: {target.name} size={target.stat().st_size}")
                return TransferResult(True, str(target))
        except Exception as exc:
            log.write("WARNING", f"Pillow 转 JPEG 失败，尝试 FFmpeg: {type(exc).__name__}: {exc}")
            ffmpeg = self._ffmpeg()
            if ffmpeg:
                rc = await self._run_cmd(task_id, [ffmpeg, "-y", "-loglevel", "error", "-i", str(temp), "-frames:v", "1", str(target)], log, timeout=120)
                if rc == 0 and target.exists() and target.stat().st_size > 0:
                    temp.unlink(missing_ok=True)
                    return TransferResult(True, str(target))
        finally:
            temp.unlink(missing_ok=True)
        return TransferResult(False, message="图片格式转换失败")

    @staticmethod
    def _to_jpeg(source: Path, target: Path) -> None:
        with Image.open(source) as image:
            if image.mode not in {"RGB", "L"}:
                if "A" in image.getbands():
                    canvas = Image.new("RGB", image.size, "white")
                    alpha = image.getchannel("A")
                    canvas.paste(image.convert("RGB"), mask=alpha)
                    image = canvas
                else:
                    image = image.convert("RGB")
            elif image.mode == "L":
                image = image.convert("RGB")
            image.save(target, format="JPEG", quality=95, subsampling=0, optimize=True)

    async def _download_video(
        self,
        task_id: str,
        url: str,
        target: Path,
        result: dict[str, Any],
        cookie: str | None,
        log: TaskLog,
    ) -> TransferResult:
        parsed = urlparse(url)
        low = url.lower()
        is_hls = parsed.path.lower().endswith(".m3u8") or "mpegurl" in low
        temp = target.with_suffix(".source.mp4")
        temp.unlink(missing_ok=True)
        if is_hls:
            ffmpeg = self._ffmpeg()
            if not ffmpeg:
                return TransferResult(False, message="HLS 需要 FFmpeg")
            headers = self._request_headers(result, cookie)
            header_blob = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
            rc = await self._run_cmd(
                task_id,
                [ffmpeg, "-y", "-loglevel", "error", "-headers", header_blob, "-i", url, "-c", "copy", str(temp)],
                log,
                timeout=1200,
            )
            if rc != 0 or not temp.exists() or temp.stat().st_size <= 0:
                return TransferResult(False, message="HLS 下载失败")
        else:
            downloaded, _ = await self._download_http(url, temp, result, cookie, log)
            if not downloaded:
                return TransferResult(False, message="视频下载失败")
            if downloaded != temp:
                shutil.move(str(downloaded), temp)
        ok = await self._ensure_compatible_mp4(task_id, temp, target, log)
        temp.unlink(missing_ok=True)
        if ok:
            log.write("INFO", f"视频完成: {target.name} size={target.stat().st_size}")
            return TransferResult(True, str(target))
        return TransferResult(False, message="视频兼容转换失败")

    async def _download_with_ytdlp(
        self,
        task_id: str,
        result: dict[str, Any],
        out_dir: Path,
        title: str,
        cookie: str | None,
        log: TaskLog,
    ) -> TransferResult:
        prefix = engine_command("yt-dlp")
        if not prefix:
            return TransferResult(False, message="yt-dlp 不可用")
        tmp_dir = self.settings.temp_dir / f"task-{task_id}-yt"
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        cookie_file: Path | None = None
        if cookie:
            jar = netscape_for_engine(str(result.get("platform")), cookie)
            if jar:
                cookie_file = self.settings.temp_dir / f"{task_id}-cookies.txt"
                cookie_file.write_text(jar, encoding="utf-8")
                cookie_file.chmod(0o600)
        cmd = [
            *prefix, "--verbose", "--newline", "--no-color", "--ignore-config", "--no-mtime", "--no-update",
            "--windows-filenames", "--no-playlist", "--merge-output-format", "mp4",
            "--retries", "3", "--fragment-retries", "3", "--retry-sleep", "http:1:3",
            "-f", str((result.get("download_plan") or {}).get("format") or YTDLP_COMPAT_FORMAT),
            "-P", str(tmp_dir), "-o", "source.%(ext)s",
        ]
        ffmpeg_dir = os.getenv("F2MEDIA_FFMPEG_DIR", "").strip()
        if ffmpeg_dir:
            cmd += ["--ffmpeg-location", ffmpeg_dir]
        deno = os.getenv("F2MEDIA_DENO_BIN", "").strip()
        if deno and Path(deno).exists():
            cmd += ["--js-runtimes", f"deno:{deno}"]
        if cookie_file:
            cmd += ["--cookies", str(cookie_file)]
        cmd.append(str(result.get("source_url")))
        try:
            rc = await self._run_cmd(task_id, cmd, log, timeout=3600, status="downloading")
        finally:
            if cookie_file:
                cookie_file.unlink(missing_ok=True)
        candidates = [p for p in tmp_dir.iterdir() if p.is_file() and p.stat().st_size > 0 and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}]
        if rc != 0 or not candidates:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return TransferResult(False, message=f"yt-dlp exit={rc}; 未生成视频文件")
        source = max(candidates, key=lambda p: p.stat().st_size)
        target = out_dir / f"{title}.mp4"
        self.db.update_task(task_id, status="merging", progress=95)
        ok = await self._ensure_compatible_mp4(task_id, source, target, log)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        self.db.update_task(task_id, status="downloading", progress=98)
        return TransferResult(ok, str(target) if ok else None, "")

    def _ffmpeg(self) -> str | None:
        path = os.getenv("FFMPEG_BINARY", "").strip() or os.getenv("F2MEDIA_FFMPEG_BIN", "").strip()
        if path and Path(path).exists():
            return path
        folder = os.getenv("F2MEDIA_FFMPEG_DIR", "").strip()
        if folder and (Path(folder) / "ffmpeg").exists():
            return str(Path(folder) / "ffmpeg")
        return shutil.which("ffmpeg")

    def _ffprobe(self) -> str | None:
        path = os.getenv("F2MEDIA_FFPROBE_BIN", "").strip()
        if path and Path(path).exists():
            return path
        folder = os.getenv("F2MEDIA_FFMPEG_DIR", "").strip()
        if folder and (Path(folder) / "ffprobe").exists():
            return str(Path(folder) / "ffprobe")
        return shutil.which("ffprobe")

    async def _ensure_compatible_mp4(self, task_id: str, source: Path, target: Path, log: TaskLog) -> bool:
        ffprobe = self._ffprobe()
        ffmpeg = self._ffmpeg()
        compatible = False
        if ffprobe:
            proc = await asyncio.create_subprocess_exec(
                ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", str(source),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            if proc.returncode == 0:
                try:
                    streams = json.loads(out.decode("utf-8", "replace")).get("streams") or []
                    video_codecs = [x.get("codec_name") for x in streams if x.get("codec_type") == "video"]
                    audio_codecs = [x.get("codec_name") for x in streams if x.get("codec_type") == "audio"]
                    compatible = bool(video_codecs) and all(x == "h264" for x in video_codecs) and all(x in {"aac", None} for x in audio_codecs)
                    log.write("INFO", f"媒体编码检查: video={video_codecs} audio={audio_codecs} compatible={compatible}")
                except Exception:
                    compatible = False
        if compatible:
            shutil.move(str(source), target)
            return target.exists() and target.stat().st_size > 0
        if not ffmpeg:
            return False
        self.db.update_task(task_id, status="merging", progress=95)
        rc = await self._run_cmd(
            task_id,
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(target)],
            log,
            timeout=3600,
            status="merging",
        )
        self.db.update_task(task_id, status="downloading", progress=98)
        return rc == 0 and target.exists() and target.stat().st_size > 0

    async def _run_cmd(
        self,
        task_id: str,
        cmd: list[str],
        log: TaskLog,
        *,
        timeout: int,
        status: str | None = None,
    ) -> int:
        log.write("INFO", f"执行命令: {redact_command(cmd)}")
        if status:
            self.db.update_task(task_id, status=status)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        self._processes[task_id] = proc

        async def consume() -> None:
            assert proc.stdout is not None
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                line = redact_text(raw.decode("utf-8", "replace").rstrip())
                if line:
                    log.write("ENGINE", line)

        try:
            await asyncio.wait_for(asyncio.gather(consume(), proc.wait()), timeout=timeout)
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        except asyncio.TimeoutError:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            log.write("ERROR", f"命令超过 {timeout}s，已终止")
            return 124
        finally:
            if self._processes.get(task_id) is proc:
                self._processes.pop(task_id, None)
        rc = proc.returncode or 0
        log.write("INFO", f"命令退出码: {rc}")
        return rc
