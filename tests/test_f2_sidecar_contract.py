from pathlib import Path


def test_f2_is_isolated_from_main_requirements():
    req = Path('requirements-build.txt').read_text(encoding='utf-8')
    assert 'f2==0.0.1.7' not in req


def test_f2_selfcheck_explicitly_imports_execjs_and_walks_platform_trees():
    text = Path('scripts/engine_f2_entry.py').read_text(encoding='utf-8')
    assert 'import execjs' in text
    assert 'pkgutil.walk_packages' in text
    for package in ('f2.apps.douyin', 'f2.apps.tiktok', 'f2.apps.twitter'):
        assert package in text


def test_workflow_builds_f2_in_isolated_venv_and_collects_execjs():
    text = Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8')
    assert 'Build isolated F2 0.0.1.7 sidecar' in text
    assert 'build/venv-f2/bin/python -m pip install "pyinstaller==6.22.2" "f2==0.0.1.7" "Pillow>=10,<13"' in text
    assert '--collect-all execjs --copy-metadata PyExecJS' in text
    assert 'assert version("PyExecJS") == "1.5.1"' in text
    assert 'build/engines/f2/f2 --selfcheck' in text
