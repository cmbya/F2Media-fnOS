from pathlib import Path


def test_f2_owns_qrcode_version_constraint():
    lines = [
        line.strip()
        for line in Path('requirements-build.txt').read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    ]
    assert 'f2==0.0.1.7' in lines
    assert not any(line.lower().startswith('qrcode') for line in lines), (
        'Do not pin qrcode separately: F2 0.0.1.7 owns its compatible qrcode dependency.'
    )
