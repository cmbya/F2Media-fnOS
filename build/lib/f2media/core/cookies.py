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

    def save(self, platform: str, cookie: str, extra: str | None = None) -> None:
        cookie = cookie.strip().replace("\r\n", "\n").replace("\r", "\n")
        if not cookie:
            raise ValueError("Cookie 不能为空")
        c = self._fernet.encrypt(cookie.encode())
        e = self._fernet.encrypt(extra.strip().encode()) if extra and extra.strip() else None
        self.db.put_cookie(platform, c, e)

    def get(self, platform: str) -> tuple[str | None, str | None]:
        row = self.db.get_cookie(platform)
        if not row:
            return None, None
        cookie = self._fernet.decrypt(row["cookie_cipher"]).decode()
        extra = self._fernet.decrypt(row["extra_cipher"]).decode() if row["extra_cipher"] else None
        return cookie, extra
