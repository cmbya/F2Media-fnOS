from __future__ import annotations

import asyncio
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from .engine import BINARY_NAMES, engine_command, packaged_engine_path

SOURCES = {
    "yt-dlp": {
        "repo": "yt-dlp/yt-dlp-nightly-builds",
        "kind": "raw",
        "asset_name": "yt-dlp_linux",
        "latest_url": "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest",
    },
    # Stable gallery-dl moved active development/releases to Codeberg.
    # Use PyPI only to discover the stable version, then download the official
    # upstream Linux standalone binary from Codeberg.
    "gallery-dl": {
        "kind": "raw",
        "asset_name": "gallery-dl.bin",
        "pypi_json": "https://pypi.org/pypi/gallery-dl/json",
        "download_template": "https://codeberg.org/mikf/gallery-dl/releases/download/v{version}/gallery-dl.bin",
    },
    "x-cli": {
        "repo": "tamnd/x-cli",
        "kind": "archive",
        "archive_binary": "x",
        "latest_url": "https://github.com/tamnd/x-cli/releases/latest",
        # GoReleaser config: x_<version>_<os>_<arch>.tar.gz
        "asset_template": "x_{version}_linux_amd64.tar.gz",
    },
}


def _version(path: str | None, name: str | None = None) -> str | None:
    if not path:
        return None
    commands = [[path, "--version"]]
    if name == "x-cli":
        commands.append([path, "version"])
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
            lines = (proc.stdout or "").strip().splitlines()
            if proc.returncode == 0 and lines:
                return lines[0].strip()
        except Exception:
            continue
    return None


def _is_linux_amd64_archive(value: str) -> bool:
    v = value.lower()
    return (
        ("linux" in v)
        and ("amd64" in v or "x86_64" in v)
        and (v.endswith(".tar.gz") or v.endswith(".tgz") or v.endswith(".zip"))
        and not any(x in v for x in ("arm64", "aarch64", "armv7", "386", "i386"))
    )


def _pick_asset(name: str, assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    if name == "yt-dlp":
        return next((x for x in assets if x.get("name") == "yt-dlp_linux"), None)
    if name == "gallery-dl":
        exact = ("gallery-dl.bin", "gallery-dl_linux", "gallery-dl_linux.bin", "gallery-dl-linux")
        for candidate in exact:
            found = next((x for x in assets if x.get("name") == candidate), None)
            if found:
                return found
        for asset in assets:
            value = str(asset.get("name") or "").lower()
            if "gallery-dl" not in value:
                continue
            if any(x in value for x in ("windows", ".exe", "arm", "aarch", "macos", "darwin")):
                continue
            if "linux" in value or value.endswith(".bin"):
                return asset
    if name == "x-cli":
        candidates = [x for x in assets if _is_linux_amd64_archive(str(x.get("name") or ""))]
        return next((x for x in candidates if str(x.get("name") or "").lower().startswith("x_")), candidates[0] if candidates else None)
    return None


def _asset_name(name: str, latest_tag: str) -> str:
    source = SOURCES[name]
    if source.get("asset_name"):
        return str(source["asset_name"])
    version = latest_tag.lstrip("v")
    template = str(source.get("asset_template") or "")
    if not template:
        raise RuntimeError(f"{name} 没有配置更新资产名称")
    return template.format(version=version, tag=latest_tag)


def _download_url(name: str, latest_tag: str, asset_name: str) -> str:
    source = SOURCES[name]
    if source.get("download_template"):
        return str(source["download_template"]).format(
            version=latest_tag.lstrip("v"), tag=latest_tag, asset=asset_name
        )
    repo = str(source.get("repo") or "")
    if not repo:
        raise RuntimeError(f"{name} 没有配置上游仓库")
    return f"https://github.com/{repo}/releases/download/{latest_tag}/{asset_name}"


def _extract_archive_binary(name: str, archive: Path, output: Path) -> None:
    wanted = str(SOURCES[name].get("archive_binary") or "")
    candidates: list[tuple[str, bytes]] = []
    lower = archive.name.lower()
    if lower.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf.getmembers():
                if not member.isfile() or Path(member.name).name != wanted:
                    continue
                fh = tf.extractfile(member)
                if fh:
                    candidates.append((member.name, fh.read()))
    elif lower.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if Path(member).name == wanted and not member.endswith("/"):
                    candidates.append((member, zf.read(member)))
    else:
        raise RuntimeError(f"不支持的 {name} 更新包格式: {archive.name}")
    if not candidates:
        raise RuntimeError(f"{name} 更新包内未找到可执行文件 {wanted}")
    output.write_bytes(candidates[0][1])


class EngineUpdater:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "engine-overrides"
        self.root.mkdir(parents=True, exist_ok=True)

    def local_status(self, name: str) -> dict[str, Any]:
        if name not in SOURCES:
            raise ValueError("不支持的在线解析引擎")
        current_cmd = engine_command(name)
        packaged = packaged_engine_path(name)
        previous = self.root / name / "previous" / BINARY_NAMES[name]
        override = self.root / name / "current" / BINARY_NAMES[name]
        tag_file = self.root / name / "current" / "VERSION_TAG"
        release_tag = tag_file.read_text(encoding="utf-8").strip() if tag_file.exists() else None
        return {
            "name": name,
            "version": _version(current_cmd[0] if current_cmd else None, name),
            "path": current_cmd[0] if current_cmd else None,
            "packaged_version": _version(packaged, name),
            "using_override": override.exists(),
            "release_tag": release_tag,
            "rollback_available": previous.exists() or override.exists(),
        }

    async def _latest_tag(self, name: str, client: httpx.AsyncClient) -> str:
        source = SOURCES[name]
        if source.get("pypi_json"):
            response = await client.get(str(source["pypi_json"]))
            response.raise_for_status()
            version = str((response.json().get("info") or {}).get("version") or "").strip()
            if not version:
                raise RuntimeError(f"无法识别 {name} 最新 PyPI 版本")
            return f"v{version}"

        latest_url = str(source.get("latest_url") or "")
        if not latest_url:
            raise RuntimeError(f"{name} 没有配置 latest URL")
        response = await client.get(latest_url)
        response.raise_for_status()
        path = urlparse(str(response.url)).path.rstrip("/")
        latest = unquote(path.rsplit("/", 1)[-1]) if "/tag/" in path else ""
        if not latest:
            raise RuntimeError(f"无法识别 {name} 最新 Release 标签")
        return latest

    async def check(self, name: str) -> dict[str, Any]:
        if name not in SOURCES:
            raise ValueError("不支持的在线解析引擎")

        headers = {"User-Agent": "F2Media-Updater/0.5.3", "Accept": "text/html,application/json,*/*"}
        async with httpx.AsyncClient(timeout=25, headers=headers, follow_redirects=True) as client:
            latest = await self._latest_tag(name, client)

        asset_name = _asset_name(name, latest)
        download_url = _download_url(name, latest, asset_name)
        local = self.local_status(name)
        return {
            **local,
            "latest_tag": latest,
            "latest_published_at": None,
            "download_url": download_url,
            "asset_name": asset_name,
            "update_available": self._is_update_available(
                name, str(local.get("version") or ""), latest, str(local.get("release_tag") or "")
            ),
        }

    @staticmethod
    def _is_update_available(name: str, local: str, latest: str, installed_tag: str = "") -> bool:
        if not latest:
            return True
        latest_norm = latest.lstrip("v")
        if installed_tag:
            return installed_tag.lstrip("v") != latest_norm
        if not local:
            return True
        if name == "yt-dlp":
            normalized = local.replace("nightly@", "").strip()
            return normalized != latest_norm
        if name == "gallery-dl":
            # standalone prints plain version such as 1.32.9
            return latest_norm not in local
        if name == "x-cli":
            return latest_norm not in local
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
        downloaded = stage / str(remote.get("asset_name") or "download.bin")
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30, read=180), follow_redirects=True,
                headers={"User-Agent": "F2Media-Updater/0.5.3"},
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with downloaded.open("wb") as fh:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            if chunk:
                                fh.write(chunk)
            if not downloaded.exists() or downloaded.stat().st_size < 100_000:
                raise RuntimeError("新引擎文件异常小，拒绝替换")
            if SOURCES[name]["kind"] == "archive":
                _extract_archive_binary(name, downloaded, candidate)
                downloaded.unlink(missing_ok=True)
            else:
                os.replace(downloaded, candidate)
            candidate.chmod(candidate.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            version = await asyncio.to_thread(_version, str(candidate), name)
            if not version:
                raise RuntimeError("新引擎版本自检失败，未替换当前版本")
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
            raise ValueError("不支持的在线解析引擎")
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
            shutil.rmtree(current)
        else:
            raise RuntimeError("没有可回滚版本")
        return {**self.local_status(name), "rolled_back": True}
