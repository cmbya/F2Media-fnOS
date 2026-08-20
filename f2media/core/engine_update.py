from __future__ import annotations

import asyncio
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

from .engine import BINARY_NAMES, engine_command, packaged_engine_path

SOURCES = {
    "yt-dlp": {"repo": "yt-dlp/yt-dlp-nightly-builds"},
    # gallery-dl moved active development to Codeberg; upstream README points Linux
    # users to gdl-org/builds for current standalone nightly executables.
    "gallery-dl": {"repo": "gdl-org/builds"},
}


def _version(path: str | None) -> str | None:
    if not path:
        return None
    try:
        proc = subprocess.run(
            [path, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=15,
        )
        lines = (proc.stdout or "").strip().splitlines()
        return lines[0].strip() if proc.returncode == 0 and lines else None
    except Exception:
        return None


def _pick_asset(name: str, assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    if name == "yt-dlp":
        return next((x for x in assets if x.get("name") == "yt-dlp_linux"), None)
    if name == "gallery-dl":
        exact = ("gallery-dl.bin", "gallery-dl_linux", "gallery-dl_linux.bin", "gallery-dl-linux")
        for candidate in exact:
            found = next((x for x in assets if x.get("name") == candidate), None)
            if found:
                return found
        # Keep this resilient to upstream asset renames while refusing Windows/ARM binaries.
        for asset in assets:
            value = str(asset.get("name") or "").lower()
            if "gallery-dl" not in value:
                continue
            if any(x in value for x in ("windows", ".exe", "arm", "aarch", "macos", "darwin")):
                continue
            if "linux" in value or value.endswith(".bin"):
                return asset
    return None


class EngineUpdater:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "engine-overrides"
        self.root.mkdir(parents=True, exist_ok=True)

    def local_status(self, name: str) -> dict[str, Any]:
        if name not in SOURCES:
            raise ValueError("只支持更新 yt-dlp / gallery-dl")
        current_cmd = engine_command(name)
        packaged = packaged_engine_path(name)
        previous = self.root / name / "previous" / BINARY_NAMES[name]
        override = self.root / name / "current" / BINARY_NAMES[name]
        tag_file = self.root / name / "current" / "VERSION_TAG"
        release_tag = tag_file.read_text(encoding="utf-8").strip() if tag_file.exists() else None
        return {
            "name": name,
            "version": _version(current_cmd[0] if current_cmd else None),
            "path": current_cmd[0] if current_cmd else None,
            "packaged_version": _version(packaged),
            "using_override": override.exists(),
            "release_tag": release_tag,
            "rollback_available": previous.exists() or override.exists(),
        }

    async def check(self, name: str) -> dict[str, Any]:
        source = SOURCES.get(name)
        if not source:
            raise ValueError("只支持更新 yt-dlp / gallery-dl")
        url = f"https://api.github.com/repos/{source['repo']}/releases/latest"
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "F2Media-Updater/0.2"}) as client:
            response = await client.get(url)
            response.raise_for_status()
            release = response.json()
        assets = [x for x in release.get("assets") or [] if isinstance(x, dict)]
        asset = _pick_asset(name, assets)
        if not asset:
            available = ", ".join(str(x.get("name")) for x in assets) or "(none)"
            raise RuntimeError(f"上游最新 Release 没找到适合 x86_64 Linux 的 {name} 文件；assets={available}")
        local = self.local_status(name)
        latest = str(release.get("tag_name") or "")
        return {
            **local,
            "latest_tag": latest,
            "latest_published_at": release.get("published_at"),
            "download_url": asset.get("browser_download_url"),
            "asset_name": asset.get("name"),
            "update_available": self._is_update_available(
                name, str(local.get("version") or ""), latest, str(local.get("release_tag") or "")
            ),
        }

    @staticmethod
    def _is_update_available(name: str, local: str, latest: str, installed_tag: str = "") -> bool:
        if not latest:
            return True
        if installed_tag:
            return installed_tag.lstrip("v") != latest.lstrip("v")
        if not local:
            return True
        if name == "yt-dlp":
            # nightly output: 2026.08.19.233000; tag usually YYYY.MM.DD.HHMMSS
            normalized = local.replace("nightly@", "").strip()
            return normalized != latest.lstrip("v")
        # The packaged gallery-dl executable reports a semantic version while the
        # build repo uses date tags. Until an override has VERSION_TAG, conservatively
        # report that a remote build can be installed.
        return True

    async def update(self, name: str) -> dict[str, Any]:
        remote = await self.check(name)
        url = str(remote.get("download_url") or "")
        if not url:
            raise RuntimeError("没有找到上游下载地址")
        base = self.root / name
        base.mkdir(parents=True, exist_ok=True)
        binary = BINARY_NAMES[name]
        stage = Path(tempfile.mkdtemp(prefix="stage-", dir=base))
        candidate = stage / binary
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30, read=180), follow_redirects=True,
                headers={"User-Agent": "F2Media-Updater/0.2"},
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with candidate.open("wb") as fh:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            if chunk:
                                fh.write(chunk)
            if not candidate.exists() or candidate.stat().st_size < 100_000:
                raise RuntimeError("新引擎文件异常小，拒绝替换")
            candidate.chmod(candidate.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            version = await asyncio.to_thread(_version, str(candidate))
            if not version:
                raise RuntimeError("新引擎 --version 自检失败，未替换当前版本")
            (stage / "VERSION_TAG").write_text(str(remote.get("latest_tag") or "") + "\n", encoding="utf-8")

            current = base / "current"
            previous = base / "previous"
            old_tmp = base / "previous.new"
            if old_tmp.exists():
                shutil.rmtree(old_tmp)
            if current.exists():
                os.replace(current, old_tmp)
            os.replace(stage, current)
            if previous.exists():
                shutil.rmtree(previous)
            if old_tmp.exists():
                os.replace(old_tmp, previous)
            return {**self.local_status(name), "updated": True, "latest_tag": remote.get("latest_tag")}
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)

    def rollback(self, name: str) -> dict[str, Any]:
        if name not in SOURCES:
            raise ValueError("只支持更新 yt-dlp / gallery-dl")
        base = self.root / name
        current = base / "current"
        previous = base / "previous"
        if previous.exists():
            swap = base / "rollback.swap"
            if swap.exists():
                shutil.rmtree(swap)
            if current.exists():
                os.replace(current, swap)
            os.replace(previous, current)
            if swap.exists():
                os.replace(swap, previous)
        elif current.exists():
            # The first online update has no prior override. Removing it cleanly falls
            # back to the packaged engine inside the installed FPK.
            shutil.rmtree(current)
        else:
            raise RuntimeError("没有可回滚版本")
        return {**self.local_status(name), "rolled_back": True}
