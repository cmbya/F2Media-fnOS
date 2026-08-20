from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import __version__
from .adapters.registry import AdapterRegistry
from .core.app_settings import AppSettingsStore
from .core.auth import AuthStore
from .core.config import load_settings
from .core.cookies import CookieStore
from .core.db import Database
from .core.doctor import diagnostics
from .core.logging import TaskLog, setup_logging
from .parse_service import ParseService
from .service import DownloadService

settings = load_settings()
logger = setup_logging(settings.log_dir, settings.log_level)
db = Database(settings.db_path)
app_settings = AppSettingsStore(db, settings)
cookies = CookieStore(db, settings.secret_key_path)
auth_store = AuthStore(db, settings.secret_key_path)
registry = AdapterRegistry()
service = DownloadService(settings, app_settings, db, cookies, registry, logger)
parse_service = ParseService(settings, app_settings, cookies, logger)
STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    interrupted = db.mark_interrupted_tasks()
    if interrupted:
        logger.warning("marked %s stale queued/running tasks as interrupted after restart", interrupted)
    effective = app_settings.effective_download_dir()
    info = diagnostics(effective, settings.data_dir)
    logger.info("F2Media %s startup host=%s port=%s", __version__, settings.host, settings.port)
    logger.info("runtime diagnostics=%s", json.dumps(info, ensure_ascii=False))
    logger.info("app settings=%s", json.dumps(app_settings.snapshot(), ensure_ascii=False))
    logger.info("web auth configured=%s; mcp/api key configured=true", auth_store.web_configured())
    for row in registry.doctor():
        logger.info("adapter doctor: %s", json.dumps(row, ensure_ascii=False))
    yield
    logger.info("F2Media shutdown")


app = FastAPI(title="F2Media", version=__version__, lifespan=lifespan)


class DownloadRequest(BaseModel):
    text: str


class ParseRequest(BaseModel):
    text: str


class CookieRequest(BaseModel):
    cookie: str
    extra: str | None = None


class SettingsRequest(BaseModel):
    download_dir: str | None = None


class WebSetupRequest(BaseModel):
    username: str
    password: str


class WebChangeRequest(BaseModel):
    username: str
    password: str


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
        "shortcut_download_url": f"{base}/api/v1/download",
        "shortcut_parse_url": f"{base}/api/v1/parse",
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
    logger.info("MCP/Shortcut API key regenerated")
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
        "adapters": registry.doctor(),
    }


@web.post("/parse")
async def parse_media_web(req: ParseRequest):
    try:
        return await parse_service.parse_text(req.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@web.post("/downloads")
async def create_download(req: DownloadRequest):
    try:
        return await service.submit(req.text)
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


@web.delete("/tasks")
def clear_tasks():
    db.clear_tasks()
    for p in settings.task_log_dir.glob("*.log"):
        p.unlink(missing_ok=True)
    return {"ok": True}


@web.get("/cookies")
def cookie_status():
    return db.cookie_statuses()


@web.put("/cookies/{platform}")
def save_cookie(platform: str, req: CookieRequest):
    if platform not in {"douyin", "tiktok", "twitter", "instagram", "facebook", "youtube", "bilibili", "kuaishou", "xiaohongshu"}:
        raise HTTPException(400, "unsupported platform")
    try:
        cookies.save(platform, req.cookie, req.extra)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info("Cookie updated platform=%s extra=%s", platform, bool(req.extra))
    return {"ok": True, "platform": platform}


@web.delete("/cookies/{platform}")
def delete_cookie(platform: str):
    db.delete_cookie(platform)
    logger.info("Cookie deleted platform=%s", platform)
    return {"ok": True}


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

# These three REST operations are the exact capabilities exposed through MCP.  They use a
# separate API key, never the WebUI password.  Apple Shortcuts can call the REST form directly,
# while MCP clients use the same operations through /mcp.
api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)], tags=["mcp-tools"])


@api.post("/parse", operation_id="parse_media")
async def parse_media_api(req: ParseRequest):
    """Parse one or more shared media links on the NAS without downloading files."""
    try:
        return await parse_service.parse_text(req.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.post("/download", operation_id="download_to_nas")
async def download_to_nas(req: DownloadRequest):
    """Submit shared media links to F2Media; the NAS performs and stores the downloads."""
    try:
        return await service.submit(req.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.get("/tasks/{task_id}", operation_id="get_task_status")
def get_task_status(task_id: str):
    """Return the current NAS-side download task status and output files."""
    row = db.task(task_id)
    if not row:
        raise HTTPException(404, "task not found")
    return row


app.include_router(api)

# Streamable HTTP MCP at /mcp.  Mount on a router that has the same API-key dependency, and
# forward X-API-Key into the generated ASGI tool calls so the REST operations stay protected too.
try:
    from fastapi_mcp import FastApiMCP

    mcp = FastApiMCP(
        app,
        name="F2Media NAS MCP",
        description="Parse media links and submit downloads that are executed and stored on the NAS.",
        include_operations=["parse_media", "download_to_nas", "get_task_status"],
        headers=["authorization", "x-api-key"],
    )
    mcp_router = APIRouter(dependencies=[Depends(require_api_key)])
    mcp.mount_http(router=mcp_router, mount_path="/mcp")
except Exception as exc:  # fail loudly in logs; CI runtime selfcheck also verifies MCP deps
    logger.exception("MCP initialization failed: %s", exc)
    mcp = None


def run() -> None:
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info", access_log=False)


if __name__ == "__main__":
    run()
