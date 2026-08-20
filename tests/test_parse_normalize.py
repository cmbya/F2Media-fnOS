from f2media.parse_service import normalize_parse_video, normalize_ytdlp


def test_normalize_live_photo_pair():
    data = {
        "title": "demo",
        "author": {"uid": "1", "name": "tester", "avatar": "https://a/avatar.jpg"},
        "images": [
            {"url": "https://cdn/a.jpg", "video_url": "https://cdn/a.mp4"},
            {"url": "https://cdn/b.jpg"},
        ],
    }
    out = normalize_parse_video(data, "douyin", "https://v.douyin.com/x")
    assert out["ok"] is True
    assert out["media_type"] == "live_photo"
    assert out["counts"] == {"videos": 0, "images": 2, "live_photos": 1}
    assert out["live_photos"][0]["video_url"].endswith("a.mp4")


def test_normalize_ytdlp_video_metadata():
    out = normalize_ytdlp(
        {"id": "abc", "title": "Title", "uploader": "User", "url": "https://cdn/video.mp4", "thumbnail": "https://cdn/c.jpg"},
        "youtube",
        "https://youtube.com/watch?v=abc",
    )
    assert out["ok"] is True
    assert out["parser"] == "yt-dlp"
    assert out["counts"]["videos"] == 1


def test_parse_video_py_image_live_photos_aligned():
    data = {
        "title": "live",
        "images": [
            "https://img.example/1.jpg",
            "https://img.example/2.jpg",
            "https://img.example/3.jpg",
        ],
        "image_live_photos": [
            "https://video.example/1.mp4",
            None,
            "https://video.example/3.mp4",
        ],
    }
    out = normalize_parse_video(data, "xiaohongshu", "https://xhslink.cn/test")
    assert out["ok"] is True
    assert out["media_type"] == "live_photo"
    assert out["counts"] == {"videos": 0, "images": 3, "live_photos": 2}
    assert out["live_photos"][0]["image_url"].endswith("1.jpg")
    assert out["live_photos"][0]["video_url"].endswith("1.mp4")
    assert out["live_photos"][1]["image_url"].endswith("3.jpg")
    assert out["live_photos"][1]["video_url"].endswith("3.mp4")


def test_parse_video_py_image_object_live_photo_url():
    data = {
        "images": [
            {"url": "https://img.example/a.jpg", "live_photo_url": "https://video.example/a.mp4"},
            {"url": "https://img.example/b.jpg"},
        ]
    }
    out = normalize_parse_video(data, "douyin", "https://v.douyin.com/test")
    assert out["counts"]["images"] == 2
    assert out["counts"]["live_photos"] == 1
    assert any(m["type"] == "live_video" for m in out["media"])
