from pathlib import Path

from f2media.core.db import Database
from f2media.core.parser_routes import PLATFORMS, ParserRouteStore


def _db(tmp_path: Path) -> Database:
    return Database(tmp_path / "f2media.db")


def _seed(db: Database, name: str, platforms: list[str], priority: int = 50) -> int:
    row = db.put_parser_api({
        "name": name,
        "platforms": platforms,
        "url": f"https://api.example.test/{name}",
        "method": "GET",
        "url_param": "url",
        "enabled": True,
        "priority": priority,
    })
    return int(row["id"])


def test_all_nine_platforms_show_all_builtin_parsers(tmp_path):
    store = ParserRouteStore(_db(tmp_path))
    # Resolver is intentionally NOT a parser: it is an always-on Facebook-only
    # preprocessor, so all nine cards continue to expose the same parser set.
    expected = {"douyin_parse", "short_videos-local", "x-cli", "facebook-cli", "gallery-dl", "yt-dlp"}
    assert set(PLATFORMS) == {"douyin", "kuaishou", "bilibili", "xiaohongshu", "instagram", "twitter", "youtube", "facebook", "tiktok"}
    for platform in PLATFORMS:
        keys = {x["key"] for x in store.get(platform)["items"] if x["kind"] == "builtin"}
        assert expected.issubset(keys)
        if platform == "facebook":
            assert "facebook-extractor" in keys


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
    store.save("facebook", [{"key": "gallery-dl", "enabled": True}])
    api_id = _seed(db, "fb-api", ["facebook"])
    key = f"free-api:{api_id}"
    row = {x["key"]: x for x in store.get("facebook")["items"]}[key]
    assert row["enabled"] is True
    db.delete_parser_api(api_id)
    assert key not in {x["key"] for x in store.get("facebook")["items"]}


def test_facebook_defaults_gallery_first_and_x_cli_first(tmp_path):
    db = _db(tmp_path)
    _seed(db, "x-api", ["twitter"], 10)
    _seed(db, "fb-api", ["facebook"], 10)
    store = ParserRouteStore(db)
    assert store.enabled_keys("twitter")[0] == "x-cli"
    assert store.enabled_keys("facebook")[0] == "gallery-dl"
