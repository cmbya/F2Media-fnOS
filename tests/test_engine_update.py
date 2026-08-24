from f2media.core.engine_update import EngineUpdater, _asset_name, _download_url, _pick_asset


def test_pick_ytdlp_linux_asset():
    assets = [{'name': 'yt-dlp.exe'}, {'name': 'yt-dlp_linux', 'browser_download_url': 'https://example/a'}]
    assert _pick_asset('yt-dlp', assets)['name'] == 'yt-dlp_linux'


def test_pick_gallery_linux_asset_avoids_windows_and_arm():
    assets = [
        {'name': 'gallery-dl.exe'},
        {'name': 'gallery-dl_linux_arm64'},
        {'name': 'gallery-dl.bin', 'browser_download_url': 'https://example/g'},
    ]
    assert _pick_asset('gallery-dl', assets)['name'] == 'gallery-dl.bin'


def test_release_tag_prevents_false_update_after_install():
    assert EngineUpdater._is_update_available('gallery-dl', '1.32.9', 'v1.32.9', '') is False
    assert EngineUpdater._is_update_available('gallery-dl', '1.32.9', 'v1.33.0', '') is True
    assert EngineUpdater._is_update_available('gallery-dl', '1.32.9', 'v1.33.0', 'v1.33.0') is False


def test_x_cli_asset_name_matches_upstream_goreleaser():
    assert _asset_name('x-cli', 'v0.5.0') == 'x_0.5.0_linux_amd64.tar.gz'
    assert _download_url('x-cli', 'v0.5.0', 'x_0.5.0_linux_amd64.tar.gz') == (
        'https://github.com/tamnd/x-cli/releases/download/v0.5.0/x_0.5.0_linux_amd64.tar.gz'
    )


def test_gallery_dl_uses_official_codeberg_stable_binary():
    assert _asset_name('gallery-dl', 'v1.32.9') == 'gallery-dl.bin'
    assert _download_url('gallery-dl', 'v1.32.9', 'gallery-dl.bin') == (
        'https://codeberg.org/mikf/gallery-dl/releases/download/v1.32.9/gallery-dl.bin'
    )


def test_engine_updater_does_not_depend_on_github_api_or_expanded_assets():
    from pathlib import Path
    text = Path('f2media/core/engine_update.py').read_text(encoding='utf-8')
    assert 'api.github.com' not in text
    assert 'releases/expanded_assets/' not in text
    assert 'pypi.org/pypi/gallery-dl/json' in text
    assert 'codeberg.org/mikf/gallery-dl/releases/download/' in text
