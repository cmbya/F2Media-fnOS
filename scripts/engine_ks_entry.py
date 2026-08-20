#!/usr/bin/env python3
"""F2Media non-interactive KS-Downloader 1.6 sidecar.

The upstream executable is interactive and normally stores mutable state beside the
executable.  This wrapper bypasses that UI/config layer and injects writable fnOS
paths before constructing KS, while keeping the upstream extraction/downloader code.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

VERSION = "1.6"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


def _snapshot(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


async def _run(url: str, output: Path) -> int:
    cookie = os.getenv("F2MEDIA_VENDOR_COOKIE", "").strip()
    state = Path(os.getenv("F2MEDIA_VENDOR_STATE", str(output.parent / ".ks-state"))).resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    # Import the upstream implementation, then replace only its config/parameter
    # adapters.  KS itself, Examiner, DetailPage and Downloader remain upstream code.
    import source.app.app as upstream

    class PortableConfig:
        def __init__(self, console):
            self.console = console

        def read(self):
            return {}

        def write(self, *_args, **_kwargs):
            return None

    class PortableParameter:
        def __init__(self, console, cleaner, **_kwargs):
            self.console = console
            self.cleaner = cleaner
            self.root = state
            self.mapping_data = {}
            self.timeout = 15
            self.max_retry = 4
            self.proxy = {}
            # Keep KS internal Data/Temp/SQLite under F2Media appdata while sending
            # downloaded media to the user-selected absolute output directory.
            self.work_path = state
            self.folder_name = str(output)
            self.name_format = "发布日期 作者昵称 作品描述"
            self.name_length = 120
            # 1.6 config names use plural cookies / impersonate / download_chunk.
            # Keep legacy aliases too because older internal helpers may still reference them.
            self.cookies = cookie
            self.cookie = cookie
            self.cover = ""
            self.music = False
            self.data_record = False
            self.download_chunk = 2 * 1024 * 1024
            self.chunk = self.download_chunk
            self.impersonate = "chrome146"
            self.user_agent = UA
            self.folder_mode = False
            self.author_archive = True
            self.max_workers = 4

    upstream.Config = PortableConfig
    upstream.Parameter = PortableParameter

    before = _snapshot(output)
    app = upstream.KS(server_mode=True)
    app.set_language("zh_CN")
    try:
        async with app:
            message = await app.detail(url, download=True)
            if isinstance(message, str) and message:
                print(message)
    finally:
        # __aexit__ closes the manager when the context was entered successfully.
        pass

    added = _snapshot(output) - before
    if not added:
        print("KS-Downloader completed but no new file was created")
        return 3
    print(f"KS-Downloader created {len(added)} new file(s)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.version:
        print(VERSION)
        return
    if args.selfcheck:
        import inspect
        import source.app.app as upstream
        sig = inspect.signature(upstream.KS)
        if "server_mode" not in sig.parameters:
            raise RuntimeError(f"KS 1.6 API changed: {sig}")
        for attr in ("Config", "Parameter"):
            if not hasattr(upstream, attr):
                raise RuntimeError(f"KS 1.6 module missing {attr}")
        print(f"KS-Downloader {VERSION} import/API OK: {sig}")
        return
    if not args.url or not args.output:
        parser.error("--url and --output are required")
    raise SystemExit(asyncio.run(_run(args.url, Path(args.output))))


if __name__ == "__main__":
    main()
