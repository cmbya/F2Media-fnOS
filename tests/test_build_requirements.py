from pathlib import Path


def test_f2_is_not_installed_into_main_runtime_build_environment():
    lines = [
        line.strip()
        for line in Path('requirements-build.txt').read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    ]
    assert 'f2==0.0.1.7' not in lines
    assert not any(line.lower().startswith('qrcode') for line in lines)
    assert not any(line.lower().startswith('pyexecjs') for line in lines)


def test_f2_is_pinned_inside_its_isolated_sidecar_builder():
    workflow = Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8')
    assert 'Build isolated F2 0.0.1.7 sidecar' in workflow
    assert '"f2==0.0.1.7"' in workflow
    assert 'version("PyExecJS") == "1.5.1"' in workflow
    assert 'version("qrcode") == "8.0"' in workflow
