"""账号表数据访问对象。"""

from app.daos.db import DB
from app.models import Account, AccountRole, AccountStatus, PublishAdapterKind, PublishChannel

_SORT_SQL = "ORDER BY created_at ASC, id ASC"


def _to_row(a: Account) -> tuple:
    return (
        a.id,
        a.name,
        a.vertical,
        a.role.value,
        a.daily_quota,
        a.publish_window_start,
        a.publish_window_end,
        a.status.value,
        a.channel.value,
        a.adapter.value,
        int(a.auto_publish),
        a.profile_dir,
        a.created_at,
    )


def _from_row(row) -> Account:
    return Account(
        id=row["id"],
        name=row["name"],
        vertical=row["vertical"],
        role=AccountRole(row["role"]),
        daily_quota=row["daily_quota"],
        publish_window_start=row["publish_window_start"],
        publish_window_end=row["publish_window_end"],
        status=AccountStatus(row["status"]),
        channel=PublishChannel(row["channel"]),
        adapter=PublishAdapterKind(row["adapter"]),
        auto_publish=bool(row["auto_publish"]),
        profile_dir=row["profile_dir"],
        created_at=row["created_at"],
    )


class AccountDao:
    """accounts 表的存取。"""

    _UPSERT_SQL = (
        "INSERT OR REPLACE INTO accounts"
        " (id, name, vertical, role, daily_quota, publish_window_start,"
        "  publish_window_end, status, channel, adapter, auto_publish,"
        "  profile_dir, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    def __init__(self, db: DB) -> None:
        self._db = db

    def upsert(self, account: Account) -> None:
        self._db.run(self._UPSERT_SQL, _to_row(account))

    def get(self, account_id: str) -> Account | None:
        rows = self._db.query("SELECT * FROM accounts WHERE id = ?", (account_id,))
        return _from_row(rows[0]) if rows else None

    def list(self, status: AccountStatus | None = None) -> list[Account]:
        """按配置时间升序返回账号（分配时先配置者优先），可按状态过滤。"""
        sql = "SELECT * FROM accounts"
        params: list = []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status.value)
        sql += f" {_SORT_SQL}"
        return [_from_row(r) for r in self._db.query(sql, tuple(params))]

    def delete(self, account_id: str) -> bool:
        """删除账号，返回是否存在过。"""
        found = self.get(account_id) is not None
        if found:
            self._db.run("DELETE FROM accounts WHERE id = ?", (account_id,))
        return found
