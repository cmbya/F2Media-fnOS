#!/usr/bin/env python3
"""Standalone F2 sidecar entrypoint.

F2 is kept separate from F2Media's web runtime.  The --selfcheck path imports all
three platform CLI modules without network requests; this catches missing hidden
imports (such as qrcode/Pillow) during GitHub Actions instead of on the NAS.
"""
from __future__ import annotations

import importlib
import os
import sys


def main() -> None:
    if sys.argv[1:] == ["--version"]:
        import f2
        print(getattr(f2, "__version__", getattr(f2, "version", "0.0.1.7")))
        return

    if sys.argv[1:] == ["--selfcheck"]:
        modules = (
            "f2.apps.douyin.cli",
            "f2.apps.tiktok.cli",
            "f2.apps.twitter.cli",
        )
        for name in modules:
            importlib.import_module(name)
            print(f"import OK: {name}")
        return

    token = os.getenv("F2MEDIA_X_CSRF_TOKEN", "").strip()
    if token:
        from f2.apps.twitter.utils import ClientConfManager
        ClientConfManager.x_csrf_token = classmethod(lambda cls: token)

    from f2.cli.cli_commands import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
