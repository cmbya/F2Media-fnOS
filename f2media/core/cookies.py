from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet

from .db import Database


class CookieStore:
    def __init__(self, db: Database, key_path: Path):
        self.db = db
        self.key_path = key_path
        self._fernet = Fernet(self._load_key())

    def _load_key(self) -> bytes:
        if self.key_path.exists():
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
            return self.key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_bytes(key + b"\n")
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    def save(
        self,
        platform: str,
        cookie: str,
        extra: str | None = None,
        allowed_parsers: list[str] | None = None,
    ) -> None:
        cookie = cookie.strip().replace("\r\n", "\n").replace("\r", "\n")
        if not cookie:
            raise ValueError("Cookie 不能为空")
        c = self._fernet.encrypt(cookie.encode())
        e = self._fernet.encrypt(extra.strip().encode()) if extra and extra.strip() else None
        self.db.put_cookie(platform, c, e, allowed_parsers=allowed_parsers)

    def get(self, platform: str) -> tuple[str | None, str | None]:
        row = self.db.get_cookie(platform)
        if not row:
            return None, None
        cookie = self._fernet.decrypt(row["cookie_cipher"]).decode()
        extra = self._fernet.decrypt(row["extra_cipher"]).decode() if row["extra_cipher"] else None
        return cookie, extra

    def get_for_parser(
        self, platform: str, parser_key: str, parser_enabled: bool = False
    ) -> tuple[str | None, str | None]:
        """仅当平台解析路由中的 Cookie 开关打开时返回 Cookie。"""
        if not parser_enabled:
            return None, None
        return self.get(platform)

    def set_permissions(self, platform: str, allowed_parsers: list[str]) -> None:
        """兼容旧接口；权限实际以平台解析路由的 cookie_enabled 为准。"""
        self.db.set_cookie_permissions(platform, [])
