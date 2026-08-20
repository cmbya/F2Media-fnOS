from f2media.parsers.free_api import apply_mapping, DEFAULT_BUGPK


def test_default_bugpk_order_and_platform_scope():
    assert DEFAULT_BUGPK['url'] == 'https://api.bugpk.com/api/short_videos'
    assert DEFAULT_BUGPK['priority'] == 100
    assert 'douyin' in DEFAULT_BUGPK['platforms']
    assert 'youtube' in DEFAULT_BUGPK['platforms']


def test_free_api_mapping_supports_replacement_provider_shapes():
    payload = {
        'result': {
            'name': '标题',
            'owner': {'name': '作者'},
            'video_url': 'https://cdn.example.com/a.mp4',
            'pics': ['https://cdn.example.com/a.jpg'],
        }
    }
    mapped = apply_mapping(payload, {
        'root': 'result',
        'title': 'name',
        'author': 'owner',
        'url': 'video_url',
        'images': 'pics',
    })
    assert mapped['data']['title'] == '标题'
    assert mapped['data']['url'].endswith('.mp4')
    assert mapped['data']['images'][0].endswith('.jpg')
