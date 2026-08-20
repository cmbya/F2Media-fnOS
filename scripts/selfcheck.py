#!/usr/bin/env python3
from __future__ import annotations

import compileall
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from f2media.adapters.registry import AdapterRegistry
from f2media.core.config import load_settings
from f2media.core.doctor import diagnostics
from f2media.core.platforms import platform_for_url


def main() -> int:
    ok = compileall.compile_dir(ROOT / "f2media", quiet=1)
    settings = load_settings()
    checks = {
        "python_compile": ok,
        "url_detection": all([
            platform_for_url("https://v.douyin.com/a") == "douyin",
            platform_for_url("https://vm.tiktok.com/a") == "tiktok",
            platform_for_url("https://x.com/a/status/1") == "twitter",
            platform_for_url("https://www.instagram.com/p/a") == "instagram",
            platform_for_url("https://www.facebook.com/watch/?v=1") == "facebook",
            platform_for_url("https://youtu.be/a") == "youtube",
            platform_for_url("https://b23.tv/a") == "bilibili",
            platform_for_url("https://v.kuaishou.com/a") == "kuaishou",
            platform_for_url("https://xhslink.com/a") == "xiaohongshu",
            platform_for_url("https://xhslink.cn/o/a") == "xiaohongshu",
        ]),
        "runtime": diagnostics(settings.download_dir, settings.data_dir),
        "adapters": AdapterRegistry(ROOT / "vendor").doctor(),
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if checks["python_compile"] and checks["url_detection"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
