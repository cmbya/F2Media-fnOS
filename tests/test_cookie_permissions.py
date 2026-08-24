from pathlib import Path

from f2media.core.cookies import CookieStore
from f2media.core.db import Database


def test_cookie_permissions_are_empty_by_default_and_require_engine_gate(tmp_path: Path):
    db = Database(tmp_path / "f2media.db")
    store = CookieStore(db, tmp_path / "secret.key")
    store.save("douyin", "sessionid=secret")

    assert store.allowed_parsers("douyin") == []
    assert store.get_for_parser("douyin", "yt-dlp", True) == (None, None)

    store.set_permissions("douyin", ["yt-dlp"])
    assert store.get_for_parser("douyin", "gallery-dl", False) == (None, None)
    cookie, extra = store.get_for_parser("douyin", "yt-dlp", True)
    assert cookie == "sessionid=secret"
    assert extra is None


def test_updating_cookie_preserves_existing_permissions(tmp_path: Path):
    db = Database(tmp_path / "f2media.db")
    store = CookieStore(db, tmp_path / "secret.key")
    store.save("instagram", "a=1", allowed_parsers=["gallery-dl"])
    store.save("instagram", "a=2")

    assert store.allowed_parsers("instagram") == ["gallery-dl"]
    assert store.get("instagram")[0] == "a=2"
