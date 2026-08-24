from pathlib import Path

from f2media.core.db import Database
from f2media.core.parser_routes import PLATFORMS, ParserRouteStore


def _db(tmp_path: Path) -> Database:
    return Database(tmp_path / "f2media.db")


def _seed(db: Database, name: str, platforms: list[str], priority: int = 50) -> int:
    row = db.put_parser_api({
        "name": name, "platforms": platforms, "url": f"https://api.example.test/{name}",
        "method": "GET", "url_param": "url", "enabled": True, "priority": priority,
    })
    return int(row["id"])


def test_builtin_parsers_match_supported_set(tmp_path):
    store = ParserRouteStore(_db(tmp_path))
    expected = {
        "douyin": {"douyin_parse", "gallery-dl", "yt-dlp"},
        "kuaishou": {"gallery-dl", "yt-dlp"},
        "bilibili": {"gallery-dl", "yt-dlp"},
        "xiaohongshu": {"gallery-dl", "yt-dlp"},
        "instagram": {"gallery-dl", "yt-dlp"},
        "twitter": {"x-cli", "gallery-dl", "yt-dlp"},
        "youtube": {"yt-dlp", "gallery-dl"},
        "facebook": {"gallery-dl", "yt-dlp"},
        "tiktok": {"gallery-dl", "yt-dlp"},
    }
    assert set(PLATFORMS) == set(expected)
    for platform in PLATFORMS:
        keys = {x["key"] for x in store.get(platform)["items"] if x["kind"] == "builtin"}
        assert keys == expected[platform]


def test_free_api_is_independent_route_item_on_every_platform(tmp_path):
    db = _db(tmp_path)
    api_id = _seed(db, "x-api", ["twitter"])
    store = ParserRouteStore(db)
    key = f"free-api:{api_id}"
    twitter = {x["key"]: x for x in store.get("twitter")["items"]}
    douyin = {x["key"]: x for x in store.get("douyin")["items"]}
    assert twitter[key]["recommended"] is True
    assert twitter[key]["enabled"] is True
    assert douyin[key]["recommended"] is False
    assert douyin[key]["enabled"] is False


def test_supported_free_api_precedes_douyin_local_fallbacks(tmp_path):
    db = _db(tmp_path)
    api_id = _seed(db, "dy-api", ["douyin"], 10)
    store = ParserRouteStore(db)
    enabled = store.enabled_keys("douyin")
    assert enabled[0] == f"free-api:{api_id}"
    assert "douyin_parse" in enabled
    assert "short_videos-local" not in {x["key"] for x in store.get("douyin")["items"]}


def test_user_order_and_enable_state_are_persisted(tmp_path):
    db = _db(tmp_path)
    api_id = _seed(db, "x-api", ["twitter"])
    store = ParserRouteStore(db)
    api_key = f"free-api:{api_id}"
    current = store.get("twitter")["items"]
    wanted = [
        {"key": api_key, "enabled": True},
        {"key": "yt-dlp", "enabled": True},
        {"key": "x-cli", "enabled": False},
    ] + [{"key": x["key"], "enabled": False} for x in current if x["key"] not in {api_key, "yt-dlp", "x-cli"}]
    saved = store.save("twitter", wanted)
    assert [x["key"] for x in saved["items"][:3]] == [api_key, "yt-dlp", "x-cli"]
    assert store.enabled_keys("twitter")[:2] == [api_key, "yt-dlp"]


def test_new_api_appears_and_deleted_api_disappears(tmp_path):
    db = _db(tmp_path)
    store = ParserRouteStore(db)
    api_id = _seed(db, "fb-api", ["facebook"])
    key = f"free-api:{api_id}"
    row = {x["key"]: x for x in store.get("facebook")["items"]}[key]
    assert row["enabled"] is True
    db.delete_parser_api(api_id)
    assert key not in {x["key"] for x in store.get("facebook")["items"]}


def test_x_cli_default_and_facebook_uses_supported_engines(tmp_path):
    store = ParserRouteStore(_db(tmp_path))
    assert store.enabled_keys("twitter")[0] == "x-cli"
    assert store.enabled_keys("facebook") == ["gallery-dl", "yt-dlp"]


def test_cookie_engine_switch_is_deny_by_default_and_persisted(tmp_path):
    store = ParserRouteStore(_db(tmp_path))
    current = store.get("douyin")["items"]
    assert all(not x["cookie_enabled"] for x in current)

    wanted = [
        {"key": x["key"], "enabled": x["enabled"], "cookie_enabled": x["key"] == "yt-dlp"}
        for x in current
    ]
    saved = store.save("douyin", wanted)
    rows = {x["key"]: x for x in saved["items"]}
    assert rows["yt-dlp"]["cookie_enabled"] is True
    assert rows["gallery-dl"]["cookie_enabled"] is False
    assert rows["yt-dlp"]["cookie_supported"] is True


def test_non_cookie_parser_cannot_enable_cookie_switch(tmp_path):
    store = ParserRouteStore(_db(tmp_path))
    current = store.get("twitter")["items"]
    saved = store.save("twitter", [
        {"key": x["key"], "enabled": x["enabled"], "cookie_enabled": True}
        for x in current
    ])
    rows = {x["key"]: x for x in saved["items"]}
    assert rows["x-cli"]["cookie_supported"] is True
    assert rows["x-cli"]["cookie_enabled"] is True
