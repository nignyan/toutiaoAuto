"""账号自动分配与待发布队列入队（规格 §5）：QUALIFIED 成品 → 账号 → 队列。

分配纯函数 pick_account：资格过滤（活跃 + 非测试域 + 当日配额未满）后按
「垂类精确匹配 > 通用主域 > 实验域」选号；队列项落库与 production.account_id
回填走 db.transaction 保持原子；批量入队与 D6/D9 容错同构。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.daos import DB, AccountDao, ProductionDao, PublishQueueDao
from app.models import (
    Account,
    AccountRole,
    AccountStatus,
    Production,
    PublishQueueItem,
    QualityStatus,
)

# 测试域不参与自动分配（规格 D10 §2）；其余按产品文档优先级排层级
_ROLE_TIER = {AccountRole.PRIMARY: 1, AccountRole.EXPERIMENT: 2}


class AllocationError(Exception):
    """分配拒绝：kind 为 not_found / not_qualified / already_enqueued / no_account，
    API 层映射 404 / 409。"""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        super().__init__(message)


@dataclass(frozen=True)
class EnqueueSkip:
    """批量入队中被跳过的成品与原因。"""

    production_id: str
    reason: str


@dataclass(frozen=True)
class EnqueueAllReport:
    """批量入队结果：单成品失败不影响其余（与 D6/D9 容错同构）。"""

    enqueued: list[PublishQueueItem] = field(default_factory=list)
    skipped: list[EnqueueSkip] = field(default_factory=list)


def today_prefix(now: datetime | None = None) -> str:
    """当日 UTC 日期前缀（配额按 UTC 日切分，规格 D10 §2）。"""
    return (now if now is not None else datetime.now(timezone.utc)).date().isoformat()


def pick_account(
    production: Production, accounts: list[Account], used_quota: dict[str, int]
) -> Account | None:
    """分配纯函数：无合格候选返回 None。

    资格（同时满足）：活跃、非测试域、当日已用配额 < daily_quota（quota=0 不参与）；
    层级：垂类精确匹配(0) > 通用主域(1) > 实验域(2)；同层先配置者优先（created_at + id）。
    """
    eligible = [
        a
        for a in accounts
        if a.status == AccountStatus.ACTIVE
        and a.role != AccountRole.TEST
        and a.daily_quota > used_quota.get(a.id, 0)
    ]
    if not eligible:
        return None

    def tier(a: Account) -> tuple:
        exact = production.vertical != "" and a.vertical == production.vertical
        return (0 if exact else _ROLE_TIER[a.role], a.created_at, a.id)

    return min(eligible, key=tier)


def allocate_for_production(db: DB, production_id: str) -> PublishQueueItem:
    """对单个 QUALIFIED 成品执行账号分配并入队；回填 production.account_id。"""
    prod = ProductionDao(db).get(production_id)
    if prod is None:
        raise AllocationError("not_found", f"成品 {production_id} 不存在")
    if prod.quality_status != QualityStatus.QUALIFIED:
        raise AllocationError(
            "not_qualified",
            f"成品 {production_id} 质检状态为 {prod.quality_status.value}，仅 QUALIFIED 可入队",
        )
    queue_dao = PublishQueueDao(db)
    if queue_dao.get_by_production(production_id) is not None:
        raise AllocationError("already_enqueued", f"成品 {production_id} 已在待发布队列")

    used = queue_dao.count_by_account_on(today_prefix())  # 跳过/失败不释放配额
    account = pick_account(prod, AccountDao(db).list(), used)
    if account is None:
        raise AllocationError(
            "no_account", f"成品 {production_id} 无可用账号（需活跃且当日配额未满）"
        )

    item = PublishQueueItem(account_id=account.id, production_id=prod.id)
    prod.account_id = account.id
    with db.transaction() as conn:  # 入队与账号回填跨表原子
        queue_dao.insert_with(conn, item)
        ProductionDao(db).update_account_with(conn, prod.id, account.id)
    return item


def enqueue_all(db: DB) -> EnqueueAllReport:
    """批量入队全部未入队的 QUALIFIED 成品（质量分降序），失败进 skipped 不中断。"""
    enqueued: list[PublishQueueItem] = []
    skipped: list[EnqueueSkip] = []
    prods = sorted(
        ProductionDao(db).list(status=QualityStatus.QUALIFIED),
        key=lambda p: (-p.quality_score, p.created_at),
    )
    for prod in prods:
        try:
            enqueued.append(allocate_for_production(db, prod.id))
        except Exception as exc:  # noqa: BLE001 单成品容错
            reason = exc.kind if isinstance(exc, AllocationError) else f"error: {exc}"
            skipped.append(EnqueueSkip(production_id=prod.id, reason=reason))
    return EnqueueAllReport(enqueued=enqueued, skipped=skipped)
