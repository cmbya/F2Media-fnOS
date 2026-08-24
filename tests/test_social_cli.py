from f2media.parsers.social_cli import normalize_x_cli, parse_cli_json


def test_parse_cli_json_accepts_json_and_jsonl():
    assert parse_cli_json('{"a":1}') == {"a": 1}
    assert parse_cli_json('{"a":1}\n{"b":2}') == [{"a": 1}, {"b": 2}]


def test_x_cli_normalizer_keeps_real_photo_and_best_video_variant():
    payload = {
        "text": "hello",
        "media": [
            {"type": "photo", "url": "https://pbs.twimg.com/media/a.jpg"},
            {
                "type": "video",
                "preview_image": "https://pbs.twimg.com/ext_tw_video_thumb/a.jpg",
                "variants": [
                    {"content_type": "video/mp4", "bitrate": 256000, "url": "https://video.twimg.com/a-low.mp4"},
                    {"content_type": "video/mp4", "bitrate": 2176000, "url": "https://video.twimg.com/a-high.mp4"},
                ],
            },
        ],
    }
    result = normalize_x_cli(payload, "https://x.com/u/status/1")
    urls = [x["url"] for x in result["media"]]
    assert "https://pbs.twimg.com/media/a.jpg" in urls
    assert "https://video.twimg.com/a-high.mp4" in urls
    assert "https://video.twimg.com/a-low.mp4" not in urls
    assert "https://pbs.twimg.com/ext_tw_video_thumb/a.jpg" not in urls
    assert result["media_type"] == "mixed"
