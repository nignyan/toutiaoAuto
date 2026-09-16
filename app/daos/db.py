"""SQLite 连接管理与建表。业务 DAO 见 event_dao.py / asset_dao.py / production_dao.py 等。"""

import sqlite3
import threading
from contextlib import contextmanager
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
        created_at TEXT NOT NULL,
        deferred_at TEXT NOT NULL DEFAULT '',
        deferred_retries INTEGER NOT NULL DEFAULT 0
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
        vertical TEXT NOT NULL DEFAULT '',
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
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        vertical TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT 'primary',
        daily_quota INTEGER NOT NULL DEFAULT 0,
        publish_window_start TEXT NOT NULL DEFAULT '',
        publish_window_end TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        channel TEXT NOT NULL DEFAULT 'toutiao',
        adapter TEXT NOT NULL DEFAULT 'draft',
        auto_publish INTEGER NOT NULL DEFAULT 0,
        profile_dir TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS publish_queue (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        production_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        scheduled_for TEXT NOT NULL DEFAULT '',
        publish_result TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    # production 与队列项 1:1，唯一索引兜底重复入队（规格 D10 §4.3）
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_publish_queue_production"
    " ON publish_queue(production_id)",
    "CREATE INDEX IF NOT EXISTS idx_publish_queue_account ON publish_queue(account_id)",
]

# 存量库补列迁移：CREATE TABLE IF NOT EXISTS 不会更新已存在的表
_COLUMN_MIGRATIONS = {
    "events": {
        "deferred_at": "deferred_at TEXT NOT NULL DEFAULT ''",
        "deferred_retries": "deferred_retries INTEGER NOT NULL DEFAULT 0",
    },
    "production": {"vertical": "vertical TEXT NOT NULL DEFAULT ''"},
}


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for col, ddl in columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


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
        """幂等建表 + 存量库补列，应用启动与测试夹具时调用。"""
        with self._lock:
            conn = self.connect()
            for ddl in _SCHEMA:
                conn.execute(ddl)
            for table, columns in _COLUMN_MIGRATIONS.items():
                _ensure_columns(conn, table, columns)
            conn.commit()

    def run(self, sql: str, params: tuple = ()) -> None:
        """原子写入：execute + commit 在锁内完成。"""
        with self._lock:
            conn = self.connect()
            conn.execute(sql, params)
            conn.commit()

    @contextmanager
    def transaction(self):
        """跨表原子写入：锁内显式事务，异常时回滚（如生产落库 + 事件状态更新）。"""
        with self._lock:
            conn = self.connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """线程安全的只读查询。"""
        with self._lock:
            return self.connect().execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
