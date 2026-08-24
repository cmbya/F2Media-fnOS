from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import __version__
from .core.app_settings import AppSettingsStore
from .core.auth import AuthStore
from .core.config import load_settings
from .core.cookies import CookieStore
from .core.db import Database
from .core.doctor import diagnostics, parser_diagnostics
from .core.engine_update import EngineUpdater
from .core.logging import TaskLog, setup_logging
from .core.parser_routes import ParserRouteStore
from .parse_service import ParseService
from .parsers.free_api import FreeApiStore
from .service import DownloadService

settings = load_settings()
logger = setup_logging(settings.log_dir, settings.log_level)
db = Database(settings.db_path)
app_settings = AppSettingsStore(db, settings)
cookies = CookieStore(db, settings.secret_key_path)
auth_store = AuthStore(db, settings.secret_key_path)
free_apis = FreeApiStore(db)
routes = ParserRouteStore(db)
engine_updater = EngineUpdater(settings.data_dir)
parse_service = ParseService(settings, app_settings, cookies, db, free_apis, routes, logger)
service = DownloadService(settings, app_settings, db, cookies, parse_service, logger)
STATIC = Path(__file__).resolve().parent / "static"
PLATFORMS = {"douyin", "tiktok", "twitter", "instagram", "facebook", "youtube", "bilibili", "kuaishou", "xiaohongshu"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    interrupted = db.mark_interrupted_tasks()
    if interrupted:
        logger.warning("marked %s stale tasks as interrupted after restart", interrupted)
    effective = app_settings.effective_download_dir()
    info = diagnostics(effective, settings.data_dir)
    logger.info("F2Media %s startup host=%s port=%s", __version__, settings.host, settings.port)
    logger.info("runtime diagnostics=%s", json.dumps(info, ensure_ascii=False))
    logger.info("app settings=%s", json.dumps(app_settings.snapshot(), ensure_ascii=False))
    logger.info("web auth configured=%s; mcp/api key configured=true", auth_store.web_configured())
    for row in parser_diagnostics():
        logger.info("parser doctor: %s", json.dumps(row, ensure_ascii=False))
    yield
    logger.info("F2Media shutdown")


app = FastAPI(title="F2Media", version=__version__, lifespan=lifespan)


class ParseRequest(BaseModel):
    text: str
    parser: str | None = None


class UrlRequest(BaseModel):
    url: str
    parser: str | None = None


class ParsedDownloadRequest(BaseModel):
    parse_id: str
    force: bool = False


class ParseAndDownloadRequest(BaseModel):
    url: str
    force: bool = False


class CookieRequest(BaseModel):
    cookie: str
    extra: str | None = None
    allowed_parsers: list[str] | None = None


class CookiePermissionRequest(BaseModel):
    allowed_parsers: list[str] = Field(default_factory=list)


class SettingsRequest(BaseModel):
    download_dir: str | None = None


class WebSetupRequest(BaseModel):
    username: str
    password: str


class WebChangeRequest(BaseModel):
    username: str
    password: str


class ParserApiRequest(BaseModel):
    name: str
    platforms: list[str]
    url: str
    method: str = "GET"
    url_param: str = "url"
    headers: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    mapping: dict[str, Any] = Field(default_factory=dict)
    timeout: int = 15
    enabled: bool = True
    priority: int = 100


class ParserApiTestRequest(BaseModel):
    platform: str
    url: str


class ParserRouteItemRequest(BaseModel):
    key: str
    enabled: bool = True
    cookie_enabled: bool = False


class ParserRouteRequest(BaseModel):
    items: list[ParserRouteItemRequest]


def _web_credentials(request: Request) -> tuple[str, str] | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header.split(None, 1)[1]).decode("utf-8")
        username, password = raw.split(":", 1)
        return username, password
    except Exception:
        return None


def require_web_auth(request: Request) -> None:
    if not auth_store.web_configured():
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, "WebUI 尚未初始化，请先访问首页创建账户")
    creds = _web_credentials(request)
    if not creds or not auth_store.verify_web(*creds):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "用户名或密码错误",
            headers={"WWW-Authenticate": 'Basic realm="F2Media"'},
        )


def _request_api_key(request: Request) -> str | None:
    key = request.headers.get("x-api-key", "").strip()
    if key:
        return key
    auth = request.headers.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip()
    return None


def require_api_key(request: Request) -> None:
    if not auth_store.verify_api_key(_request_api_key(request)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API Key 无效或未提供")


@app.get("/")
def index(request: Request):
    if not auth_store.web_configured():
        return FileResponse(STATIC / "setup.html")
    require_web_auth(request)
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "version": __version__,
        "web_auth_configured": auth_store.web_configured(),
        "mcp_enabled": mcp is not None,
        "mcp_path": "/mcp",
        "mcp_tools": ["parse_media", "download_to_nas", "parse_and_download", "get_task_status"],
    }


@app.post("/api/auth/setup")
def auth_setup(req: WebSetupRequest):
    try:
        auth_store.setup_web(req.username, req.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info("WebUI account initialized username=%s", req.username.strip())
    return {"ok": True}


web = APIRouter(prefix="/api", dependencies=[Depends(require_web_auth)])


@web.get("/auth/config")
def auth_config(request: Request):
    base = str(request.base_url).rstrip("/")
    return {
        "username": auth_store.username(),
        "api_key": auth_store.api_key(),
        "mcp_url": f"{base}/mcp",
        "shortcut_url": f"{base}/api/v1/parse-and-download",
        "shortcut_status_url": f"{base}/api/v1/tasks/{{task_id}}",
        "api_key_header": "X-API-Key",
    }


@web.put("/auth/web")
def auth_change(req: WebChangeRequest):
    try:
        auth_store.setup_web(req.username, req.password, force=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info("WebUI credentials updated username=%s", req.username.strip())
    return {"ok": True}


@web.post("/auth/api-key/regenerate")
def regenerate_api_key():
    value = auth_store.regenerate_api_key()
    logger.info("MCP/REST API key regenerated")
    return {"ok": True, "api_key": value}


@web.get("/settings")
def get_settings():
    return app_settings.snapshot()


@web.put("/settings")
def put_settings(req: SettingsRequest):
    try:
        path = app_settings.set_download_dir(req.download_dir)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info("download directory updated path=%s", path)
    return {"ok": True, **app_settings.snapshot()}


@web.get("/doctor")
def doctor():
    effective = app_settings.effective_download_dir()
    return {
        "runtime": diagnostics(effective, settings.data_dir),
        "settings": app_settings.snapshot(),
        "auth": {"web_configured": auth_store.web_configured(), "mcp_enabled": mcp is not None},
        "parsers": parser_diagnostics(),
        "engines": [engine_updater.local_status(x) for x in ("gallery-dl", "yt-dlp", "x-cli")],
        "free_apis": free_apis.list(),
        "parser_routes": routes.all(),
    }


@web.post("/parse")
async def parse_media_web(req: ParseRequest):
    try:
        return await parse_service.parse_text(req.text, parser=req.parser)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@web.post("/downloads")
async def create_download(req: ParsedDownloadRequest):
    try:
        return await service.submit_parse_id(req.parse_id, force=req.force)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@web.get("/tasks")
def tasks(limit: int = 100):
    return db.tasks(max(1, min(limit, 500)))


@web.get("/tasks/{task_id}")
def task(task_id: str):
    row = db.task(task_id)
    if not row:
        raise HTTPException(404, "task not found")
    return row


@web.get("/tasks/{task_id}/log", response_class=PlainTextResponse)
def task_log(task_id: str):
    if not db.task(task_id):
        raise HTTPException(404, "task not found")
    return TaskLog(settings.task_log_dir / f"{task_id}.log").tail()


@web.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    try:
        return await service.retry(task_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@web.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    if not await service.cancel(task_id):
        raise HTTPException(404, "task not found")
    return {"ok": True}


@web.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    row = db.task(task_id)
    if not row:
        raise HTTPException(404, "task not found")
    if row.get("status") in {"queued", "parsing", "running", "downloading", "merging"}:
        raise HTTPException(409, "任务仍在运行，请先取消")
    db.delete_task(task_id)
    (settings.task_log_dir / f"{task_id}.log").unlink(missing_ok=True)
    return {"ok": True}


@web.delete("/tasks")
def clear_tasks():
    active = [x for x in db.tasks(500) if x.get("status") in {"queued", "parsing", "running", "downloading", "merging"}]
    if active:
        raise HTTPException(409, "仍有运行中的任务，请先取消")
    db.clear_tasks()
    for p in settings.task_log_dir.glob("*.log"):
        p.unlink(missing_ok=True)
    return {"ok": True}


@web.get("/cookies")
def cookie_status():
    current = {x["platform"]: x for x in db.cookie_statuses()}
    return [
        {"platform": platform, "configured": platform in current, **(current.get(platform) or {})}
        for platform in sorted(PLATFORMS)
    ]


@web.put("/cookies/{platform}")
def save_cookie(platform: str, req: CookieRequest):
    if platform not in PLATFORMS:
        raise HTTPException(400, "unsupported platform")
    allowed = req.allowed_parsers
    if allowed is not None:
        available = {x["key"] for x in routes.parser_options(platform)}
        allowed = [x for x in dict.fromkeys(allowed) if x in available]
    try:
        cookies.save(platform, req.cookie, req.extra, allowed)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info("Cookie updated platform=%s extra=%s", platform, bool(req.extra))
    return {"ok": True, "platform": platform}


@web.put("/cookies/{platform}/permissions")
def set_cookie_permissions(platform: str, req: CookiePermissionRequest):
    if platform not in PLATFORMS:
        raise HTTPException(400, "unsupported platform")
    if not db.get_cookie(platform):
        raise HTTPException(400, "请先保存该平台 Cookie，再设置读取授权")
    available = {x["key"] for x in routes.parser_options(platform)}
    allowed = [x for x in dict.fromkeys(req.allowed_parsers) if x in available]
    cookies.set_permissions(platform, allowed)
    logger.info("Cookie permissions updated platform=%s parsers=%s", platform, allowed)
    return {"ok": True, "platform": platform, "allowed_parsers": allowed}


@web.delete("/cookies/{platform}")
def delete_cookie(platform: str):
    db.delete_cookie(platform)
    logger.info("Cookie deleted platform=%s", platform)
    return {"ok": True}


@web.get("/parser-apis")
def parser_apis():
    return free_apis.list()


@web.post("/parser-apis")
def create_parser_api(req: ParserApiRequest):
    try:
        return free_apis.save(req.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@web.put("/parser-apis/{api_id}")
def update_parser_api(api_id: int, req: ParserApiRequest):
    try:
        return free_apis.save(req.model_dump(), api_id=api_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@web.delete("/parser-apis/{api_id}")
def delete_parser_api(api_id: int):
    free_apis.delete(api_id)
    return {"ok": True}


@web.post("/parser-apis/{api_id}/test")
async def test_parser_api(api_id: int, req: ParserApiTestRequest):
    config = next((x for x in free_apis.list() if int(x["id"]) == api_id), None)
    if not config:
        raise HTTPException(404, "API config not found")
    if req.platform not in PLATFORMS:
        raise HTTPException(400, "unsupported platform")
    try:
        result = await free_apis.call(config, req.platform, req.url)
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@web.get("/parser-routes")
def parser_routes():
    return routes.all()


@web.get("/parser-routes/{platform}")
def parser_route(platform: str):
    try:
        return routes.get(platform)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@web.put("/parser-routes/{platform}")
def save_parser_route(platform: str, req: ParserRouteRequest):
    try:
        return routes.save(platform, [x.model_dump() for x in req.items])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@web.post("/parser-routes/{platform}/reset")
def reset_parser_route(platform: str):
    try:
        return routes.reset(platform)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@web.get("/engines")
def engine_status():
    return [engine_updater.local_status(x) for x in ("gallery-dl", "yt-dlp", "x-cli")]


@web.post("/engines/{name}/check")
async def engine_check(name: str):
    try:
        return await engine_updater.check(name)
    except Exception as exc:
        detail = str(exc).strip() or f"{type(exc).__name__}: 更新检查失败"
        raise HTTPException(400, detail) from exc


@web.post("/engines/{name}/update")
async def engine_update(name: str):
    try:
        result = await engine_updater.update(name)
        logger.info("engine updated name=%s version=%s", name, result.get("version"))
        return result
    except Exception as exc:
        logger.exception("engine update failed name=%s", name)
        detail = str(exc).strip() or f"{type(exc).__name__}: 更新失败"
        raise HTTPException(400, detail) from exc


@web.post("/engines/{name}/rollback")
def engine_rollback(name: str):
    try:
        result = engine_updater.rollback(name)
        logger.info("engine rollback name=%s version=%s", name, result.get("version"))
        return result
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


def _tail_text(path: Path, max_chars: int = 400_000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-max_chars:]


@web.get("/logs", response_class=PlainTextResponse)
def app_log():
    return _tail_text(settings.log_dir / "f2media.log")


@web.get("/logs/console", response_class=PlainTextResponse)
def console_log():
    return _tail_text(settings.log_dir / "runtime-console.log")


@web.delete("/logs")
def clear_logs():
    active = settings.log_dir / "f2media.log"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text("", encoding="utf-8")
    for p in settings.log_dir.glob("f2media.log.*"):
        p.unlink(missing_ok=True)
    console = settings.log_dir / "runtime-console.log"
    if console.exists():
        console.write_text("", encoding="utf-8")
    return {"ok": True}


app.include_router(web)

# REST API: Apple Shortcuts uses parse-and-download. MCP exposes the exact same four
# operations and shares the independent API Key; WebUI Basic credentials are never used here.
api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)], tags=["mcp-tools"])


@api.post("/parse", operation_id="parse_media")
async def parse_media_api(req: UrlRequest):
    """Parse one media URL on the NAS without downloading any media files."""
    try:
        results = await parse_service.parse_text(req.url, parser=req.parser)
        return results[0] if len(results) == 1 else results
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.post("/download", operation_id="download_to_nas")
async def download_to_nas(req: ParsedDownloadRequest):
    """Download a previously parsed result to the configured NAS media directory."""
    try:
        return await service.submit_parse_id(req.parse_id, force=req.force)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.post("/parse-and-download", operation_id="parse_and_download")
async def parse_and_download(req: ParseAndDownloadRequest):
    """Parse one URL and immediately enqueue its NAS-side download."""
    try:
        results = await service.parse_and_submit(req.url, force=req.force)
        return results[0] if len(results) == 1 else results
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.get("/tasks/{task_id}", operation_id="get_task_status")
def get_task_status(task_id: str):
    """Return the current NAS-side task status, progress, output directory and files."""
    row = db.task(task_id)
    if not row:
        raise HTTPException(404, "task not found")
    return row


app.include_router(api)

try:
    from fastapi_mcp import FastApiMCP

    mcp = FastApiMCP(
        app,
        name="F2Media NAS MCP",
        description="Parse supported social-media URLs and download the actual media to the NAS.",
        include_operations=["parse_media", "download_to_nas", "parse_and_download", "get_task_status"],
        headers=["authorization", "x-api-key"],
    )
    mcp_router = APIRouter(dependencies=[Depends(require_api_key)])
    mcp.mount_http(router=mcp_router, mount_path="/mcp")
except Exception as exc:
    logger.exception("MCP initialization failed: %s", exc)
    mcp = None


def run() -> None:
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info", access_log=False)


if __name__ == "__main__":
    run()
