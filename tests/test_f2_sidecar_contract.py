from pathlib import Path


def test_f2_is_isolated_from_main_requirements():
    req = Path('requirements-build.txt').read_text(encoding='utf-8')
    assert 'f2==0.0.1.7' not in req


def test_f2_selfcheck_is_offline_and_does_not_import_platform_cli_trees():
    text = Path('scripts/engine_f2_entry.py').read_text(encoding='utf-8')
    assert 'importlib.util.find_spec' in text
    assert 'pkgutil.walk_packages' not in text
    assert 'import f2.apps.tiktok.cli' not in text
    assert 'import f2.apps.douyin.cli' not in text
    assert 'import f2.apps.twitter.cli' not in text
    assert 'importlib.import_module(module_name)' in text
    assert '"execjs"' in text
    for package in ('f2.apps.douyin.cli', 'f2.apps.tiktok.cli', 'f2.apps.twitter.cli'):
        assert package in text


def test_workflow_builds_f2_in_isolated_venv_and_uses_offline_probe():
    text = Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8')
    assert 'Build isolated F2 0.0.1.7 sidecar' in text
    assert 'build/venv-f2/bin/python -m pip install "pyinstaller==6.22.2" "f2==0.0.1.7" "Pillow>=10,<13"' in text
    assert '--collect-all execjs --copy-metadata PyExecJS' in text
    assert 'assert version("PyExecJS") == "1.5.1"' in text
    assert 'build/engines/f2/f2 --selfcheck' in text
    assert 'F2 isolated dependency probe (offline-safe)' in text
    assert 'find_spec(name)' in text
    assert 'import f2.apps.tiktok.cli' not in text


def test_find_spec_probe_does_not_execute_platform_cli(tmp_path, monkeypatch):
    root = tmp_path / 'f2'
    (root / 'apps' / 'douyin').mkdir(parents=True)
    (root / 'apps' / 'tiktok').mkdir(parents=True)
    (root / 'apps' / 'twitter').mkdir(parents=True)
    for path in [root, root / 'apps', root / 'apps' / 'douyin', root / 'apps' / 'tiktok', root / 'apps' / 'twitter']:
        (path / '__init__.py').write_text('', encoding='utf-8')
    for platform in ('douyin', 'tiktok', 'twitter'):
        (root / 'apps' / platform / 'cli.py').write_text(
            'raise RuntimeError("network-active CLI module was executed")\n',
            encoding='utf-8',
        )

    monkeypatch.syspath_prepend(str(tmp_path))
    # Remove any already imported real/fake f2 modules so this test controls the tree.
    import sys
    for name in list(sys.modules):
        if name == 'f2' or name.startswith('f2.'):
            sys.modules.pop(name, None)

    import importlib.util
    for name in ('f2.apps.douyin.cli', 'f2.apps.tiktok.cli', 'f2.apps.twitter.cli'):
        spec = importlib.util.find_spec(name)
        assert spec is not None
        assert name not in sys.modules
