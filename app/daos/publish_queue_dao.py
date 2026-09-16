"""发布队列表数据访问对象。"""

from app.daos.db import DB
from app.models import PublishQueueItem, PublishStatus

# 队列按入队顺序投递（FIFO）
_SORT_SQL = "ORDER BY created_at ASC, id ASC"


def _to_row(item: PublishQueueItem) -> tuple:
    return (
        item.id,
        item.account_id,
        item.production_id,
        item.status.value,
        item.scheduled_for,
        item.publish_result,
        item.created_at,
    )


def _from_row(row) -> PublishQueueItem:
    return PublishQueueItem(
        id=row["id"],
        account_id=row["account_id"],
        production_id=row["production_id"],
        status=PublishStatus(row["status"]),
        scheduled_for=row["scheduled_for"],
        publish_result=row["publish_result"],
        created_at=row["created_at"],
    )


class PublishQueueDao:
    """publish_queue 表的存取。production_id 唯一（与成品 1:1）。"""

    # 重复 production_id 由唯一索引拦截（不静默替换）
    _INSERT_SQL = (
        "INSERT INTO publish_queue"
        " (id, account_id, production_id, status, scheduled_for, publish_result, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
    )

    def __init__(self, db: DB) -> None:
        self._db = db

    def insert(self, item: PublishQueueItem) -> None:
        self._db.run(self._INSERT_SQL, _to_row(item))

    def insert_with(self, conn, item: PublishQueueItem) -> None:
        """在外部事务连接上写入（db.transaction 内使用，勿与 run 混用）。"""
        conn.execute(self._INSERT_SQL, _to_row(item))

    def get(self, item_id: str) -> PublishQueueItem | None:
        rows = self._db.query("SELECT * FROM publish_queue WHERE id = ?", (item_id,))
        return _from_row(rows[0]) if rows else None

    def get_by_production(self, production_id: str) -> PublishQueueItem | None:
        rows = self._db.query(
            "SELECT * FROM publish_queue WHERE production_id = ?", (production_id,)
        )
        return _from_row(rows[0]) if rows else None

    def list(
        self,
        account_id: str | None = None,
        status: PublishStatus | None = None,
        limit: int | None = None,
    ) -> list[PublishQueueItem]:
        """按入队顺序返回队列项，可按账号/状态过滤。"""
        sql = "SELECT * FROM publish_queue"
        params: list = []
        conditions: list[str] = []
        if account_id is not None:
            conditions.append("account_id = ?")
            params.append(account_id)
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += f" {_SORT_SQL}"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [_from_row(r) for r in self._db.query(sql, tuple(params))]

    def count_by_account_on(self, date_prefix: str) -> dict[str, int]:
        """指定日期（UTC created_at 前缀）各账号的队列条目数，用于当日配额核算。"""
        rows = self._db.query(
            "SELECT account_id, COUNT(*) AS n FROM publish_queue"
            " WHERE created_at LIKE ? GROUP BY account_id",
            (f"{date_prefix}%",),
        )
        return {r["account_id"]: r["n"] for r in rows}

    def count_for_account(
        self, account_id: str, status: PublishStatus | None = None
    ) -> int:
        """账号的队列条目总数，可按状态过滤（删除保护用）。"""
        sql = "SELECT COUNT(*) AS n FROM publish_queue WHERE account_id = ?"
        params: list = [account_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        rows = self._db.query(sql, tuple(params))
        return int(rows[0]["n"]) if rows else 0
