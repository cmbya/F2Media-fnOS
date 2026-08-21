from f2media.parsers.social_cli import normalize_facebook_cli


def test_facebook_cli_reel_streams_are_normalized():
    payload = {
        "video_id": "2300217217408960",
        "owner_name": "Example",
        "title": "Example reel",
        "thumb_url": "https://scontent.xx.fbcdn.net/thumb.jpg",
        "permalink": "https://www.facebook.com/reel/2300217217408960",
        "is_reel": True,
        "streams": [
            {"quality": "SD", "mime": "video/mp4", "width": 540, "height": 960, "url": "https://video.xx.fbcdn.net/sd.mp4"},
            {"quality": "HD", "mime": "video/mp4", "width": 1080, "height": 1920, "url": "https://video.xx.fbcdn.net/hd.mp4"},
        ],
    }
    result = normalize_facebook_cli(payload, payload["permalink"])
    assert result["ok"] is True
    assert result["parser"] == "facebook-cli"
    assert result["media_type"] == "video"
    assert result["counts"] == {"videos": 1, "images": 0, "live_photos": 0}
    assert result["media"] == [{"type": "video", "url": "https://video.xx.fbcdn.net/hd.mp4"}]
    assert result["cover_url"] is None


def test_facebook_cli_separate_audio_is_preserved():
    payload = {
        "video_id": "1",
        "streams": [
            {"quality": "1080p", "mime": "video/mp4", "height": 1080, "url": "https://video.xx.fbcdn.net/video.mp4"},
            {"quality": "audio", "mime": "audio/mp4", "is_audio": True, "url": "https://video.xx.fbcdn.net/audio.m4a"},
        ],
    }
    result = normalize_facebook_cli(payload, "https://www.facebook.com/reel/1")
    assert result["media"][0]["url"].endswith("video.mp4")
    assert result["media"][0]["audio_url"].endswith("audio.m4a")
