"""DAO 层测试：建表幂等、事件/素材/成品往返、过滤排序。"""

import pytest

from app.daos import DB, EventDao, MediaAssetDao, ProductionDao
from app.models import (
    AuthStatus,
    Clarity,
    Event,
    EventStatus,
    MediaAsset,
    MediaType,
    Production,
    ProductionType,
    QualityStatus,
    SourceType,
    TimelineEntry,
)


@pytest.fixture()
def db(tmp_path) -> DB:
    d = DB(tmp_path / "test.db")
    d.migrate()
    return d


@pytest.fixture()
def event_dao(db) -> EventDao:
    return EventDao(db)


@pytest.fixture()
def asset_dao(db) -> MediaAssetDao:
    return MediaAssetDao(db)


def _event(score: float = 80.0, status: EventStatus = EventStatus.READY, **kw) -> Event:
    return Event(
        title=kw.pop("title", "某地突发山火，救援进行中"),
        score=score,
        status=status,
        timeline=kw.pop(
            "timeline",
            [TimelineEntry(
                ts="2026-09-15T08:00:00+00:00", title="信号标题", source="weibo_hot", heat=88.0
            )],
        ),
        **kw,
    )


# ---- migrate ----

def test_migrate_idempotent(tmp_path) -> None:
    d = DB(tmp_path / "twice.db")
    d.migrate()
    d.migrate()  # 二次调用不报错


# ---- EventDao ----

def test_event_roundtrip_preserves_all_fields(event_dao) -> None:
    ev = _event()
    event_dao.upsert(ev)

    loaded = event_dao.get(ev.id)
    assert loaded == ev  # 含 timeline / status / created_at 全字段往返一致


def test_event_upsert_replaces_row(event_dao) -> None:
    ev = _event()
    event_dao.upsert(ev)
    ev.score = 99.0
    ev.timeline.append(TimelineEntry(ts="2026-09-15T09:00:00+00:00", title="后续信号"))
    event_dao.upsert(ev)

    rows = event_dao.list_all()
    assert len(rows) == 1
    assert rows[0].score == 99.0
    assert len(rows[0].timeline) == 2


def test_event_get_missing_returns_none(event_dao) -> None:
    assert event_dao.get("nope") is None


def test_event_list_filters_status_and_sorts_by_score(event_dao) -> None:
    event_dao.upsert(_event(score=60, title="事件A"))
    event_dao.upsert(_event(score=90, title="事件B", status=EventStatus.DEFERRED))
    event_dao.upsert(_event(score=75, title="事件C"))

    all_events = event_dao.list_all()
    assert [e.title for e in all_events] == ["事件B", "事件C", "事件A"]

    deferred = event_dao.list_all(status=EventStatus.DEFERRED)
    assert [e.title for e in deferred] == ["事件B"]

    top1 = event_dao.list_all(limit=1)
    assert len(top1) == 1 and top1[0].title == "事件B"


# ---- MediaAssetDao ----

def _asset(event_id: str = "ev1", **kw) -> MediaAsset:
    return MediaAsset(
        event_id=event_id,
        type=kw.pop("type", MediaType.VIDEO),
        source_url="https://example.com/v1",
        source_type=kw.pop("source_type", SourceType.B),
        auth_status=kw.pop("auth_status", AuthStatus.CLEARED),
        auth_evidence="原始发布链接",
        license_business=True,
        attribution="来源：合作媒体",
        clarity=kw.pop("clarity", Clarity.CLEAR),
        info_density=kw.pop("info_density", 82.5),
        duration_s=kw.pop("duration_s", 45.0),
        fingerprint="fp_abc",
        **kw,
    )


def test_asset_roundtrip_preserves_all_fields(asset_dao) -> None:
    a = _asset()
    asset_dao.insert(a)

    assert asset_dao.get(a.id) == a


def test_asset_nullable_fields_roundtrip(asset_dao) -> None:
    a = _asset(clarity=None, info_density=None, duration_s=None)
    asset_dao.insert(a)

    loaded = asset_dao.get(a.id)
    assert loaded.clarity is None
    assert loaded.info_density is None
    assert loaded.duration_s is None


def test_asset_list_by_event(asset_dao) -> None:
    asset_dao.insert(_asset(event_id="ev1"))
    asset_dao.insert(_asset(event_id="ev1", type=MediaType.IMAGE, clarity=None, info_density=None))
    asset_dao.insert(_asset(event_id="ev2"))

    ev1_assets = asset_dao.list_by_event("ev1")
    assert len(ev1_assets) == 2
    assert all(a.event_id == "ev1" for a in ev1_assets)
    assert asset_dao.list_by_event("missing") == []


# ---- ProductionDao ----

@pytest.fixture()
def production_dao(db) -> ProductionDao:
    return ProductionDao(db)


def _production(event_id: str = "ev1", **kw) -> Production:
    return Production(
        event_id=event_id,
        production_type=kw.pop("production_type", ProductionType.IMAGE_SLIDESHOW),
        asset_ids=kw.pop("asset_ids", ["a1", "a2"]),
        title=kw.pop("title", "多图直击：某地突发山火"),
        body=kw.pop("body", "正文第一段……"),
        cover_asset_id=kw.pop("cover_asset_id", "a1"),
        rule=kw.pop("rule", "规则2：无可用视频成片，采用多张图集呈现"),
        composer=kw.pop("composer", "template"),
        checks=kw.pop("checks", ["署名完整", "时间线完整"]),
        vetoes=kw.pop("vetoes", []),
        quality_score=kw.pop("quality_score", 82.5),
        quality_status=kw.pop("quality_status", QualityStatus.QUALIFIED),
        **kw,
    )


def test_production_roundtrip_preserves_all_fields(production_dao) -> None:
    p = _production()
    production_dao.insert(p)

    assert production_dao.get_by_event("ev1") == p


def test_production_list_filters_status_and_orders_by_created(production_dao) -> None:
    p_old = _production(event_id="ev1", title="旧成品", quality_status=QualityStatus.HELD)
    p_old.created_at = "2026-09-15T08:00:00+00:00"
    p_new = _production(event_id="ev2", title="新成品", quality_status=QualityStatus.BLOCKED)
    p_new.created_at = "2026-09-16T08:00:00+00:00"
    production_dao.insert(p_old)
    production_dao.insert(p_new)

    all_prods = production_dao.list()
    assert [p.title for p in all_prods] == ["新成品", "旧成品"]

    blocked = production_dao.list(status=QualityStatus.BLOCKED)
    assert [p.title for p in blocked] == ["新成品"]

    top1 = production_dao.list(limit=1)
    assert len(top1) == 1 and top1[0].title == "新成品"


def test_production_get_by_event_missing_returns_none(production_dao) -> None:
    assert production_dao.get_by_event("nope") is None
