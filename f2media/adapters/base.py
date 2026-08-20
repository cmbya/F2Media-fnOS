from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from f2media.core.logging import TaskLog


@dataclass
class AdapterContext:
    task_id: str
    platform: str
    url: str
    output_dir: Path
    temp_dir: Path
    state_dir: Path
    cookie: str | None
    extra_secret: str | None
    task_log: TaskLog


@dataclass
class AdapterResult:
    adapter: str
    ok: bool
    message: str
    metadata: dict = field(default_factory=dict)


class Adapter:
    name = "base"
    platforms: set[str] = set()

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    async def download(self, ctx: AdapterContext) -> AdapterResult:
        raise NotImplementedError
