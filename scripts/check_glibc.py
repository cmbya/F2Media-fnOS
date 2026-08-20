#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

GLIBC_RE = re.compile(r"GLIBC_(\d+)\.(\d+)")


def parse_version(text: str) -> tuple[int, int] | None:
    versions = [(int(a), int(b)) for a, b in GLIBC_RE.findall(text)]
    return max(versions) if versions else None


def elf_requirement(path: Path) -> tuple[int, int] | None:
    hdr = subprocess.run(
        ["readelf", "-h", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if hdr.returncode != 0:
        return None
    p = subprocess.run(
        ["readelf", "--version-info", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return parse_version(p.stdout or "")


def walk_targets(targets: list[Path]):
    seen: set[Path] = set()
    for target in targets:
        if target.is_dir():
            items = (p for p in target.rglob("*") if p.is_file())
        else:
            items = (target,)
        for p in items:
            try:
                rp = p.resolve()
            except OSError:
                rp = p
            if rp in seen:
                continue
            seen.add(rp)
            yield p


def main() -> int:
    ap = argparse.ArgumentParser(description="Reject ELF files requiring a glibc newer than fnOS baseline")
    ap.add_argument("targets", nargs="+", type=Path)
    ap.add_argument("--max", default="2.36", dest="maximum")
    args = ap.parse_args()
    try:
        max_allowed = tuple(map(int, args.maximum.split(".", 1)))
    except Exception as exc:
        raise SystemExit(f"invalid --max version: {args.maximum}") from exc

    checked = 0
    offenders: list[tuple[Path, tuple[int, int]]] = []
    maximum_seen: tuple[int, int] | None = None
    for path in walk_targets(args.targets):
        req = elf_requirement(path)
        if req is None:
            continue
        checked += 1
        maximum_seen = req if maximum_seen is None else max(maximum_seen, req)
        print(f"ELF {path}: max GLIBC_{req[0]}.{req[1]}")
        if req > max_allowed:
            offenders.append((path, req))

    print(f"checked_elf={checked} maximum_seen={maximum_seen} allowed={max_allowed}")
    if offenders:
        print("ERROR: binaries newer than fnOS Debian 12 glibc baseline:")
        for path, req in offenders:
            print(f"  {path}: GLIBC_{req[0]}.{req[1]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
