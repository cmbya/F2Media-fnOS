from pathlib import Path


def test_xhs_sidecar_eliminates_runtime_fastmcp_dependency_but_keeps_lazy_upstream_method():
    workflow = Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8')
    assert "(rookiepy|fastmcp)" in workflow
    assert "cat > build/vendor/xhs/source/__init__.py" in workflow
    assert 'XHS 2.7 FastMCP top-level import signature changed' in workflow
    assert 'XHS 2.7 run_mcp_server FastMCP call signature changed' in workflow
    assert 'from fastmcp import FastMCP\\n\\n' in workflow
    assert 'XHS reduced API import OK' in workflow
    assert '--collect-all fastmcp' not in workflow.split('Build pinned Kuaishou and Xiaohongshu sidecars', 1)[1].split('Download verified external binaries', 1)[0]
    assert '--copy-metadata fastmcp' not in workflow.split('Build pinned Kuaishou and Xiaohongshu sidecars', 1)[1].split('Download verified external binaries', 1)[0]


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
