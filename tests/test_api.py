"""应用健康检查与管道 API 测试。"""

import pytest
from fastapi.testclient import TestClient

from app.api.pipeline import get_composer, get_db, get_sources
from app.daos import DB, EventDao, MediaAssetDao
from app.main import app
from app.models import (
    AuthStatus,
    Event,
    EventStatus,
    MediaAsset,
    MediaType,
    SourceType,
    TimelineEntry,
)
from app.pipeline.collector import FixtureSource, RawSignal
from app.pipeline.composer import TemplateComposer

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---- 管道 API ----

@pytest.fixture()
def api(tmp_path):
    db = DB(tmp_path / "api.db")
    db.migrate()
    app.dependency_overrides[get_db] = lambda: db
    yield db
    app.dependency_overrides.clear()


def _override_sources(*sources) -> None:
    app.dependency_overrides[get_sources] = lambda: list(sources)


def _sig(title: str, heat: float = 80.0) -> RawSignal:
    return RawSignal(title=title, heat=heat, source="fixture")


class _BrokenSource:
    name = "broken"

    def fetch(self):
        raise RuntimeError("源挂了")


def test_collect_creates_merges_and_ingests_assets(api) -> None:
    from app.models import AuthStatus, Clarity, MediaAsset, MediaType

    video = MediaAsset(
        type=MediaType.VIDEO, clarity=Clarity.CLEAR, info_density=85.0,
        auth_status=AuthStatus.CLEARED,
    )
    custom = FixtureSource(
        [
            RawSignal(
                title="四川雅安山火", heat=95, source="fixture",
                pending_assets=[video.model_copy(deep=True)],
            ),
            RawSignal(title="雅安山火救援", heat=88, source="fixture"),
        ]
    )
    _override_sources(custom)

    resp = client.post("/pipeline/collect")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["created"]) == 1  # 两条相似信号聚为一个事件
    assert len(body["assignments"]) == 2
    assert body["sources"][0]["ok"] is True

    event_id = body["created"][0]["id"]
    detail = client.get(f"/events/{event_id}")
    assert detail.status_code == 200
    d = detail.json()
    assert len(d["assets"]) == 1  # 新建事件的 pending_assets 已入库
    assert d["decision_format"] == "video"  # 规则 1


def test_collect_tolerates_source_failure(api) -> None:
    _override_sources(_BrokenSource(), FixtureSource([_sig("博物馆预约数字化", 39)]))

    resp = client.post("/pipeline/collect")
    assert resp.status_code == 200
    sources = {s["source"]: s for s in resp.json()["sources"]}
    assert sources["broken"]["ok"] is False
    assert sources["fixture"]["ok"] is True


def test_collect_filters_unknown_source_returns_400(api) -> None:
    _override_sources(FixtureSource([]))
    resp = client.post("/pipeline/collect", json={"sources": ["nope"]})
    assert resp.status_code == 400


def test_collect_merges_into_existing_event_across_batches(api) -> None:
    _override_sources(FixtureSource([_sig("台风梅花登陆", 92)]))
    first = client.post("/pipeline/collect").json()
    assert len(first["created"]) == 1

    _override_sources(FixtureSource([_sig("台风梅花减弱", 66)]))
    second = client.post("/pipeline/collect").json()
    assert second["created"] == []
    assert len(second["updated"]) == 1
    assert second["updated"][0]["id"] == first["created"][0]["id"]
    assert second["updated"][0]["score"] == 92.0  # max 保持
    assert len(second["updated"][0]["timeline"]) == 2


def test_events_list_filter_and_order(api) -> None:
    db = api
    EventDao(db).upsert(Event(title="高分事件", score=90, status=EventStatus.READY))
    EventDao(db).upsert(Event(title="暂缓事件", score=60, status=EventStatus.DEFERRED))

    all_events = client.get("/events").json()
    assert [e["title"] for e in all_events] == ["高分事件", "暂缓事件"]

    deferred = client.get("/events", params={"status": "deferred"}).json()
    assert [e["title"] for e in deferred] == ["暂缓事件"]


def test_event_detail_404(api) -> None:
    assert client.get("/events/missing").status_code == 404


def test_add_asset_reevaluates_deferred_event(api) -> None:
    db = api
    ev = Event(title="某品牌发布会定档", score=55, status=EventStatus.DEFERRED)
    EventDao(db).upsert(ev)

    def _asset_body(**kw):
        return {"type": "image", "auth_status": "cleared", **kw}

    r1 = client.post(f"/events/{ev.id}/assets", json=_asset_body())
    assert r1.status_code == 200
    assert r1.json()["event_status_changed"] is False  # 单图仍规则 4

    r2 = client.post(f"/events/{ev.id}/assets", json=_asset_body())
    assert r2.json()["event_status_changed"] is True
    assert r2.json()["decision_format"] == "image_slideshow"

    detail = client.get(f"/events/{ev.id}").json()
    assert detail["event"]["status"] == "ready"
    assert len(detail["assets"]) == 2


def test_add_asset_to_missing_event_404(api) -> None:
    resp = client.post("/events/missing/assets", json={"type": "image"})
    assert resp.status_code == 404


def test_add_asset_rejects_invalid_density(api) -> None:
    resp = client.post("/events/x/assets", json={"type": "image", "info_density": 150})
    assert resp.status_code == 422


# ---- 内容生产 API ----

def _seed_ready(db: DB, n_assets: int = 2, **event_kw) -> Event:
    ev = Event(
        title=event_kw.pop("title", "某地突发山火，救援进行中"),
        timeline=event_kw.pop(
            "timeline",
            [
                TimelineEntry(ts="2026-09-15T08:00:00+00:00", title="首报", heat=80.0),
                TimelineEntry(ts="2026-09-15T09:00:00+00:00", title="跟进", heat=85.0),
            ],
        ),
        **event_kw,
    )
    EventDao(db).upsert(ev)
    for i in range(n_assets):
        MediaAssetDao(db).insert(
            MediaAsset(
                event_id=ev.id,
                type=MediaType.IMAGE,
                source_type=SourceType.A,
                auth_status=AuthStatus.CLEARED,
                attribution="来源：合作媒体",
                info_density=70.0 + 10.0 * i,
            )
        )
    return ev


def test_produce_endpoint_200_and_event_transitions(api) -> None:
    ev = _seed_ready(api)

    resp = client.post("/pipeline/produce", json={"event_id": ev.id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["event_id"] == ev.id
    assert body["production_type"] == "image_slideshow"
    assert body["quality_status"] == "qualified"
    assert body["rule"] == "规则2"

    detail = client.get(f"/events/{ev.id}").json()
    assert detail["event"]["status"] == "produced"


def test_produce_endpoint_404_unknown_event(api) -> None:
    resp = client.post("/pipeline/produce", json={"event_id": "missing"})
    assert resp.status_code == 404


def test_produce_endpoint_409_when_not_ready(api) -> None:
    ev = _seed_ready(api, status=EventStatus.DEFERRED)
    resp = client.post("/pipeline/produce", json={"event_id": ev.id})
    assert resp.status_code == 409


def test_produce_endpoint_409_on_repeat(api) -> None:
    ev = _seed_ready(api)
    assert client.post("/pipeline/produce", json={"event_id": ev.id}).status_code == 200
    resp = client.post("/pipeline/produce", json={"event_id": ev.id})
    assert resp.status_code == 409


def test_produce_endpoint_422_missing_body(api) -> None:
    assert client.post("/pipeline/produce").status_code == 422


def test_produce_all_endpoint_reports_skipped(api) -> None:
    ev_ok = _seed_ready(api)
    _seed_ready(api, n_assets=1, title="素材不足事件")  # READY 但 DEFER → skipped

    resp = client.post("/pipeline/produce/all")
    assert resp.status_code == 200
    body = resp.json()
    assert {p["event_id"] for p in body["produced"]} == {ev_ok.id}
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["reason"] == "not_ready"


def test_produce_endpoint_uses_composer_override(api) -> None:
    class _StubComposer:
        name = "stub"

        def compose(self, event, assets, decision):
            return TemplateComposer().compose(event, assets, decision)

    ev = _seed_ready(api)
    app.dependency_overrides[get_composer] = lambda: _StubComposer()
    resp = client.post("/pipeline/produce", json={"event_id": ev.id})
    assert resp.status_code == 200
    assert resp.json()["composer"] == "stub"


def test_productions_list_and_status_filter(api) -> None:
    ev_ok = _seed_ready(api)
    ev_block = _seed_ready(api, timeline=[], title="时间线缺失事件")  # → BLOCKED
    assert client.post("/pipeline/produce", json={"event_id": ev_ok.id}).status_code == 200
    assert client.post("/pipeline/produce", json={"event_id": ev_block.id}).status_code == 200

    all_prods = client.get("/productions").json()
    assert len(all_prods) == 2

    qualified = client.get("/productions", params={"status": "qualified"}).json()
    assert [p["event_id"] for p in qualified] == [ev_ok.id]

    blocked = client.get("/productions", params={"status": "blocked"}).json()
    assert [p["event_id"] for p in blocked] == [ev_block.id]

    held = client.get("/productions", params={"status": "held"}).json()
    assert held == []

    limited = client.get("/productions", params={"limit": 1}).json()
    assert len(limited) == 1


def test_productions_rejects_invalid_status(api) -> None:
    resp = client.get("/productions", params={"status": "whatever"})
    assert resp.status_code == 422