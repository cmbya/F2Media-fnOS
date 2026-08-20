from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

from .db import Database


class AuthStore:
    """Web Basic-Auth credentials plus an independent MCP/Shortcut API key."""

    USER_KEY = "auth_web_username"
    PASSWORD_KEY = "auth_web_password"
    API_KEY = "auth_api_key_cipher"
    PBKDF2_ROUNDS = 260_000

    def __init__(self, db: Database, key_path: Path):
        self.db = db
        self.key_path = key_path
        self._fernet = Fernet(self._load_key())
        self._ensure_api_key()

    def _load_key(self) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_bytes(key + b"\n")
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    @classmethod
    def _hash_password(cls, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, cls.PBKDF2_ROUNDS)
        return "pbkdf2_sha256${}${}${}".format(
            cls.PBKDF2_ROUNDS,
            base64.urlsafe_b64encode(salt).decode().rstrip("="),
            base64.urlsafe_b64encode(digest).decode().rstrip("="),
        )

    @staticmethod
    def _b64decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    @classmethod
    def _verify_password(cls, password: str, stored: str) -> bool:
        try:
            algo, rounds, salt, expected = stored.split("$", 3)
            if algo != "pbkdf2_sha256":
                return False
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), cls._b64decode(salt), int(rounds)
            )
            return hmac.compare_digest(digest, cls._b64decode(expected))
        except Exception:
            return False

    def web_configured(self) -> bool:
        return bool(self.db.get_setting(self.USER_KEY) and self.db.get_setting(self.PASSWORD_KEY))

    def setup_web(self, username: str, password: str, *, force: bool = False) -> None:
        username = username.strip()
        if self.web_configured() and not force:
            raise ValueError("WebUI 账户已经初始化")
        if len(username) < 3:
            raise ValueError("用户名至少 3 个字符")
        if len(password) < 8:
            raise ValueError("密码至少 8 个字符")
        self.db.put_setting(self.USER_KEY, username)
        self.db.put_setting(self.PASSWORD_KEY, self._hash_password(password))

    def verify_web(self, username: str, password: str) -> bool:
        stored_user = self.db.get_setting(self.USER_KEY) or ""
        stored_password = self.db.get_setting(self.PASSWORD_KEY) or ""
        return hmac.compare_digest(username, stored_user) and self._verify_password(password, stored_password)

    def username(self) -> str | None:
        return self.db.get_setting(self.USER_KEY)

    def _ensure_api_key(self) -> None:
        if self.db.get_setting(self.API_KEY):
            return
        seeded = os.getenv("F2MEDIA_API_KEY", "").strip()
        self._store_api_key(seeded or self._new_api_key())

    @staticmethod
    def _new_api_key() -> str:
        return "f2m_" + secrets.token_urlsafe(32)

    def _store_api_key(self, value: str) -> None:
        token = self._fernet.encrypt(value.encode()).decode()
        self.db.put_setting(self.API_KEY, token)

    def api_key(self) -> str:
        token = self.db.get_setting(self.API_KEY)
        if not token:
            self._ensure_api_key()
            token = self.db.get_setting(self.API_KEY)
        assert token is not None
        return self._fernet.decrypt(token.encode()).decode()

    def regenerate_api_key(self) -> str:
        value = self._new_api_key()
        self._store_api_key(value)
        return value

    def verify_api_key(self, value: str | None) -> bool:
        if not value:
            return False
        return hmac.compare_digest(value, self.api_key())
