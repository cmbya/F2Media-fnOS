from f2media.core.platforms import ParsedInput
from f2media.parse_service import ParseService
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


def test_video_backup_is_not_counted_as_second_content_video():
    result = normalize_external_result({
        'data': {
            'type': 'video',
            'title': '快手测试',
            'url': 'https://cdn.example.com/main.mp4',
            'video_backup': [
                'https://cdn.example.com/backup1.mp4',
                'https://cdn.example.com/backup2.mp4',
            ],
        }
    }, 'kuaishou', 'https://v.kuaishou.com/x', 'test')
    assert result['counts']['videos'] == 1
    assert [x['url'] for x in result['media']] == ['https://cdn.example.com/main.mp4']


def test_video_backup_is_used_only_when_primary_is_missing():
    result = normalize_external_result({
        'data': {
            'type': 'video',
            'video_backup': ['https://cdn.example.com/backup.mp4'],
        }
    }, 'kuaishou', 'https://v.kuaishou.com/x', 'test')
    assert result['counts']['videos'] == 1
    assert result['media'][0]['url'].endswith('/backup.mp4')


def test_short_videos_bilibili_parts_are_all_normalized_with_part_metadata():
    result = normalize_external_result({
        'data': {
            'title': '合集',
            'videos': [
                {'title': '第一集', 'index': 1, 'url': 'https://cdn.example.com/p1.mp4'},
                {'title': '第二集', 'index': 2, 'url': 'https://cdn.example.com/p2.mp4'},
            ],
        }
    }, 'bilibili', 'https://www.bilibili.com/video/BV1xx', 'short_videos')
    assert result['counts']['videos'] == 2
    assert [(x['part_index'], x['part_title']) for x in result['media']] == [(1, '第一集'), (2, '第二集')]


def test_douyin_desktop_modal_url_normalizes_to_work_url():
    item = ParsedInput(
        url='https://www.douyin.com/user/abc?from_tab_name=main&modal_id=7676064894881797617',
        platform='douyin',
    )
    routed = ParseService._normalize_routing_item(item)
    assert routed.url == 'https://www.douyin.com/video/7676064894881797617'
    assert routed.platform == 'douyin'




def test_filename_sanitizer_keeps_readable_unicode():
    assert safe_title('大海真蓝 / 你好?') == '大海真蓝 你好'


def test_pipeline_order_is_user_configurable():
    from f2media.core.parser_routes import DEFAULT_BUILTIN_ORDER
    assert DEFAULT_BUILTIN_ORDER["twitter"][:3] == ["x-cli", "gallery-dl", "yt-dlp"]
    assert DEFAULT_BUILTIN_ORDER["facebook"] == ["gallery-dl", "yt-dlp"]
    assert DEFAULT_BUILTIN_ORDER["douyin"] == ["douyin_parse", "short_videos", "gallery-dl", "yt-dlp"]
    assert DEFAULT_BUILTIN_ORDER["bilibili"] == ["short_videos", "gallery-dl", "yt-dlp"]
