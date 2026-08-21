def test_all_nine_platforms_show_all_builtin_parsers(tmp_path):
    store = ParserRouteStore(_db(tmp_path))
    common = {"gallery-dl", "yt-dlp", "x-cli", "facebook-cli", "douyin_parse", "short_videos-local"}
    for platform in PLATFORMS:
        keys = {x["key"] for x in store.get(platform)["items"] if x["kind"] == "builtin"}
        assert common.issubset(keys)

    facebook_keys = {x["key"] for x in store.get("facebook")["items"] if x["kind"] == "builtin"}
    assert "facebook-resolver" in facebook_keys
