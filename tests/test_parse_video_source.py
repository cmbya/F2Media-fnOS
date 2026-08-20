from pathlib import Path


def test_parse_video_py_is_not_a_pypi_requirement():
    requirements = Path('requirements-build.txt').read_text(encoding='utf-8')
    pyproject = Path('pyproject.toml').read_text(encoding='utf-8')
    assert 'parse-video-py==0.0.3' not in requirements
    assert 'parse-video-py==0.0.3' not in pyproject


def test_parse_video_py_is_fetched_from_pinned_github_tag():
    workflow = Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8')
    assert 'git clone --depth 1 --branch v0.0.3' in workflow
    assert 'wujunwei928/parse-video-py.git' in workflow
    assert '2d94221*' in workflow
    assert './build/vendor/parse-video-py' in workflow
    assert 'version("parse-video-py") == "0.0.3"' in workflow
