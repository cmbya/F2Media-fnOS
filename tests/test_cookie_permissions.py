from pathlib import Path

from f2media.core.cookies import CookieStore
from f2media.core.db import Database


def test_cookie_reading_is_denied_until_route_switch_is_enabled(tmp_path: Path):
    db = Database(tmp_path / "f2media.db")
    store = CookieStore(db, tmp_path / "secret.key")
    store.save("douyin", "sessionid=secret")

    assert store.get_for_parser("douyin", "douyin_parse", False) == (None, None)

    cookie, extra = store.get_for_parser("douyin", "douyin_parse", True)
    assert cookie == "sessionid=secret"
    assert extra is None


def test_legacy_cookie_permission_data_no_longer_controls_reading(tmp_path: Path):
    db = Database(tmp_path / "f2media.db")
    store = CookieStore(db, tmp_path / "secret.key")
    store.save("instagram", "a=1", allowed_parsers=[])

    # 旧版 Cookie 页面写入的授权列表不再参与判断。
    store.set_permissions("instagram", [])
    cookie, _ = store.get_for_parser("instagram", "gallery-dl", True)
    assert cookie == "a=1"

    store.save("instagram", "a=2")
    assert store.get("instagram")[0] == "a=2"
