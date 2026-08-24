from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .logging import TaskLog
from .redact import redact_command, redact_text


@dataclass
class ProcessResult:
    returncode: int
    lines: list[str]


async def run_process(
    cmd: Sequence[str],
    task_log: TaskLog,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int = 900,
) -> ProcessResult:
    task_log.write("INFO", f"执行适配器命令: {redact_command(cmd)}")
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        env=merged_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    lines: list[str] = []

    async def collect() -> None:
        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = redact_text(raw.decode("utf-8", errors="replace").rstrip())
            if line:
                lines.append(line)
                task_log.write("ENGINE", line)

    try:
        await asyncio.wait_for(asyncio.gather(collect(), proc.wait()), timeout=timeout)
    except asyncio.TimeoutError:
        task_log.write("ERROR", f"命令超过 {timeout}s，终止子进程")
        proc.kill()
        await proc.wait()
        return ProcessResult(124, lines)
    task_log.write("INFO", f"适配器退出码: {proc.returncode}")
    return ProcessResult(proc.returncode or 0, lines)
