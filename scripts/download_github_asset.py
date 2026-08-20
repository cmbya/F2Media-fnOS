#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import urllib.request

API = "https://api.github.com"


def request_json(url: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "F2Media-builder",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_stream(src, dst, length: int = 1024 * 1024) -> None:
    while True:
        block = src.read(length)
        if not block:
            return
        dst.write(block)


def release_endpoint(repo: str, tag: str) -> str:
    # GitHub exposes latest and tag-name lookup as different endpoints.
    if tag.lower() == "latest":
        return f"{API}/repos/{repo}/releases/latest"
    return f"{API}/repos/{repo}/releases/tags/{tag}"


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit("usage: download_github_asset.py owner/repo tag|latest asset_name dest")

    repo, tag, name, dest_s = sys.argv[1:]
    release = request_json(release_endpoint(repo, tag))
    resolved_tag = str(release.get("tag_name") or tag)
    asset = next((item for item in release.get("assets", []) if item.get("name") == name), None)
    if asset is None:
        names = ", ".join(str(item.get("name")) for item in release.get("assets", []))
        raise SystemExit(
            f"asset not found: repo={repo} requested={tag} resolved={resolved_tag} "
            f"name={name}; available=[{names}]"
        )

    digest = str(asset.get("digest") or "")
    if not digest.startswith("sha256:"):
        # Do not silently accept an unverified binary. A missing GitHub digest is a hard build error.
        raise SystemExit(
            f"GitHub asset has no SHA256 digest: repo={repo} tag={resolved_tag} name={name}"
        )
    expected = digest.split(":", 1)[1].lower()

    dest = pathlib.Path(dest_s)
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "F2Media-builder"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(asset["browser_download_url"], headers=headers)
    with urllib.request.urlopen(req, timeout=300) as response, dest.open("wb") as handle:
        copy_stream(response, handle)

    actual = sha256(dest)
    if actual != expected:
        dest.unlink(missing_ok=True)
        raise SystemExit(
            f"SHA256 mismatch: repo={repo} tag={resolved_tag} name={name} "
            f"expected={expected} actual={actual}"
        )
    print(f"verified: repo={repo} tag={resolved_tag} name={name} sha256={actual}")


if __name__ == "__main__":
    main()
