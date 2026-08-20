from f2media.core.db import Database
from f2media.parsers.free_api import (
    BUILTIN_APIS,
    DEFAULT_BUGPK,
    DEFAULT_BUGPK_DOUYIN,
    DEFAULT_BUGPK_DYZY,
    DEFAULT_BUGPK_KSJX,
    DEFAULT_BUGPK_SVPARSE,
    FreeApiStore,
    apply_mapping,
)


def test_builtin_bugpk_endpoints_and_order():
    assert [x['url'] for x in BUILTIN_APIS] == [
        'https://api.bugpk.com/api/douyin',
        'https://api.bugpk.com/api/ksjx',
        'https://api.bugpk.com/api/svparse',
        'https://api.bugpk.com/api/dyzy',
        'https://api.bugpk.com/api/short_videos',
    ]
    assert DEFAULT_BUGPK_DOUYIN['priority'] == 10
    assert DEFAULT_BUGPK_KSJX['priority'] == 10
    assert DEFAULT_BUGPK_SVPARSE['priority'] == 20
    assert DEFAULT_BUGPK_DYZY['priority'] == 30
    assert DEFAULT_BUGPK['priority'] == 100
    assert 'youtube' in DEFAULT_BUGPK['platforms']


def test_existing_v020_database_gets_all_missing_builtin_apis_once(tmp_path):
    db = Database(tmp_path / 'db.sqlite')
    # Simulate v0.2.0: only the aggregate API already existed.
    db.seed_parser_api(DEFAULT_BUGPK)
    assert len(db.parser_apis()) == 1

    FreeApiStore(db)
    rows = db.parser_apis()
    assert len(rows) == 5
    assert {x['url'] for x in rows} == {x['url'] for x in BUILTIN_APIS}

    # Startup again must not create duplicates.
    FreeApiStore(db)
    assert len(db.parser_apis()) == 5


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
