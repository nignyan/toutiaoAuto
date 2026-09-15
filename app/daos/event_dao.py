"""事件表数据访问对象。"""

import json

from app.daos.db import DB
from app.models import Event, EventStatus, TimelineEntry

_SORT_SQL = "ORDER BY score DESC, created_at DESC"


def _to_row(event: Event) -> tuple:
    return (
        event.id,
        event.title,
        event.summary,
        event.score,
        event.status.value,
        json.dumps([t.model_dump() for t in event.timeline], ensure_ascii=False),
        event.created_at,
    )


def _from_row(row) -> Event:
    return Event(
        id=row["id"],
        title=row["title"],
        summary=row["summary"],
        score=row["score"],
        status=EventStatus(row["status"]),
        timeline=[TimelineEntry(**t) for t in json.loads(row["timeline_json"])],
        created_at=row["created_at"],
    )


class EventDao:
    """events 表的存取。"""

    def __init__(self, db: DB) -> None:
        self._db = db

    def upsert(self, event: Event) -> None:
        """整行覆盖写入（聚类编排层负责合并 timeline / score 后调用）。"""
        self._db.connect().execute(
            "INSERT OR REPLACE INTO events"
            " (id, title, summary, score, status, timeline_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            _to_row(event),
        )
        self._db.connect().commit()

    def get(self, event_id: str) -> Event | None:
        row = self._db.connect().execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return _from_row(row) if row else None

    def list_all(self, status: EventStatus | None = None, limit: int | None = None) -> list[Event]:
        """按 score 降序返回事件，可按状态过滤。"""
        sql = "SELECT * FROM events"
        params: list = []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status.value)
        sql += f" {_SORT_SQL}"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._db.connect().execute(sql, params).fetchall()
        return [_from_row(r) for r in rows]
