"""数据回流表数据访问对象：表现记录（reflux_records）+ 建议动作（reflux_suggestions）。"""

from app.daos.db import DB
from app.models import (
    PerformanceRecord,
    RefluxSuggestion,
    ReviewStatus,
    SuggestionKind,
    SuggestionStatus,
)

_SORT_SQL = "ORDER BY created_at DESC, id ASC"
_RECORD_SORT_SQL = "ORDER BY recorded_at DESC, id ASC"  # 回填时间倒序（最新数据在前）


def _record_row(record: PerformanceRecord) -> tuple:
    return (
        record.id,
        record.production_id,
        record.account_id,
        record.exposure,
        record.plays,
        record.completion_rate,
        record.interactions,
        record.negative,
        record.review_status.value,
        record.review_note,
        record.recorded_at,
        record.created_at,
    )


def _record_from_row(row) -> PerformanceRecord:
    return PerformanceRecord(
        id=row["id"],
        production_id=row["production_id"],
        account_id=row["account_id"],
        exposure=row["exposure"],
        plays=row["plays"],
        completion_rate=row["completion_rate"],
        interactions=row["interactions"],
        negative=row["negative"],
        review_status=ReviewStatus(row["review_status"]),
        review_note=row["review_note"],
        recorded_at=row["recorded_at"],
        created_at=row["created_at"],
    )


def _suggestion_row(sug: RefluxSuggestion) -> tuple:
    return (
        sug.id,
        sug.kind.value,
        sug.text,
        sug.basis,
        sug.impact,
        sug.status.value,
        sug.created_at,
        sug.decided_at,
    )


def _suggestion_from_row(row) -> RefluxSuggestion:
    return RefluxSuggestion(
        id=row["id"],
        kind=SuggestionKind(row["kind"]),
        text=row["text"],
        basis=row["basis"],
        impact=row["impact"],
        status=SuggestionStatus(row["status"]),
        created_at=row["created_at"],
        decided_at=row["decided_at"],
    )


class RefluxRecordDao:
    """reflux_records 表的存取。production_id 唯一（与成品 1:1），重复回填 upsert。"""

    # 冲突时更新表现指标与审核状态、刷新 recorded_at，保留首次回填的 id/created_at
    _UPSERT_SQL = (
        "INSERT INTO reflux_records"
        " (id, production_id, account_id, exposure, plays, completion_rate,"
        "  interactions, negative, review_status, review_note, recorded_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(production_id) DO UPDATE SET"
        "  account_id = excluded.account_id,"
        "  exposure = excluded.exposure,"
        "  plays = excluded.plays,"
        "  completion_rate = excluded.completion_rate,"
        "  interactions = excluded.interactions,"
        "  negative = excluded.negative,"
        "  review_status = excluded.review_status,"
        "  review_note = excluded.review_note,"
        "  recorded_at = excluded.recorded_at"
    )

    def __init__(self, db: DB) -> None:
        self._db = db

    def upsert(self, record: PerformanceRecord) -> None:
        self._db.run(self._UPSERT_SQL, _record_row(record))

    def get_by_production(self, production_id: str) -> PerformanceRecord | None:
        rows = self._db.query(
            "SELECT * FROM reflux_records WHERE production_id = ?", (production_id,)
        )
        return _record_from_row(rows[0]) if rows else None

    def list(self, limit: int | None = None) -> list[PerformanceRecord]:
        """按回填时间倒序返回表现记录。"""
        sql = f"SELECT * FROM reflux_records {_RECORD_SORT_SQL}"
        params: list = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [_record_from_row(r) for r in self._db.query(sql, tuple(params))]


class RefluxSuggestionDao:
    """reflux_suggestions 表的存取。analyze 重建 pending，已决策项保留作历史。"""

    _INSERT_SQL = (
        "INSERT INTO reflux_suggestions"
        " (id, kind, text, basis, impact, status, created_at, decided_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )

    def __init__(self, db: DB) -> None:
        self._db = db

    def insert(self, sug: RefluxSuggestion) -> None:
        self._db.run(self._INSERT_SQL, _suggestion_row(sug))

    def insert_with(self, conn, sug: RefluxSuggestion) -> None:
        """在外部事务连接上写入（db.transaction 内使用，勿与 run 混用）。"""
        conn.execute(self._INSERT_SQL, _suggestion_row(sug))

    def get(self, sug_id: str) -> RefluxSuggestion | None:
        rows = self._db.query("SELECT * FROM reflux_suggestions WHERE id = ?", (sug_id,))
        return _suggestion_from_row(rows[0]) if rows else None

    def list(
        self, status: SuggestionStatus | None = None, limit: int | None = None
    ) -> list[RefluxSuggestion]:
        """按创建时间倒序返回建议，可按状态过滤。"""
        sql = "SELECT * FROM reflux_suggestions"
        params: list = []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status.value)
        sql += f" {_SORT_SQL}"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [_suggestion_from_row(r) for r in self._db.query(sql, tuple(params))]

    def delete_pending_with(self, conn) -> None:
        """在外部事务连接上清空待确认建议（analyze 重建使用，已决策项不受影响）。"""
        conn.execute("DELETE FROM reflux_suggestions WHERE status = 'pending'")

    def update_status(
        self, sug_id: str, status: SuggestionStatus, decided_at: str | None = None
    ) -> None:
        """更新状态；decided_at 传 None 时保留原值（回滚回到待确认不清决策时间）。"""
        if decided_at is None:
            self._db.run(
                "UPDATE reflux_suggestions SET status = ? WHERE id = ?",
                (status.value, sug_id),
            )
        else:
            self._db.run(
                "UPDATE reflux_suggestions SET status = ?, decided_at = ? WHERE id = ?",
                (status.value, decided_at, sug_id),
            )
