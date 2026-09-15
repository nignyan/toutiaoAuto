"""SQLite 连接管理骨架。表结构与业务 DAO 在后续迭代中实现。"""

import sqlite3
from pathlib import Path


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

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None