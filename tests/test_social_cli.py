from f2media.parsers.facebook_resolver import is_facebook_url
from f2media.parsers.social_cli import normalize_facebook_cli, normalize_x_cli, parse_cli_json


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


def test_facebook_cli_normalizer_ignores_video_thumbnail():
    payload = {
        "message": "post",
        "attachments": [
            {
                "type": "video",
                "url": "https://video.xx.fbcdn.net/v/t42/video.mp4",
                "thumbnail": {"url": "https://scontent.xx.fbcdn.net/thumb.jpg"},
            }
        ],
    }
    result = normalize_facebook_cli(payload, "https://www.facebook.com/posts/1")
    assert [x["url"] for x in result["media"]] == ["https://video.xx.fbcdn.net/v/t42/video.mp4"]
    assert result["counts"]["images"] == 0
    assert result["counts"]["videos"] == 1


def test_facebook_resolver_scope_detection():
    assert is_facebook_url("https://www.facebook.com/share/p/abc/")
    assert not is_facebook_url("https://v.douyin.com/abc/")
    assert not is_facebook_url("https://x.com/user/status/1")
