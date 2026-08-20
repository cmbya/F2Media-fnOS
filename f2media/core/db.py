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
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
        # The DB contains encrypted cookies plus task history. Keep the main DB private even
        # if the parent directory was created with a permissive umask. SQLite WAL/SHM files are
        # transient and inherit directory protection; the service data directory is also private.
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def mark_interrupted_tasks(self) -> int:
        """Mark tasks left active by an unclean shutdown as failed."""
        with self._lock, self._conn() as c:
            cur = c.execute(
                """UPDATE tasks
                   SET status='failed', message='应用重启，上一轮任务中断', finished_at=?
                   WHERE status IN ('queued','running')""",
                (now_iso(),),
            )
            return int(cur.rowcount or 0)

    def create_task(self, row: dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO tasks
                (id,source_text,url,platform,status,output_dir,created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    row["id"], row["source_text"], row["url"], row["platform"],
                    row["status"], row["output_dir"], row["created_at"],
                ),
            )

    def update_task(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {"status", "adapter", "message", "started_at", "finished_at", "files_json"}
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

    def clear_tasks(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM tasks")

    def put_cookie(self, platform: str, cookie_cipher: bytes, extra_cipher: bytes | None) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO cookies(platform,cookie_cipher,extra_cipher,updated_at)
                VALUES(?,?,?,?) ON CONFLICT(platform) DO UPDATE SET
                cookie_cipher=excluded.cookie_cipher, extra_cipher=excluded.extra_cipher,
                updated_at=excluded.updated_at""",
                (platform, cookie_cipher, extra_cipher, now_iso()),
            )

    def get_cookie(self, platform: str) -> sqlite3.Row | None:
        with self._lock, self._conn() as c:
            return c.execute("SELECT * FROM cookies WHERE platform=?", (platform,)).fetchone()

    def cookie_statuses(self) -> list[dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT platform, updated_at, extra_cipher IS NOT NULL AS has_extra FROM cookies ORDER BY platform").fetchall()
        return [dict(r) for r in rows]

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
