from pathlib import Path


def test_webui_parse_download_and_auth_controls_are_present():
    html = Path('f2media/static/index.html').read_text(encoding='utf-8')
    for token in ('>解析<', '下载到 NAS', 'MCP / 快捷指令', 'X-API-Key', 'shortcutParseUrl'):
        assert token in html
    assert '创建 WebUI 账户' in Path('f2media/static/setup.html').read_text(encoding='utf-8')


def test_nas_api_and_mcp_contract_is_explicit():
    source = Path('f2media/main.py').read_text(encoding='utf-8')
    assert 'operation_id="parse_media"' in source
    assert 'operation_id="download_to_nas"' in source
    assert 'operation_id="get_task_status"' in source
    assert 'return await service.submit(req.text)' in source
    assert 'mount_path="/mcp"' in source
    assert 'dependencies=[Depends(require_api_key)]' in source
    assert 'headers=["authorization", "x-api-key"]' in source


def test_fastapi_mcp_sdk_pair_is_pinned_and_runtime_probed():
    requirements = Path('requirements-build.txt').read_text(encoding='utf-8')
    pyproject = Path('pyproject.toml').read_text(encoding='utf-8')
    workflow = Path('.github/workflows/build-fnos.yml').read_text(encoding='utf-8')
    assert 'fastapi-mcp==0.4.0' in requirements
    assert 'mcp==1.12.1' in requirements
    assert '"fastapi-mcp==0.4.0"' in pyproject
    assert '"mcp==1.12.1"' in pyproject
    assert 'version("mcp") == "1.12.1"' in workflow
    assert 'FastApiMCP 0.4.0 + mcp 1.12.1 constructor/mount_http probe: OK' in workflow
    assert 'probe_mcp.mount_http(router=probe_router, mount_path="/mcp")' in workflow
