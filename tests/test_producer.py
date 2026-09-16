"""生产编排测试：端到端落库、状态机拒绝、DEFER 防御、批量容错。"""

import pytest

from app.daos import DB, EventDao, MediaAssetDao, ProductionDao
from app.models import (
    AuthStatus,
    Event,
    EventStatus,
    MediaAsset,
    MediaType,
    ProductionType,
    QualityStatus,
    SourceType,
    TimelineEntry,
)
from app.pipeline.composer import TemplateComposer
from app.pipeline.producer import ProducerError, produce_all, produce_for_event


@pytest.fixture()
def db(tmp_path) -> DB:
    d = DB(tmp_path / "producer.db")
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


def _seed_ready(db: DB, n_assets: int = 2, **event_kw) -> Event:
    """建一个 READY 事件并插入 usable 图片素材（默认密度 70/80 → 规则 2 图集）。"""
    ev = Event(title="某地突发山火，救援进行中", timeline=_timeline(), **event_kw)
    EventDao(db).upsert(ev)
    for i in range(n_assets):
        MediaAssetDao(db).insert(_asset(ev.id, info_density=70.0 + 10.0 * i))
    return ev


# ---- 端到端 ----

def test_produce_end_to_end(db) -> None:
    ev = _seed_ready(db)  # 密度 70/80 → 均值 75

    prod = produce_for_event(db, ev.id)

    assert prod.production_type == ProductionType.IMAGE_SLIDESHOW
    assert prod.title == "多图直击：某地突发山火，救援进行中"
    assert prod.rule == "规则2"
    assert prod.composer == "template"
    assert prod.body.startswith("【事件】某地突发山火，救援进行中")
    assert len(prod.asset_ids) == 2
    assert prod.cover_asset_id == prod.asset_ids[0]  # 封面取信息密度最高者
    # 50 + 75×0.25 + 5（2 素材）+ 5（2 时间线）+ 5（标题 12 字）= 83.75
    assert prod.quality_score == 83.75
    assert prod.quality_status == QualityStatus.QUALIFIED
    assert prod.vetoes == []
    assert len(prod.checks) == 4

    # 成品落库且事件状态转 PRODUCED
    assert ProductionDao(db).get_by_event(ev.id) == prod
    assert EventDao(db).get(ev.id).status == EventStatus.PRODUCED


def test_produce_orders_images_by_density_desc(db) -> None:
    ev = _seed_ready(db, n_assets=3)
    prod = produce_for_event(db, ev.id)

    assets = {a.id: a for a in MediaAssetDao(db).list_by_event(ev.id)}
    densities = [assets[i].info_density for i in prod.asset_ids]
    assert densities == [90.0, 80.0, 70.0]  # 密度降序
    assert prod.cover_asset_id == prod.asset_ids[0]


# ---- 状态机拒绝 ----

def test_produce_missing_event_not_found(db) -> None:
    with pytest.raises(ProducerError) as exc_info:
        produce_for_event(db, "missing")
    assert exc_info.value.kind == "not_found"


def test_produce_rejects_deferred_event(db) -> None:
    ev = _seed_ready(db, status=EventStatus.DEFERRED)
    with pytest.raises(ProducerError) as exc_info:
        produce_for_event(db, ev.id)
    assert exc_info.value.kind == "not_ready"


def test_produce_rejects_repeat_production(db) -> None:
    ev = _seed_ready(db)
    produce_for_event(db, ev.id)

    with pytest.raises(ProducerError) as exc_info:  # 已 PRODUCED → 409 语义
        produce_for_event(db, ev.id)
    assert exc_info.value.kind == "not_ready"
    assert len(ProductionDao(db).list()) == 1  # 不产生重复成品


def test_produce_defer_defensive_path(db) -> None:
    """READY 但素材不足以判定形态（与状态矛盾）→ not_ready，不落库。"""
    ev = _seed_ready(db, n_assets=1)  # 单图 → 规则 4 DEFER

    with pytest.raises(ProducerError) as exc_info:
        produce_for_event(db, ev.id)
    assert exc_info.value.kind == "not_ready"
    assert ProductionDao(db).get_by_event(ev.id) is None
    assert EventDao(db).get(ev.id).status == EventStatus.READY


# ---- blocked / held 成品语义 ----

def test_produce_blocked_production_still_recorded(db) -> None:
    ev = Event(title="某地突发山火，救援进行中", timeline=[])  # timeline 空 → 否决
    EventDao(db).upsert(ev)
    MediaAssetDao(db).insert(_asset(ev.id))
    MediaAssetDao(db).insert(_asset(ev.id, info_density=80.0))

    prod = produce_for_event(db, ev.id)

    assert prod.quality_status == QualityStatus.BLOCKED
    assert prod.vetoes == ["事件来源缺失"]
    # 质检拦截不回滚生产：成品留档，事件转为 PRODUCED
    assert ProductionDao(db).get_by_event(ev.id).quality_status == QualityStatus.BLOCKED
    assert EventDao(db).get(ev.id).status == EventStatus.PRODUCED


def test_produce_held_production_when_score_below_75(db) -> None:
    # 2 素材密度 30/40 → 均值 35 → 50+8.75+5+5+5 = 73.75 → HELD
    ev = _seed_ready(db, n_assets=0)
    MediaAssetDao(db).insert(_asset(ev.id, info_density=30.0))
    MediaAssetDao(db).insert(_asset(ev.id, info_density=40.0))

    prod = produce_for_event(db, ev.id)
    assert prod.quality_score == 73.75
    assert prod.quality_status == QualityStatus.HELD
    assert prod.vetoes == []


# ---- composer 替换与批量容错 ----

class _PickyComposer:
    """对特定事件抛错的替身，用于验证单事件失败不影响其余。"""

    name = "picky"

    def compose(self, event, assets, decision):
        if "炸弹" in event.title:
            raise RuntimeError("composer 炸了")
        return TemplateComposer().compose(event, assets, decision)


def test_produce_uses_custom_composer(db) -> None:
    ev = _seed_ready(db)
    prod = produce_for_event(db, ev.id, _PickyComposer())
    assert prod.composer == "picky"


def test_produce_all_mixed_with_fault_tolerance(db) -> None:
    ev_ok = _seed_ready(db)
    ev_bomb = _seed_ready(db)
    ev_bomb.title = "某地炸弹警报解除"
    EventDao(db).upsert(ev_bomb)
    for i in range(2):
        MediaAssetDao(db).insert(_asset(ev_bomb.id, info_density=70.0 + 10.0 * i))
    ev_defer = _seed_ready(db, n_assets=1)  # READY 但形态 DEFER → skipped

    report = produce_all(db, _PickyComposer())

    produced_ids = {p.event_id for p in report.produced}
    assert produced_ids == {ev_ok.id}  # 炸弹事件失败，其余正常
    skip_map = {s.event_id: s.reason for s in report.skipped}
    assert skip_map[ev_bomb.id] == "error: composer 炸了"
    assert skip_map[ev_defer.id] == "not_ready"
    # 失败事件保持 READY，成功事件转 PRODUCED
    assert EventDao(db).get(ev_bomb.id).status == EventStatus.READY
    assert EventDao(db).get(ev_ok.id).status == EventStatus.PRODUCED


def test_produce_all_empty_when_no_ready_events(db) -> None:
    report = produce_all(db)
    assert report.produced == []
    assert report.skipped == []
