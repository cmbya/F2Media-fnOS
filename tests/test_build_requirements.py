from pathlib import Path


def test_removed_legacy_parsers_are_not_built():
    all_text = "\n".join([
        Path('requirements-build.txt').read_text(encoding='utf-8'),
        Path('pyproject.toml').read_text(encoding='utf-8'),
        Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8'),
        Path('fnos/start-f2media').read_text(encoding='utf-8'),
        Path('scripts/build_fpk.sh').read_text(encoding='utf-8'),
    ]).lower()
    for token in ('parse-video-py', 'ks-downloader', 'xhs-downloader', 'f2==0.0.1.7', 'engines/f2'):
        assert token not in all_text


def test_new_parser_dependencies_are_present():
    req = Path('requirements-build.txt').read_text(encoding='utf-8')
    workflow = Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8')
    assert 'gallery-dl==1.32.9' in req
    assert 'gmssl>=3.2,<4' in req
    assert 'requests>=2.32,<3' in req
    assert 'DLWangSan/douyin_parse.git' in workflow
    assert '--branch v2.0.3' in workflow
    assert 'tamnd/x-cli.git' in workflow
    assert 'tamnd/facebook-cli.git' in workflow
    assert 'CGO_ENABLED=0 GOOS=linux GOARCH=amd64' in workflow
