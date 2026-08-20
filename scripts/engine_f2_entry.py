#!/usr/bin/env python3
"""Standalone F2 sidecar entrypoint.

F2 is isolated from F2Media's Web/MCP runtime.

IMPORTANT: ``--selfcheck`` must be deterministic and offline.  F2 0.0.1.7 has
import-time side effects in some Douyin/TikTok modules (notably real msToken
generation), so importing the platform CLI trees during a build check can make
a perfectly valid frozen binary fail merely because GitHub Actions cannot get a
usable platform token.

The self-check therefore verifies the external dependency surface explicitly
and verifies that the three platform CLI modules are present via module specs,
without importing those network-active modules.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys


# Import names that cover F2's non-stdlib runtime dependencies which have been
# problematic or are dynamically reached by F2/PyInstaller.  These imports are
# intentionally network-free.
_OFFLINE_IMPORTS = (
    "execjs",             # PyExecJS
    "qrcode",
    "PIL",
    "gmssl",
    "Cryptodome",        # pycryptodomex
    "browser_cookie3",
    "websockets",
    "websockets_proxy",
    "m3u8",
    "jsonpath_ng",
    "importlib_resources",
    "aiofiles",
    "aiosqlite",
    "pydantic",
    "httpx",
    "rich",
    "click",
    "babel",
    "yaml",
    "google.protobuf",
)

_PLATFORM_CLI_MODULES = (
    "f2.apps.douyin.cli",
    "f2.apps.tiktok.cli",
    "f2.apps.twitter.cli",
)


def _offline_selfcheck() -> None:
    import f2

    print(f"import OK: f2 ({getattr(f2, '__file__', '<frozen>')})")
    for module_name in _OFFLINE_IMPORTS:
        module = importlib.import_module(module_name)
        print(f"import OK: {module_name} ({getattr(module, '__file__', '<frozen>')})")

    # find_spec() verifies that PyInstaller included the platform CLI modules,
    # but unlike importing them it does not execute cli.py/utils.py/model.py and
    # therefore does not trigger F2's real-msToken network calls.
    for module_name in _PLATFORM_CLI_MODULES:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            raise RuntimeError(f"frozen F2 module missing: {module_name}")
        print(f"module present: {module_name} origin={spec.origin}")

    print("F2 sidecar offline dependency check OK")


def main() -> None:
    if sys.argv[1:] == ["--version"]:
        import f2
        print(getattr(f2, "__version__", getattr(f2, "version", "0.0.1.7")))
        return

    if sys.argv[1:] == ["--selfcheck"]:
        _offline_selfcheck()
        return

    token = os.getenv("F2MEDIA_X_CSRF_TOKEN", "").strip()
    if token:
        from f2.apps.twitter.utils import ClientConfManager
        ClientConfManager.x_csrf_token = classmethod(lambda cls: token)

    from f2.cli.cli_commands import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
