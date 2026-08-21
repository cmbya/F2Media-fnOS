from __future__ import annotations

"""
Facebook 专用解析入口。

当前版本复用已有 Facebook resolver 的 URL 归一化能力，
并作为独立阶段名称暴露给路由/UI。
后续可在这里继续加入媒体提取逻辑。
"""

from .facebook_resolver import (
    facebook_url_kind,
    is_facebook_url,
    resolve_facebook_url,
)

__all__ = [
    "facebook_url_kind",
    "is_facebook_url",
    "resolve_facebook_url",
]
