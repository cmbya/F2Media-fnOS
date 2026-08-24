from pathlib import Path

from f2media.core.auth import AuthStore
from f2media.core.db import Database


def test_auth_setup_and_api_key(tmp_path: Path):
    db = Database(tmp_path / "db.sqlite")
    store = AuthStore(db, tmp_path / "secret.key")
    assert not store.web_configured()
    key = store.api_key()
    assert key.startswith("f2m_")
    assert store.verify_api_key(key)
    assert not store.verify_api_key("wrong")

    store.setup_web("admin", "password123")
    assert store.web_configured()
    assert store.verify_web("admin", "password123")
    assert not store.verify_web("admin", "bad-password")

    new_key = store.regenerate_api_key()
    assert new_key != key
    assert not store.verify_api_key(key)
    assert store.verify_api_key(new_key)
