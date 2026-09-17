"""重生产编排测试：原地覆盖、守卫链、队列状态阻塞、幂等与身份保持。"""

import pytest

from app.daos import DB, EventDao, MediaAssetDao, ProductionDao, PublishQueueDao
from app.models import (
    AuthStatus,
    Event,
    EventStatus,
    MediaAsset,
    MediaType,
    PublishQueueItem,
    PublishStatus,
    QualityStatus,
    SourceType,
    TimelineEntry,
)
from app.pipeline.producer import (
    ProducerError,
    produce_for_event,
    reproduce_for_production,
)


@pytest.fixture()
def db(tmp_path) -> DB:
    d = DB(tmp_path / "reproduce.db")
    d.migrate()
    return d


def _timeline(n: int = 2) -> list[TimelineEntry]:
    return [
        TimelineEntry(ts=f"2026-09-15T0{i}:00:00+00:00", title=f"信号{i}", heat=80.0)
        for i in range(n)
    ]


def _asset(event_id: str, info_density: float = 70.0) -> MediaAsset:
    return MediaAsset(
        event_id=event_id,
        type=MediaType.IMAGE,
        source_type=SourceType.A,
        auth_status=AuthStatus.CLEARED,
        attribution="来源：合作媒体",
        info_density=info_density,
    )


def _seed_produced(db: DB, n_assets: int = 2) -> tuple[Event, object]:
    """建 READY 事件 + usable 图片素材，生产并返回事件与成品。"""
    ev = Event(title="某地突发山火，救援进行中", timeline=_timeline())
    EventDao(db).upsert(ev)
    for i in range(n_assets):
        MediaAssetDao(db).insert(_asset(ev.id, info_density=70.0 + 10.0 * i))
    prod = produce_for_event(db, ev.id)
    return ev, prod


# ---- 核心场景：素材补录后 HELD → QUALIFIED，原地覆盖 ----

def test_reproduce_backfill_turns_held_into_qualified(db) -> None:
    ev = Event(title="某地突发山火，救援进行中", timeline=_timeline())
    EventDao(db).upsert(ev)
    MediaAssetDao(db).insert(_asset(ev.id, info_density=30.0))
    MediaAssetDao(db).insert(_asset(ev.id, info_density=40.0))
    prod = produce_for_event(db, ev.id)
    assert prod.quality_status == QualityStatus.HELD

    late = _asset(ev.id, info_density=90.0)  # 晚到高密度素材
    MediaAssetDao(db).insert(late)

    updated = reproduce_for_production(db, prod.id)

    assert updated.id == prod.id  # 原地覆盖，成品行不变
    assert updated.event_id == ev.id
    assert updated.quality_status == QualityStatus.QUALIFIED
    assert updated.quality_score > prod.quality_score
    assert len(updated.asset_ids) == 3
    assert updated.cover_asset_id == late.id  # 封面取最高密度
    assert EventDao(db).get(ev.id).status == EventStatus.PRODUCED  # 事件状态不动
    assert ProductionDao(db).get(prod.id) == updated  # 落库一致


# ---- 身份字段不回写 ----

def test_reproduce_preserves_identity_fields(db) -> None:
    ev, prod = _seed_produced(db)
    with db.transaction() as conn:
        ProductionDao(db).update_account_with(conn, prod.id, "acc-sentinel")

    updated = reproduce_for_production(db, prod.id)

    assert updated.id == prod.id
    assert updated.event_id == prod.event_id
    assert updated.account_id == "acc-sentinel"
    assert updated.vertical == prod.vertical
    assert updated.created_at == prod.created_at


# ---- 守卫：成品不存在 ----

def test_reproduce_missing_production_not_found(db) -> None:
    with pytest.raises(ProducerError) as exc_info:
        reproduce_for_production(db, "missing")
    assert exc_info.value.kind == "not_found"


# ---- 守卫：draft_ready / published 阻塞 ----

@pytest.mark.parametrize("status", [PublishStatus.DRAFT_READY, PublishStatus.PUBLISHED])
def test_reproduce_rejects_draft_ready_or_published(db, status) -> None:
    _, prod = _seed_produced(db)
    PublishQueueDao(db).insert(
        PublishQueueItem(account_id="acc-a", production_id=prod.id, status=status)
    )

    with pytest.raises(ProducerError) as exc_info:
        reproduce_for_production(db, prod.id)
    assert exc_info.value.kind == "queue_state"


# ---- 允许：未入队 / pending / failed / skipped ----

@pytest.mark.parametrize(
    "status",
    [None, PublishStatus.PENDING, PublishStatus.FAILED, PublishStatus.SKIPPED],
)
def test_reproduce_allowed_when_not_blocked(db, status) -> None:
    _, prod = _seed_produced(db)
    if status is not None:
        PublishQueueDao(db).insert(
            PublishQueueItem(account_id="acc-a", production_id=prod.id, status=status)
        )

    updated = reproduce_for_production(db, prod.id)

    assert updated.id == prod.id


# ---- 守卫：形态判定 DEFER ----

def test_reproduce_rejects_defer(db) -> None:
    ev, prod = _seed_produced(db)
    victim = MediaAssetDao(db).list_by_event(ev.id)[0]
    # 覆盖其中一张为不可用素材，使 usable 图像 < 2 → DEFER
    MediaAssetDao(db).insert(
        MediaAsset(
            id=victim.id,
            event_id=ev.id,
            type=MediaType.IMAGE,
            source_type=SourceType.A,
            auth_status=AuthStatus.PENDING,
            attribution="",
            info_density=70.0,
        )
    )

    with pytest.raises(ProducerError) as exc_info:
        reproduce_for_production(db, prod.id)
    assert exc_info.value.kind == "not_ready"


# ---- 幂等：重复重产可再跑 ----

def test_reproduce_idempotent(db) -> None:
    _, prod = _seed_produced(db)

    first = reproduce_for_production(db, prod.id)
    second = reproduce_for_production(db, prod.id)

    assert first == second
    assert ProductionDao(db).get(prod.id) == second