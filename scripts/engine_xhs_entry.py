#!/usr/bin/env python3
"""F2Media non-interactive XHS-Downloader 2.7 sidecar."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

VERSION = "2.7"


def _snapshot(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


async def _run(url: str, output: Path) -> int:
    from source import XHS

    cookie = os.getenv("F2MEDIA_VENDOR_COOKIE", "").strip()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    before = _snapshot(output)

    state = Path(os.getenv("F2MEDIA_VENDOR_STATE", str(output.parent / ".xhs-state"))).resolve()
    state.mkdir(parents=True, exist_ok=True)

    async with XHS(
        # pathlib keeps an absolute folder_name absolute. This leaves XHS mutable
        # state under appdata while media lands exactly in F2Media's output path.
        work_path=state,
        folder_name=str(output),
        cookie=cookie,
        record_data=False,
        image_format="AUTO",
        folder_mode=False,
        image_download=True,
        video_download=True,
        live_download=True,
        download_record=False,
        language="zh_CN",
        author_archive=True,
        write_mtime=True,
        note_format="",
    ) as xhs:
        result = await xhs.extract(url, download=True)
        if not result:
            print("XHS-Downloader returned no work data")

    added = _snapshot(output) - before
    if not added:
        print("XHS-Downloader completed but no new media file was created")
        return 3
    print(f"XHS-Downloader created {len(added)} new file(s)")
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
        import sys
        from source import XHS
        sig = inspect.signature(XHS)
        required = {"work_path", "folder_name", "cookie", "image_download", "video_download", "live_download"}
        missing = required - set(sig.parameters)
        if missing:
            raise RuntimeError(f"XHS 2.7 API changed; missing={sorted(missing)} signature={sig}")
        if "fastmcp" in sys.modules:
            raise RuntimeError("XHS reduced sidecar unexpectedly imported fastmcp")
        print(f"XHS-Downloader {VERSION} reduced import/API OK: {sig}; fastmcp_not_loaded=true")
        return
    if not args.url or not args.output:
        parser.error("--url and --output are required")
    raise SystemExit(asyncio.run(_run(args.url, Path(args.output))))


if __name__ == "__main__":
    main()
