"""账号分配与入队测试：分配纯函数、单成品入队、批量容错与配额即时生效。"""

import pytest

from app.daos import DB, AccountDao, ProductionDao, PublishQueueDao
from app.models import (
    Account,
    AccountRole,
    AccountStatus,
    Production,
    ProductionType,
    PublishQueueItem,
    PublishStatus,
    QualityStatus,
)
from app.pipeline.allocator import (
    AllocationError,
    allocate_for_production,
    enqueue_all,
    pick_account,
)


@pytest.fixture()
def db(tmp_path) -> DB:
    d = DB(tmp_path / "alloc.db")
    d.migrate()
    return d


@pytest.fixture()
def account_dao(db) -> AccountDao:
    return AccountDao(db)


@pytest.fixture()
def production_dao(db) -> ProductionDao:
    return ProductionDao(db)


@pytest.fixture()
def queue_dao(db) -> PublishQueueDao:
    return PublishQueueDao(db)


def _account(account_id: str = "acc1", **kw) -> Account:
    acc = Account(
        id=account_id,
        name=kw.pop("name", account_id),
        vertical=kw.pop("vertical", ""),
        role=kw.pop("role", AccountRole.PRIMARY),
        daily_quota=kw.pop("daily_quota", 1),
        status=kw.pop("status", AccountStatus.ACTIVE),
    )
    acc.created_at = kw.pop("created_at", "2026-09-16T00:00:00+00:00")
    return acc


def _prod(prod_id: str = "p1", **kw) -> Production:
    p = Production(
        id=prod_id,
        event_id=kw.pop("event_id", f"ev-{prod_id}"),
        vertical=kw.pop("vertical", ""),
        production_type=kw.pop("production_type", ProductionType.IMAGE_SLIDESHOW),
        title=kw.pop("title", "多图直击：测试事件"),
        quality_score=kw.pop("quality_score", 80.0),
        quality_status=kw.pop("quality_status", QualityStatus.QUALIFIED),
    )
    p.created_at = kw.pop("created_at", "2026-09-16T10:00:00+00:00")
    return p


def _queue_entry_for(production_id: str) -> PublishQueueItem:
    item = PublishQueueItem(account_id="acc1", production_id=production_id)
    item.created_at = "2026-09-16T00:00:00+00:00"
    return item


# ---- pick_account 纯函数 ----

def test_pick_prefers_exact_vertical_match_over_primary() -> None:
    prod = _prod(vertical="科技")
    primary = _account("acc_main", role=AccountRole.PRIMARY)
    exp_match = _account("acc_exp", role=AccountRole.EXPERIMENT, vertical="科技")

    picked = pick_account(prod, [primary, exp_match], {})

    assert picked is exp_match  # 垂类精确匹配 > 通用主域


def test_pick_primary_before_experiment() -> None:
    prod = _prod(vertical="科技")  # 无账号垂类匹配
    primary = _account("acc_main", role=AccountRole.PRIMARY)
    experiment = _account("acc_exp", role=AccountRole.EXPERIMENT)

    assert pick_account(prod, [primary, experiment], {}) is primary


def test_pick_general_production_goes_to_primary() -> None:
    prod = _prod()  # vertical 为空（通用），精确匹配层级不触发
    primary = _account("acc_main")
    experiment = _account("acc_exp", role=AccountRole.EXPERIMENT)

    assert pick_account(prod, [primary, experiment], {}) is primary


def test_pick_skips_paused_account() -> None:
    prod = _prod()
    paused = _account("acc_paused", status=AccountStatus.INACTIVE)

    assert pick_account(prod, [paused], {}) is None


def test_pick_skips_test_domain_even_with_vertical_match() -> None:
    prod = _prod(vertical="科技")
    tester = _account("acc_test", role=AccountRole.TEST, vertical="科技")

    assert pick_account(prod, [tester], {}) is None  # 测试域不参与自动分配


def test_pick_respects_daily_quota() -> None:
    prod = _prod()
    full = _account("acc_full", daily_quota=1)
    zero = _account("acc_zero", daily_quota=0)
    spare = _account("acc_spare", daily_quota=3)

    assert pick_account(prod, [full], {"acc_full": 1}) is None  # 配额已满
    assert pick_account(prod, [zero], {}) is None  # quota=0 不参与
    assert pick_account(prod, [full, spare], {"acc_full": 1}) is spare


def test_pick_stable_order_within_tier() -> None:
    prod = _prod()
    late = _account("acc_late", created_at="2026-09-16T00:00:00+00:00")
    early = _account("acc_early", created_at="2026-09-15T00:00:00+00:00")

    assert pick_account(prod, [late, early], {}) is early  # 同层先配置者优先


# ---- allocate_for_production ----

def test_allocate_enqueues_and_backfills_account(
    db, account_dao, production_dao, queue_dao
) -> None:
    acc = _account()
    prod = _prod()
    account_dao.upsert(acc)
    production_dao.insert(prod)

    item = allocate_for_production(db, prod.id)

    assert item.account_id == acc.id
    assert item.production_id == prod.id
    assert item.status == PublishStatus.PENDING
    assert queue_dao.get_by_production(prod.id) == item
    assert production_dao.get(prod.id).account_id == acc.id  # 跨表回填


def test_allocate_missing_production_raises_not_found(db) -> None:
    with pytest.raises(AllocationError) as exc_info:
        allocate_for_production(db, "nope")
    assert exc_info.value.kind == "not_found"


@pytest.mark.parametrize("status", [QualityStatus.HELD, QualityStatus.BLOCKED])
def test_allocate_rejects_non_qualified(db, production_dao, status) -> None:
    production_dao.insert(_prod(quality_status=status))

    with pytest.raises(AllocationError) as exc_info:
        allocate_for_production(db, "p1")
    assert exc_info.value.kind == "not_qualified"


def test_allocate_rejects_already_enqueued(db, account_dao, production_dao, queue_dao) -> None:
    account_dao.upsert(_account())
    production_dao.insert(_prod())

    allocate_for_production(db, "p1")
    with pytest.raises(AllocationError) as exc_info:
        allocate_for_production(db, "p1")
    assert exc_info.value.kind == "already_enqueued"


def test_allocate_rejects_when_no_account(db, account_dao, production_dao) -> None:
    production_dao.insert(_prod())

    with pytest.raises(AllocationError) as exc_info:  # 无任何账号
        allocate_for_production(db, "p1")
    assert exc_info.value.kind == "no_account"

    account_dao.upsert(_account(daily_quota=0))  # 仅 quota=0 账号同样无候选
    with pytest.raises(AllocationError):
        allocate_for_production(db, "p1")


# ---- enqueue_all ----

def test_enqueue_all_orders_by_score_and_quota_takes_effect(
    db, account_dao, production_dao
) -> None:
    account_dao.upsert(_account(daily_quota=2))
    production_dao.insert(_prod("p_low", quality_score=70.0))
    production_dao.insert(_prod("p_high", quality_score=95.0))

    report = enqueue_all(db)

    assert [i.production_id for i in report.enqueued] == ["p_high", "p_low"]  # 质量分降序
    assert report.skipped == []


def test_enqueue_all_skips_when_quota_exhausted(db, account_dao, production_dao) -> None:
    account_dao.upsert(_account(daily_quota=1))
    production_dao.insert(_prod("p_first", quality_score=95.0))
    production_dao.insert(_prod("p_second", quality_score=80.0))

    report = enqueue_all(db)

    assert [i.production_id for i in report.enqueued] == ["p_first"]  # 优质内容优先占配额
    assert [(s.production_id, s.reason) for s in report.skipped] == [("p_second", "no_account")]


def test_enqueue_all_ignores_non_qualified_and_continues(
    db, account_dao, production_dao, queue_dao
) -> None:
    account_dao.upsert(_account(daily_quota=5))
    production_dao.insert(_prod("p_ok", quality_score=90.0))
    production_dao.insert(_prod("p_held", quality_status=QualityStatus.HELD))
    production_dao.insert(_prod("p_blocked", quality_status=QualityStatus.BLOCKED))
    queue_dao.insert(_queue_entry_for("p_dup"))  # 已有队列项 → already_enqueued
    production_dao.insert(_prod("p_dup", quality_score=85.0))

    report = enqueue_all(db)

    assert [i.production_id for i in report.enqueued] == ["p_ok"]
    assert [(s.production_id, s.reason) for s in report.skipped] == [("p_dup", "already_enqueued")]


def test_enqueue_all_empty_without_qualified(db) -> None:
    report = enqueue_all(db)

    assert report.enqueued == [] and report.skipped == []
