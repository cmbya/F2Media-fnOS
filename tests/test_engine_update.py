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


def test_pick_x_cli_linux_amd64_archive():
    assets = [
        {'name': 'x_Darwin_arm64.tar.gz'},
        {'name': 'x_Linux_arm64.tar.gz'},
        {'name': 'x_Linux_x86_64.tar.gz', 'browser_download_url': 'https://example/x'},
    ]
    assert _pick_asset('x-cli', assets)['name'] == 'x_Linux_x86_64.tar.gz'


def test_engine_updater_does_not_depend_on_github_api():
    from pathlib import Path
    text = Path("f2media/core/engine_update.py").read_text(encoding="utf-8")
    assert "api.github.com" not in text
    assert "releases/expanded_assets/" not in text
    assert "releases/latest/download" in text
