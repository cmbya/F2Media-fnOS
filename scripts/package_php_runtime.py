#!/usr/bin/env python3
"""Package the PHP CLI plus its cURL extension and ELF dependencies."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path


def ldd_paths(path: Path) -> set[Path]:
    text = subprocess.check_output(["ldd", str(path)], text=True, stderr=subprocess.STDOUT)
    found: set[Path] = set()
    for line in text.splitlines():
        match = re.search(r"=>\s+(?P<path>/[^\s]+)", line)
        if not match:
            match = re.match(r"\s*(?P<path>/[^\s]+)\s+\(", line)
        if match:
            candidate = Path(match.group("path"))
            if candidate.is_file():
                found.add(candidate.resolve())
    return found


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} PHP_BIN OUTPUT_DIR", file=sys.stderr)
        return 2
    php = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    extension_dir = subprocess.check_output(
        [str(php), "-n", "-r", "echo ini_get('extension_dir');"], text=True
    ).strip()
    curl = Path(extension_dir) / "curl.so"
    if not php.is_file() or not curl.is_file():
        raise SystemExit(f"PHP CLI or curl extension missing: php={php} curl={curl}")

    if output.exists():
        shutil.rmtree(output)
    (output / "bin").mkdir(parents=True)
    (output / "extensions").mkdir()
    (output / "lib").mkdir()
    shutil.copy2(php, output / "bin" / "php")
    shutil.copy2(curl, output / "extensions" / "curl.so")

    queue = [php, curl]
    libraries: set[Path] = set()
    while queue:
        current = queue.pop()
        for dependency in ldd_paths(current):
            if dependency in libraries:
                continue
            libraries.add(dependency)
            queue.append(dependency)
    for dependency in sorted(libraries):
        shutil.copy2(dependency, output / "lib" / dependency.name)
    print(f"packaged php={php} curl={curl} libraries={len(libraries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
