from pathlib import Path

from f2media.parsers.common import looks_downloadable, normalize_external_result, safe_title


def test_page_urls_are_not_media_success():
    assert not looks_downloadable('https://www.tiktok.com/@abc/video/123', 'video')
    assert not looks_downloadable('https://www.instagram.com/p/ABC/', 'image')
    assert looks_downloadable('https://v16-webapp-prime.us.tiktok.com/video/tos/x?mime_type=video_mp4', 'video')


def test_live_photo_keeps_static_and_motion_pair():
    result = normalize_external_result({
        'type': 'live',
        'title': '大海真蓝',
        'live_photo': [{'image': 'https://cdn.example.com/a.jpg', 'video': 'https://cdn.example.com/a.mp4'}],
    }, 'douyin', 'https://v.douyin.com/x', 'test')
    assert result['ok'] is True
    assert result['media_type'] == 'live_photo'
    assert result['counts']['live_photos'] == 1
    assert {x['type'] for x in result['media']} == {'image', 'live_video'}


def test_filename_sanitizer_keeps_readable_unicode():
    assert safe_title('大海真蓝 / 你好?') == '大海真蓝 你好'


def test_pipeline_order_is_locked():
    src = Path('f2media/parse_service.py').read_text(encoding='utf-8')
    assert src.index('("douyin_parse"') < src.index('("short_videos-local"')
    assert src.index('("short_videos-local"') < src.index('("free-api"')
    assert src.index('("free-api"') < src.index('("gallery-dl"')
    assert src.index('("gallery-dl"') < src.index('("yt-dlp"')
