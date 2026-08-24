#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"version update failed for {path}: matched {count} times")
    path.write_text(updated, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2 or not VERSION_RE.fullmatch(sys.argv[1]):
        raise SystemExit("usage: set_version.py X.Y.Z")
    version = sys.argv[1]
    replace_once(
        Path("f2media/__init__.py"),
        r'^__version__\s*=\s*"[^"]+"$',
        f'__version__ = "{version}"',
    )
    replace_once(
        Path("pyproject.toml"),
        r'^version\s*=\s*"[^"]+"$',
        f'version = "{version}"',
    )
    replace_once(
        Path("fnos/manifest"),
        r'^version=[^\n]+$',
        f'version={version}',
    )
    replace_once(
        Path(".github/workflows/build-fnos.yml"),
        r'^(\s*default:\s*)"[0-9]+\.[0-9]+\.[0-9]+"$',
        rf'\g<1>"{version}"',
    )
    replace_once(
        Path("scripts/build_fpk.sh"),
        r'^VERSION="\$\{1:-[0-9]+\.[0-9]+\.[0-9]+\}"$',
        f'VERSION="${{1:-{version}}}"',
    )
    replace_once(
        Path("scripts/build_install_probe.sh"),
        r'^VERSION="\$\{1:-[0-9]+\.[0-9]+\.[0-9]+\}"$',
        f'VERSION="${{1:-{version}}}"',
    )
    print(f"F2Media source/build/manifest/workflow version => {version}")


if __name__ == "__main__":
    main()
