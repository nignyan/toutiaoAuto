"""应用健康检查与管道 API 测试。"""

import pytest
from fastapi.testclient import TestClient

from app.api.pipeline import get_db, get_sources
from app.daos import DB, EventDao
from app.main import app
from app.models import Event, EventStatus
from app.pipeline.collector import FixtureSource, RawSignal

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