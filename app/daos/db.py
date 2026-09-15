"""SQLite 连接管理与建表。业务 DAO 见 event_dao.py / asset_dao.py。"""

import sqlite3
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
]


class DB:
    """极简 SQLite 连接封装。"""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def migrate(self) -> None:
        """幂等建表，应用启动与测试夹具时调用。"""
        conn = self.connect()
        for ddl in _SCHEMA:
            conn.execute(ddl)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None