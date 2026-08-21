import re
import tomllib
from pathlib import Path


def test_release_version_is_synchronized():
    with Path('pyproject.toml').open('rb') as fh:
        pyproject = tomllib.load(fh)
    version = pyproject['project']['version']
    init = Path('f2media/__init__.py').read_text(encoding='utf-8')
    manifest = Path('fnos/manifest').read_text(encoding='utf-8')
    workflow = Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8')
    build_fpk = Path('scripts/build_fpk.sh').read_text(encoding='utf-8')
    build_probe = Path('scripts/build_install_probe.sh').read_text(encoding='utf-8')
    assert f'__version__ = "{version}"' in init
    assert re.search(rf'^version={re.escape(version)}$', manifest, re.MULTILINE)
    assert re.search(rf'^\s*default:\s*"{re.escape(version)}"$', workflow, re.MULTILINE)
    assert f'VERSION="${{1:-{version}}}"' in build_fpk
    assert f'VERSION="${{1:-{version}}}"' in build_probe
