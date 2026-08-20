#!/usr/bin/env python3
"""Standalone F2 sidecar entrypoint.

F2 is isolated from F2Media's Web/MCP runtime.  ``--selfcheck`` deliberately
imports PyExecJS and every module below the Douyin/TikTok/Twitter app packages.
That makes GitHub Actions fail before an FPK is published if PyInstaller drops
an external or dynamically reached dependency.
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import sys


def _import_tree(package_name: str) -> None:
    package = importlib.import_module(package_name)
    print(f"import OK: {package_name}")
    package_path = getattr(package, "__path__", None)
    if package_path is None:
        return
    for info in pkgutil.walk_packages(package_path, package.__name__ + "."):
        importlib.import_module(info.name)
        print(f"import OK: {info.name}")


def main() -> None:
    if sys.argv[1:] == ["--version"]:
        import f2
        print(getattr(f2, "__version__", getattr(f2, "version", "0.0.1.7")))
        return

    if sys.argv[1:] == ["--selfcheck"]:
        # F2's Douyin webcast signature module imports ``execjs``. Import it
        # explicitly so the frozen binary itself proves that PyExecJS survived.
        import execjs
        print(f"import OK: execjs ({execjs.__file__})")
        for root in (
            "f2.apps.douyin",
            "f2.apps.tiktok",
            "f2.apps.twitter",
        ):
            _import_tree(root)
        print("F2 sidecar dependency tree OK")
        return

    token = os.getenv("F2MEDIA_X_CSRF_TOKEN", "").strip()
    if token:
        from f2.apps.twitter.utils import ClientConfManager
        ClientConfManager.x_csrf_token = classmethod(lambda cls: token)

    from f2.cli.cli_commands import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
