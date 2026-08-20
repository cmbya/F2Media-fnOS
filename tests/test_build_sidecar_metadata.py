from pathlib import Path


def test_xhs_sidecar_eliminates_unused_fastmcp_dependency():
    workflow = Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8')
    assert "(rookiepy|fastmcp)" in workflow
    assert "cat > build/vendor/xhs/source/__init__.py" in workflow
    assert "sed -i '/^from fastmcp import FastMCP$/d'" in workflow
    assert 'XHS reduced API import OK' in workflow
    assert '--collect-all fastmcp' not in workflow
    assert '--copy-metadata fastmcp' not in workflow


def test_main_runtime_bundles_mcp_and_parse_metadata():
    workflow = Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8')
    for token in (
        '--collect-all fastapi_mcp',
        '--collect-all mcp',
        '--collect-all parse_video_py',
        '--copy-metadata fastapi-mcp',
        '--copy-metadata mcp',
        '--copy-metadata parse-video-py',
    ):
        assert token in workflow
    assert "obj.get('mcp_enabled') is True" in workflow
    assert "X-API-Key: ci-test-api-key" in workflow
