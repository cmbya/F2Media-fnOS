import inspect
from pathlib import Path


def test_xhs_guard_checks_init_not_class_signature():
    # XHS 2.7 implements __new__(*args, **kwargs), so inspect.signature(XHS)
    # is intentionally generic. The real public configuration API is __init__.
    class XHSLike:
        def __new__(cls, *args, **kwargs):
            return super().__new__(cls)

        def __init__(
            self,
            work_path="",
            folder_name="Download",
            cookie="",
            image_download=True,
            video_download=True,
            live_download=False,
            **kwargs,
        ):
            pass

    assert str(inspect.signature(XHSLike)) == '(*args, **kwargs)'
    init_sig = inspect.signature(XHSLike.__init__)
    for name in ("work_path", "folder_name", "cookie", "image_download", "video_download", "live_download"):
        assert name in init_sig.parameters

    workflow = Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8')
    sidecar = Path('scripts/engine_xhs_entry.py').read_text(encoding='utf-8')
    assert 'inspect.signature(XHS.__init__)' in workflow
    assert 'inspect.signature(XHS.__init__)' in sidecar
    assert 'inspect.signature(XHS)\n' not in workflow
    assert 'inspect.signature(XHS)\n' not in sidecar
