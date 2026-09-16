"""数据回流 API 测试：回填 upsert 守卫、分析报告、建议决策端点。"""

import pytest
from fastapi.testclient import TestClient

from app.api.pipeline import get_db
from app.daos import DB, ProductionDao, PublishQueueDao, RefluxSuggestionDao
from app.main import app
from app.models import (
    Production,
    ProductionType,
    PublishQueueItem,
    PublishStatus,
    QualityStatus,
    RefluxSuggestion,
    SuggestionKind,
    SuggestionStatus,
)

client = TestClient(app)


@pytest.fixture()
def api(tmp_path):
    db = DB(tmp_path / "reflux_api.db")
    db.migrate()
    app.dependency_overrides[get_db] = lambda: db
    yield db
    app.dependency_overrides.clear()


def _published_production(db: DB, production_id: str = "p1", **kw) -> None:
    ProductionDao(db).insert(
        Production(
            id=production_id,
            event_id=kw.pop("event_id", "ev1"),
            production_type=kw.pop("production_type", ProductionType.TEXT),
            title=kw.pop("title", "某地突发山火，救援进行中"),
            quality_score=80.0,
            quality_status=QualityStatus.QUALIFIED,
        )
    )
    PublishQueueDao(db).insert(
        PublishQueueItem(
            account_id=kw.pop("account_id", "acc1"),
            production_id=production_id,
            status=kw.pop("status", PublishStatus.PUBLISHED),
            published_at=kw.pop("published_at", "2026-09-16T10:30:00+00:00"),
        )
    )


def _payload(production_id: str = "p1", **kw) -> dict:
    body = {
        "production_id": production_id,
        "exposure": kw.pop("exposure", 1000),
        "plays": kw.pop("plays", 500),
        "completion_rate": kw.pop("completion_rate", 45.0),
        "interactions": kw.pop("interactions", 80),
        "negative": kw.pop("negative", 2),
        "review_status": kw.pop("review_status", "approved"),
        "review_note": kw.pop("review_note", ""),
    }
    body.update(kw)
    return body


def _seed_suggestion(db: DB, **kw) -> RefluxSuggestion:
    sug = RefluxSuggestion(
        kind=kw.pop("kind", SuggestionKind.FORMAT),
        text=kw.pop("text", "建议优先图集形态"),
        status=kw.pop("status", SuggestionStatus.PENDING),
    )
    RefluxSuggestionDao(db).insert(sug)
    return sug


# ---- POST /reflux/records ----

class TestUpsertRecordEndpoint:
    def test_upsert_returns_enriched_view(self, api) -> None:
        _published_production(api)
        resp = client.post("/reflux/records", json=_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["record"]["production_id"] == "p1"
        assert body["record"]["account_id"] == "acc1"  # 队列账号冗余回填
        assert body["record"]["review_status"] == "approved"
        assert body["production_title"] == "某地突发山火，救援进行中"
        assert body["production_type"] == "text"
        assert body["published_at"] == "2026-09-16T10:30:00+00:00"

    def test_reentry_updates_and_preserves_created_at(self, api) -> None:
        _published_production(api)
        first = client.post("/reflux/records", json=_payload(exposure=1000)).json()
        second = client.post("/reflux/records", json=_payload(exposure=2000)).json()
        assert second["record"]["id"] == first["record"]["id"]
        assert second["record"]["created_at"] == first["record"]["created_at"]
        assert second["record"]["exposure"] == 2000

    def test_missing_production_404(self, api) -> None:
        resp = client.post("/reflux/records", json=_payload("ghost"))
        assert resp.status_code == 404

    def test_unpublished_queue_item_409(self, api) -> None:
        _published_production(api, status=PublishStatus.DRAFT_READY)
        resp = client.post("/reflux/records", json=_payload())
        assert resp.status_code == 409

    def test_missing_queue_item_409(self, api) -> None:
        ProductionDao(api).insert(
            Production(
                id="p1", event_id="ev1", production_type=ProductionType.TEXT,
                quality_score=80.0, quality_status=QualityStatus.QUALIFIED,
            )
        )
        resp = client.post("/reflux/records", json=_payload())
        assert resp.status_code == 409

    def test_negative_metric_rejected_422(self, api) -> None:
        _published_production(api)
        resp = client.post("/reflux/records", json=_payload(exposure=-1))
        assert resp.status_code == 422


# ---- GET /reflux/records ----

def test_list_records_enriched_order(api) -> None:
    _published_production(api, "p1")
    _published_production(api, "p2")
    client.post("/reflux/records", json=_payload("p1"))
    client.post("/reflux/records", json=_payload("p2"))
    resp = client.get("/reflux/records")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["record"]["production_id"] for r in body] == ["p2", "p1"]  # 回填倒序
    assert body[0]["production_type"] == "text"


def test_list_records_limit(api) -> None:
    _published_production(api, "p1")
    _published_production(api, "p2")
    client.post("/reflux/records", json=_payload("p1"))
    client.post("/reflux/records", json=_payload("p2"))
    assert len(client.get("/reflux/records?limit=1").json()) == 1


# ---- POST /reflux/analyze + GET /reflux/analysis ----

class TestAnalyzeEndpoints:
    def test_analyze_returns_report_and_pending_suggestions(self, api) -> None:
        # 图文两条互动率 20%，视频两条 10%：同桶发表，只拉开形态差距
        seeds = [("p1", ProductionType.TEXT, 200), ("p2", ProductionType.TEXT, 200),
                 ("p3", ProductionType.VIDEO, 100), ("p4", ProductionType.VIDEO, 100)]
        for pid, ptype, interactions in seeds:
            _published_production(api, pid, production_type=ptype)
            resp = client.post("/reflux/records", json=_payload(pid, interactions=interactions))
            assert resp.status_code == 200
        resp = client.post("/reflux/analyze")
        assert resp.status_code == 200
        body = resp.json()
        assert body["report"]["record_count"] == 4
        assert len(body["suggestions"]) == 1  # 形态差距 100% → 1 条待确认
        assert body["suggestions"][0]["kind"] == "format"
        assert body["suggestions"][0]["status"] == "pending"

    def test_analysis_readonly_no_suggestion_mutation(self, api) -> None:
        _seed_suggestion(api)
        resp = client.get("/reflux/analysis")
        assert resp.status_code == 200
        assert resp.json()["record_count"] == 0  # 无回填数据，空报告
        remaining = client.get("/reflux/suggestions").json()
        assert len(remaining) == 1  # GET 分析不重建建议

    def test_analyze_keeps_decided_history(self, api) -> None:
        sug = _seed_suggestion(api)
        client.post(f"/reflux/suggestions/{sug.id}/confirm")
        client.post("/reflux/analyze")  # 无数据 → pending 清空，已确认保留
        assert client.get("/reflux/suggestions?status=confirmed").json() != []
        assert client.get("/reflux/suggestions?status=pending").json() == []


# ---- 建议决策端点 ----

class TestSuggestionEndpoints:
    def test_confirm_reject_rollback_flow(self, api) -> None:
        sug = _seed_suggestion(api)
        confirmed = client.post(f"/reflux/suggestions/{sug.id}/confirm").json()
        assert confirmed["status"] == "confirmed"
        assert confirmed["decided_at"]
        rolled = client.post(f"/reflux/suggestions/{sug.id}/rollback").json()
        assert rolled["status"] == "pending"  # 回滚回到待确认
        rejected = client.post(f"/reflux/suggestions/{sug.id}/reject").json()
        assert rejected["status"] == "rejected"

    def test_invalid_transition_409(self, api) -> None:
        sug = _seed_suggestion(api, status=SuggestionStatus.CONFIRMED)
        resp = client.post(f"/reflux/suggestions/{sug.id}/reject")
        assert resp.status_code == 409

    def test_missing_suggestion_404(self, api) -> None:
        assert client.post("/reflux/suggestions/ghost/confirm").status_code == 404

    def test_list_filter_by_status(self, api) -> None:
        _seed_suggestion(api, kind=SuggestionKind.TIMING)
        _seed_suggestion(api, kind=SuggestionKind.VERTICAL, status=SuggestionStatus.REJECTED)
        pending = client.get("/reflux/suggestions?status=pending").json()
        rejected = client.get("/reflux/suggestions?status=rejected").json()
        assert [s["kind"] for s in pending] == ["timing"]
        assert [s["kind"] for s in rejected] == ["vertical"]
