"""SQLite 连接管理与建表。业务 DAO 见 event_dao.py / asset_dao.py / production_dao.py。"""

import sqlite3
import threading
from pathlib import Path

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        score REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        timeline_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS media_assets (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL,
        type TEXT NOT NULL,
        source_url TEXT NOT NULL DEFAULT '',
        source_type TEXT NOT NULL DEFAULT 'A',
        auth_status TEXT NOT NULL DEFAULT 'pending',
        auth_evidence TEXT NOT NULL DEFAULT '',
        license_business INTEGER NOT NULL DEFAULT 1,
        attribution TEXT NOT NULL DEFAULT '',
        clarity TEXT,
        info_density REAL,
        duration_s REAL,
        fingerprint TEXT NOT NULL DEFAULT '',
        ingested_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_media_assets_event ON media_assets(event_id)",
    """
    CREATE TABLE IF NOT EXISTS production (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL,
        production_type TEXT NOT NULL,
        asset_ids_json TEXT NOT NULL DEFAULT '[]',
        title TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        cover_asset_id TEXT NOT NULL DEFAULT '',
        rule TEXT NOT NULL DEFAULT '',
        composer TEXT NOT NULL DEFAULT 'template',
        quality_score REAL NOT NULL DEFAULT 0,
        quality_status TEXT NOT NULL,
        checks_json TEXT NOT NULL DEFAULT '[]',
        vetoes_json TEXT NOT NULL DEFAULT '[]',
        account_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_production_event ON production(event_id)",
]


class DB:
    """极简 SQLite 连接封装（单连接 + 线程锁，适配 FastAPI 线程池）。"""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def migrate(self) -> None:
        """幂等建表，应用启动与测试夹具时调用。"""
        with self._lock:
            conn = self.connect()
            for ddl in _SCHEMA:
                conn.execute(ddl)
            conn.commit()

    def run(self, sql: str, params: tuple = ()) -> None:
        """原子写入：execute + commit 在锁内完成。"""
        with self._lock:
            conn = self.connect()
            conn.execute(sql, params)
            conn.commit()

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """线程安全的只读查询。"""
        with self._lock:
            return self.connect().execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
