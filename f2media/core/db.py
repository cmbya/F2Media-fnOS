from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today_local() -> str:
    return datetime.now().astimezone().date().isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _ensure_column(c: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
        columns = {str(row["name"]) for row in c.execute(f"PRAGMA table_info({table})").fetchall()}
        if name not in columns:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def _init(self) -> None:
        with self._lock, self._conn() as c:
            c.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    source_text TEXT NOT NULL,
                    url TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    status TEXT NOT NULL,
                    adapter TEXT,
                    message TEXT,
                    output_dir TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    files_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);
                CREATE TABLE IF NOT EXISTS cookies (
                    platform TEXT PRIMARY KEY,
                    cookie_cipher BLOB NOT NULL,
                    extra_cipher BLOB,
                    allowed_parsers_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS parse_results (
                    id TEXT PRIMARY KEY,
                    source_text TEXT NOT NULL,
                    url TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    parser TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_parse_results_created ON parse_results(created_at DESC);
                CREATE TABLE IF NOT EXISTS parser_apis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    platforms_json TEXT NOT NULL DEFAULT '[]',
                    url TEXT NOT NULL,
                    method TEXT NOT NULL DEFAULT 'GET',
                    url_param TEXT NOT NULL DEFAULT 'url',
                    headers_json TEXT NOT NULL DEFAULT '{}',
                    params_json TEXT NOT NULL DEFAULT '{}',
                    mapping_json TEXT NOT NULL DEFAULT '{}',
                    timeout INTEGER NOT NULL DEFAULT 15,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 100,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                """
            )
            # In-place migration from 0.1.x.  Keep old history/cookies/settings intact.
            self._ensure_column(c, "tasks", "parse_id", "TEXT")
            self._ensure_column(c, "tasks", "title", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(c, "tasks", "progress", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(c, "tasks", "source_key", "TEXT NOT NULL DEFAULT ''")
            # Cookie access is deny-by-default. Existing cookies therefore migrate
            # with an empty parser allow-list until the user explicitly grants access.
            self._ensure_column(c, "cookies", "allowed_parsers_json", "TEXT NOT NULL DEFAULT '[]'")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def mark_interrupted_tasks(self) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                """UPDATE tasks
                   SET status='failed', message='应用重启，上一轮任务中断', finished_at=?
                   WHERE status IN ('queued','parsing','running','downloading','merging')""",
                (now_iso(),),
            )
            return int(cur.rowcount or 0)

    def create_task(self, row: dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO tasks
                (id,source_text,url,platform,status,output_dir,created_at,parse_id,title,progress,source_key)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["id"], row.get("source_text") or row["url"], row["url"], row["platform"],
                    row["status"], row.get("output_dir") or "", row.get("created_at") or now_iso(),
                    row.get("parse_id"), row.get("title") or "", int(row.get("progress") or 0),
                    row.get("source_key") or row["url"],
                ),
            )

    def update_task(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status", "adapter", "message", "started_at", "finished_at", "files_json",
            "output_dir", "parse_id", "title", "progress", "source_key", "url", "platform",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unsupported task fields: {sorted(bad)}")
        keys = list(fields)
        values = [fields[k] for k in keys]
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE tasks SET {', '.join(k + '=?' for k in keys)} WHERE id=?", (*values, task_id))

    def task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self._row_task(r) if r else None

    def tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_task(r) for r in rows]

    @staticmethod
    def _row_task(r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["files"] = json.loads(d.pop("files_json") or "[]")
        return d

    def duplicate_today(self, source_key: str) -> dict[str, Any] | None:
        if not source_key:
            return None
        with self._lock, self._conn() as c:
            row = c.execute(
                """SELECT * FROM tasks
                   WHERE source_key=? AND substr(created_at,1,10)=? AND status IN ('success','partial')
                   ORDER BY created_at DESC LIMIT 1""",
                (source_key, today_local()),
            ).fetchone()
        return self._row_task(row) if row else None

    def delete_task(self, task_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM tasks WHERE id=?", (task_id,))

    def clear_tasks(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM tasks")

    def put_parse_result(self, parse_id: str, source_text: str, result: dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO parse_results
                   (id,source_text,url,platform,title,parser,result_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    parse_id, source_text, str(result.get("source_url") or ""),
                    str(result.get("platform") or "unknown"), str(result.get("title") or ""),
                    str(result.get("parser") or ""), json.dumps(result, ensure_ascii=False), now_iso(),
                ),
            )

    def parse_result(self, parse_id: str) -> dict[str, Any] | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT result_json FROM parse_results WHERE id=?", (parse_id,)).fetchone()
        return json.loads(row["result_json"]) if row else None

    def put_cookie(
        self,
        platform: str,
        cookie_cipher: bytes,
        extra_cipher: bytes | None,
        allowed_parsers: list[str] | None = None,
    ) -> None:
        with self._lock, self._conn() as c:
            if allowed_parsers is None:
                existing = c.execute(
                    "SELECT allowed_parsers_json FROM cookies WHERE platform=?", (platform,)
                ).fetchone()
                allowed_parsers = json.loads(existing["allowed_parsers_json"] or "[]") if existing else []
            c.execute(
                """INSERT INTO cookies(platform,cookie_cipher,extra_cipher,allowed_parsers_json,updated_at)
                VALUES(?,?,?,?,?) ON CONFLICT(platform) DO UPDATE SET
                cookie_cipher=excluded.cookie_cipher, extra_cipher=excluded.extra_cipher,
                allowed_parsers_json=excluded.allowed_parsers_json, updated_at=excluded.updated_at""",
                (platform, cookie_cipher, extra_cipher, json.dumps(allowed_parsers or [], ensure_ascii=False), now_iso()),
            )

    def get_cookie(self, platform: str) -> sqlite3.Row | None:
        with self._lock, self._conn() as c:
            return c.execute("SELECT * FROM cookies WHERE platform=?", (platform,)).fetchone()

    def cookie_statuses(self) -> list[dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT platform, updated_at, extra_cipher IS NOT NULL AS has_extra, allowed_parsers_json FROM cookies ORDER BY platform").fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["allowed_parsers"] = json.loads(item.pop("allowed_parsers_json") or "[]")
            out.append(item)
        return out

    def set_cookie_permissions(self, platform: str, allowed_parsers: list[str]) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE cookies SET allowed_parsers_json=?, updated_at=? WHERE platform=?",
                (json.dumps(allowed_parsers, ensure_ascii=False), now_iso(), platform),
            )

    def delete_cookie(self, platform: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM cookies WHERE platform=?", (platform,))

    def get_setting(self, key: str) -> str | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def put_setting(self, key: str, value: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, value, now_iso()),
            )

    def delete_setting(self, key: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM app_settings WHERE key=?", (key,))

    @staticmethod
    def _api_row(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["platforms"] = json.loads(d.pop("platforms_json") or "[]")
        d["headers"] = json.loads(d.pop("headers_json") or "{}")
        d["params"] = json.loads(d.pop("params_json") or "{}")
        d["mapping"] = json.loads(d.pop("mapping_json") or "{}")
        d["enabled"] = bool(d["enabled"])
        d["is_default"] = bool(d["is_default"])
        return d

    def parser_apis(self, platform: str | None = None, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM parser_apis"
        clauses: list[str] = []
        args: list[Any] = []
        if enabled_only:
            clauses.append("enabled=1")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY priority ASC,id ASC"
        with self._lock, self._conn() as c:
            rows = c.execute(query, args).fetchall()
        items = [self._api_row(r) for r in rows]
        if platform:
            items = [x for x in items if "*" in x["platforms"] or platform in x["platforms"]]
        return items

    def put_parser_api(self, config: dict[str, Any], api_id: int | None = None) -> dict[str, Any]:
        name = str(config.get("name") or "").strip()
        url = str(config.get("url") or "").strip()
        method = str(config.get("method") or "GET").upper()
        platforms = config.get("platforms") or []
        if not name or not url.startswith(("http://", "https://")):
            raise ValueError("免费 API 必须填写名称和 http/https 地址")
        if method not in {"GET", "POST"}:
            raise ValueError("请求方式只能是 GET 或 POST")
        if isinstance(platforms, str):
            platforms = [x.strip() for x in platforms.split(",") if x.strip()]
        if not platforms:
            raise ValueError("至少选择一个平台")
        values = (
            name, json.dumps(platforms, ensure_ascii=False), url, method,
            str(config.get("url_param") or "url"), json.dumps(config.get("headers") or {}, ensure_ascii=False),
            json.dumps(config.get("params") or {}, ensure_ascii=False), json.dumps(config.get("mapping") or {}, ensure_ascii=False),
            max(3, min(int(config.get("timeout") or 15), 120)), 1 if config.get("enabled", True) else 0,
            int(config.get("priority") or 100), 1 if config.get("is_default") else 0, now_iso(),
        )
        with self._lock, self._conn() as c:
            if api_id is None:
                cur = c.execute(
                    """INSERT INTO parser_apis
                    (name,platforms_json,url,method,url_param,headers_json,params_json,mapping_json,timeout,enabled,priority,is_default,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", values,
                )
                api_id = int(cur.lastrowid)
            else:
                c.execute(
                    """UPDATE parser_apis SET
                    name=?,platforms_json=?,url=?,method=?,url_param=?,headers_json=?,params_json=?,mapping_json=?,timeout=?,enabled=?,priority=?,is_default=?,updated_at=?
                    WHERE id=?""", (*values, api_id),
                )
            row = c.execute("SELECT * FROM parser_apis WHERE id=?", (api_id,)).fetchone()
        if not row:
            raise RuntimeError("保存免费 API 配置失败")
        return self._api_row(row)

    def seed_parser_api(self, config: dict[str, Any]) -> None:
        name = str(config.get("name") or "")
        url = str(config.get("url") or "")
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id FROM parser_apis WHERE name=? OR url=? LIMIT 1",
                (name, url),
            ).fetchone()
        if row:
            return
        seeded = dict(config)
        seeded["is_default"] = True
        self.put_parser_api(seeded)

    def delete_parser_api(self, api_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM parser_apis WHERE id=?", (api_id,))
