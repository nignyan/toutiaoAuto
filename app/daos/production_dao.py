"""成品表数据访问对象。"""

import json

from app.daos.db import DB
from app.models import Production, ProductionType, QualityStatus

_SORT_SQL = "ORDER BY created_at DESC"


def _to_row(prod: Production) -> tuple:
    return (
        prod.id,
        prod.event_id,
        prod.production_type.value,
        json.dumps(prod.asset_ids, ensure_ascii=False),
        prod.title,
        prod.body,
        prod.cover_asset_id,
        prod.rule,
        prod.composer,
        prod.quality_score,
        prod.quality_status.value,
        json.dumps(prod.checks, ensure_ascii=False),
        json.dumps(prod.vetoes, ensure_ascii=False),
        prod.account_id,
        prod.created_at,
    )


def _from_row(row) -> Production:
    return Production(
        id=row["id"],
        event_id=row["event_id"],
        production_type=ProductionType(row["production_type"]),
        asset_ids=json.loads(row["asset_ids_json"]),
        title=row["title"],
        body=row["body"],
        cover_asset_id=row["cover_asset_id"],
        rule=row["rule"],
        composer=row["composer"],
        quality_score=row["quality_score"],
        quality_status=QualityStatus(row["quality_status"]),
        checks=json.loads(row["checks_json"]),
        vetoes=json.loads(row["vetoes_json"]),
        account_id=row["account_id"],
        created_at=row["created_at"],
    )


class ProductionDao:
    """production 表的存取。"""

    _INSERT_SQL = (
        "INSERT OR REPLACE INTO production"
        " (id, event_id, production_type, asset_ids_json, title, body,"
        "  cover_asset_id, rule, composer, quality_score, quality_status,"
        "  checks_json, vetoes_json, account_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    def __init__(self, db: DB) -> None:
        self._db = db

    def insert(self, prod: Production) -> None:
        self._db.run(self._INSERT_SQL, _to_row(prod))

    def insert_with(self, conn, prod: Production) -> None:
        """在外部事务连接上写入（db.transaction 内使用，勿与 run 混用）。"""
        conn.execute(self._INSERT_SQL, _to_row(prod))

    def get_by_event(self, event_id: str) -> Production | None:
        rows = self._db.query(
            f"SELECT * FROM production WHERE event_id = ? {_SORT_SQL}", (event_id,)
        )
        return _from_row(rows[0]) if rows else None

    def list(
        self, status: QualityStatus | None = None, limit: int | None = None
    ) -> list[Production]:
        """按创建时间倒序返回成品，可按质检状态过滤。"""
        sql = "SELECT * FROM production"
        params: list = []
        if status is not None:
            sql += " WHERE quality_status = ?"
            params.append(status.value)
        sql += f" {_SORT_SQL}"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [_from_row(r) for r in self._db.query(sql, tuple(params))]
