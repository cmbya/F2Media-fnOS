from f2media.core.engine_update import _pick_asset


def test_pick_ytdlp_linux_asset():
    assets = [{'name': 'yt-dlp.exe'}, {'name': 'yt-dlp_linux', 'browser_download_url': 'https://example/a'}]
    assert _pick_asset('yt-dlp', assets)['name'] == 'yt-dlp_linux'


def test_pick_gallery_linux_asset_avoids_windows_and_arm():
    assets = [
        {'name': 'gallery-dl.exe'},
        {'name': 'gallery-dl_linux_arm64'},
        {'name': 'gallery-dl_linux', 'browser_download_url': 'https://example/g'},
    ]
    assert _pick_asset('gallery-dl', assets)['name'] == 'gallery-dl_linux'


def test_release_tag_prevents_false_update_after_install():
    from f2media.core.engine_update import EngineUpdater
    assert EngineUpdater._is_update_available('gallery-dl', '1.32.9', '2026.08.20', '2026.08.20') is False
    assert EngineUpdater._is_update_available('gallery-dl', '1.32.9', '2026.08.21', '2026.08.20') is True
