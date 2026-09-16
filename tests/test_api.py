"""应用健康检查与管道 API 测试。"""

from datetime import datetime, timedelta, timezone

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

def _seed_ready(db: DB, n_assets: int = 2, density_base: float = 70.0, **event_kw) -> Event:
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
                info_density=density_base + 10.0 * i,
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


# ---- 账号矩阵与分配入队（D10）----

def _create_account(**overrides) -> dict:
    body = {"name": "主域账号", "daily_quota": 2, **overrides}
    resp = client.post("/accounts", json=body)
    assert resp.status_code == 200
    return resp.json()


def _produce_qualified(api: DB, title: str = "某地突发山火，救援进行中", **seed_kw) -> dict:
    ev = _seed_ready(api, title=title, **seed_kw)
    resp = client.post("/pipeline/produce", json={"event_id": ev.id})
    assert resp.status_code == 200
    return resp.json()


def test_account_create_list_update_delete(api) -> None:
    acc = _create_account(vertical="科技", role="experiment")
    assert acc["role"] == "experiment"
    assert acc["daily_quota"] == 2
    assert acc["auto_publish"] is False  # 自动发布默认关闭（D5）

    assert [a["id"] for a in client.get("/accounts").json()] == [acc["id"]]

    paused = client.patch(f"/accounts/{acc['id']}", json={"status": "inactive"})
    assert paused.json()["status"] == "inactive"
    assert client.get("/accounts", params={"status": "active"}).json() == []

    patched = client.patch(f"/accounts/{acc['id']}", json={"daily_quota": 5, "name": "改名"})
    assert patched.json()["daily_quota"] == 5  # 部分字段更新，其余不受影响
    assert patched.json()["vertical"] == "科技"

    deleted = client.delete(f"/accounts/{acc['id']}")
    assert deleted.status_code == 200 and deleted.json() == {"deleted": True}
    assert client.get("/accounts").json() == []


def test_account_create_422_missing_name(api) -> None:
    assert client.post("/accounts", json={}).status_code == 422


def test_account_update_delete_404(api) -> None:
    assert client.patch("/accounts/missing", json={"name": "x"}).status_code == 404
    assert client.delete("/accounts/missing").status_code == 404


def test_account_delete_rejects_non_experiment(api) -> None:
    acc = _create_account(role="primary")

    assert client.delete(f"/accounts/{acc['id']}").status_code == 409  # 仅实验域可删


def test_account_delete_rejects_with_pending_queue(api) -> None:
    acc = _create_account(role="experiment")
    _produce_qualified(api)
    prod = client.get("/productions", params={"status": "qualified"}).json()[0]
    enqueue = client.post("/pipeline/enqueue", json={"production_id": prod["id"]})
    assert enqueue.status_code == 200

    assert client.delete(f"/accounts/{acc['id']}").status_code == 409  # 有待发布队列项


def test_enqueue_endpoint_200_and_backfill(api) -> None:
    acc = _create_account()
    prod = _produce_qualified(api)

    resp = client.post("/pipeline/enqueue", json={"production_id": prod["id"]})
    assert resp.status_code == 200
    item = resp.json()
    assert item["account_id"] == acc["id"]
    assert item["production_id"] == prod["id"]
    assert item["status"] == "pending"

    refreshed = client.get("/productions").json()[0]
    assert refreshed["account_id"] == acc["id"]  # 分配账号回填

    queue = client.get("/publish-queue").json()
    assert [i["id"] for i in queue] == [item["id"]]  # 队列可查
    assert len(client.get("/publish-queue", params={"account_id": acc["id"]}).json()) == 1


def test_enqueue_endpoint_404_unknown_production(api) -> None:
    assert client.post("/pipeline/enqueue", json={"production_id": "missing"}).status_code == 404


def test_enqueue_endpoint_409_repeats_and_non_qualified(api) -> None:
    _create_account()
    prod = _produce_qualified(api)

    assert client.post("/pipeline/enqueue", json={"production_id": prod["id"]}).status_code == 200
    resp = client.post("/pipeline/enqueue", json={"production_id": prod["id"]})
    assert resp.status_code == 409  # 已入队

    blocked = _produce_qualified(api, title="时间线缺失", timeline=[])  # → BLOCKED
    resp = client.post("/pipeline/enqueue", json={"production_id": blocked["id"]})
    assert resp.status_code == 409  # 非 QUALIFIED


def test_enqueue_endpoint_409_without_account(api) -> None:
    prod = _produce_qualified(api)  # 未配置任何账号

    assert client.post("/pipeline/enqueue", json={"production_id": prod["id"]}).status_code == 409


def test_enqueue_endpoint_422_missing_body(api) -> None:
    assert client.post("/pipeline/enqueue").status_code == 422


def test_enqueue_all_endpoint_quota_and_skip(api) -> None:
    _create_account(daily_quota=1)
    _produce_qualified(api, title="事件一")
    _produce_qualified(api, title="事件二")

    body = client.post("/pipeline/enqueue/all").json()
    assert len(body["enqueued"]) == 1  # 配额 1 只入一单
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["reason"] == "no_account"

    again = client.post("/pipeline/enqueue/all").json()
    assert again["enqueued"] == []  # 重复批量不重复入队
    assert len(again["skipped"]) == 1


def test_enqueue_all_endpoint_ignores_non_qualified(api) -> None:
    _create_account(daily_quota=5)
    _produce_qualified(api, title="正常事件")
    _produce_qualified(api, title="时间线缺失", timeline=[])  # BLOCKED
    _produce_qualified(api, title="held 事件标题超过十个字以便触发扣分", density_base=0.0)  # HELD

    body = client.post("/pipeline/enqueue/all").json()
    assert len(body["enqueued"]) == 1  # 仅 QUALIFIED 入队
    assert body["skipped"] == []


# ---- 素材等待队列超时归档 ----

def test_wait_queue_timeout_archives_expired_only(api) -> None:
    now = datetime.now(timezone.utc)
    dao = EventDao(api)
    expired = Event(
        title="过期等待事件",
        status=EventStatus.DEFERRED,
        deferred_at=(now - timedelta(hours=25)).isoformat(),
    )
    fresh = Event(
        title="新鲜等待事件",
        status=EventStatus.DEFERRED,
        deferred_at=(now - timedelta(hours=1)).isoformat(),
    )
    dao.upsert(expired)
    dao.upsert(fresh)

    body = client.post("/pipeline/wait-queue/timeout").json()
    assert [e["id"] for e in body["archived"]] == [expired.id]
    assert body["checked"] == 2
    assert dao.get(expired.id).status == EventStatus.ARCHIVED
    assert dao.get(fresh.id).status == EventStatus.DEFERRED

    again = client.post("/pipeline/wait-queue/timeout").json()
    assert again["archived"] == []  # 重复调用幂等：已归档不再出现在等待队列
    assert again["checked"] == 1


# ---- 发布执行（D13）----

from app.api.pipeline import get_adapter  # noqa: E402  与替身适配器配套使用
from app.publish.adapter import PublishResult  # noqa: E402
from app.publish.adapter import PublishStatus as AdapterStatus  # noqa: E402


class _FakeAdapter:
    """API 层适配器替身：按脚本依次返回结果。"""

    name = "fake"

    def __init__(self, *results: PublishResult):
        self._results = list(results)
        self.calls: list = []

    def publish(self, package, account) -> PublishResult:
        self.calls.append((package, account))
        return self._results.pop(0)


def _override_adapter(adapter: _FakeAdapter) -> None:
    app.dependency_overrides[get_adapter] = lambda: adapter


_DRAFT_OK = PublishResult(status=AdapterStatus.DRAFT_READY, message="草稿箱已填好")
_AUTO_PUB = PublishResult(status=AdapterStatus.PUBLISHED, message="已自动发布")


# ---- get_adapter CDP 接线（D14）----

def test_get_adapter_reads_cdp_endpoint_from_env(monkeypatch) -> None:
    monkeypatch.setenv("TOUTIAO_CDP_ENDPOINT", "http://localhost:9222")
    adapter = get_adapter()

    assert adapter.cdp_endpoint == "http://localhost:9222"


def test_get_adapter_defaults_to_profile_mode(monkeypatch) -> None:
    monkeypatch.delenv("TOUTIAO_CDP_ENDPOINT", raising=False)

    assert get_adapter().cdp_endpoint is None


def _enqueue_one(api: DB) -> dict:
    """账号 + QUALIFIED 成品入队，返回队列项。"""
    _create_account()
    prod = _produce_qualified(api)
    resp = client.post("/pipeline/enqueue", json={"production_id": prod["id"]})
    assert resp.status_code == 200
    return resp.json()


def test_publish_queue_item_fills_draft(api) -> None:
    item = _enqueue_one(api)
    _override_adapter(_FakeAdapter(_DRAFT_OK))

    resp = client.post(f"/publish-queue/{item['id']}/publish")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "draft_ready"
    assert "[draft_ready]" in body["publish_result"]


def test_publish_queue_item_auto_publish_records_published(api) -> None:
    item = _enqueue_one(api)
    _override_adapter(_FakeAdapter(_AUTO_PUB))

    resp = client.post(f"/publish-queue/{item['id']}/publish")

    assert resp.status_code == 200
    assert resp.json()["status"] == "published"


def test_publish_queue_item_failure_and_retry(api) -> None:
    item = _enqueue_one(api)
    _override_adapter(_FakeAdapter(PublishResult(status=AdapterStatus.FAILED, message="上传超时")))
    first = client.post(f"/publish-queue/{item['id']}/publish")
    assert first.json()["status"] == "failed"  # 适配器失败也是 200（结果落库）

    _override_adapter(_FakeAdapter(_DRAFT_OK))
    retry = client.post(f"/publish-queue/{item['id']}/publish")
    assert retry.status_code == 200  # failed 可重试
    assert retry.json()["status"] == "draft_ready"


def test_publish_queue_item_404_unknown(api) -> None:
    _override_adapter(_FakeAdapter())
    assert client.post("/publish-queue/missing/publish").status_code == 404


def test_publish_queue_item_409_on_repeat_dispatch(api) -> None:
    item = _enqueue_one(api)
    _override_adapter(_FakeAdapter(_DRAFT_OK))
    assert client.post(f"/publish-queue/{item['id']}/publish").status_code == 200

    again = client.post(f"/publish-queue/{item['id']}/publish")
    assert again.status_code == 409  # draft_ready 不可重复派发（避免重复草稿）


def test_skip_unskip_confirm_flow(api) -> None:
    item = _enqueue_one(api)

    skipped = client.post(f"/publish-queue/{item['id']}/skip")
    assert skipped.status_code == 200
    assert skipped.json()["status"] == "skipped"

    blocked = client.post(f"/publish-queue/{item['id']}/publish")
    assert blocked.status_code == 409  # skipped 不可直接派发

    unskipped = client.post(f"/publish-queue/{item['id']}/unskip")
    assert unskipped.status_code == 200
    assert unskipped.json()["status"] == "pending"

    _override_adapter(_FakeAdapter(_DRAFT_OK))
    assert client.post(f"/publish-queue/{item['id']}/publish").status_code == 200

    confirmed = client.post(f"/publish-queue/{item['id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "published"
    assert confirmed.json()["publish_result"] == "人工确认已发布"


def test_queue_action_409_on_wrong_state(api) -> None:
    item = _enqueue_one(api)

    assert client.post(f"/publish-queue/{item['id']}/unskip").status_code == 409  # 非 skipped
    assert client.post(f"/publish-queue/{item['id']}/confirm").status_code == 409  # 非 draft_ready

    assert client.post(f"/publish-queue/{item['id']}/skip").status_code == 200
    assert client.post(f"/publish-queue/{item['id']}/skip").status_code == 409  # 重复跳过
    assert client.post("/publish-queue/missing/skip").status_code == 404


def test_patch_queue_item_title_updates_production(api) -> None:
    item = _enqueue_one(api)
    old_title = client.get("/productions").json()[0]["title"]

    resp = client.patch(f"/publish-queue/{item['id']}", json={"title": "运营改过的标题"})
    assert resp.status_code == 200

    prods = client.get("/productions").json()
    assert prods[0]["title"] == "运营改过的标题"
    assert prods[0]["title"] != old_title


def test_patch_queue_item_sort_key_reorders_list(api) -> None:
    _create_account(daily_quota=5)
    prod1 = _produce_qualified(api, title="事件一")
    prod2 = _produce_qualified(api, title="事件二")
    first = client.post("/pipeline/enqueue", json={"production_id": prod1["id"]}).json()
    second = client.post("/pipeline/enqueue", json={"production_id": prod2["id"]}).json()
    assert client.get("/publish-queue").json()[0]["id"] == first["id"]  # 默认 FIFO

    moved = client.patch(f"/publish-queue/{second['id']}", json={"sort_key": -1})
    assert moved.status_code == 200
    assert [i["id"] for i in client.get("/publish-queue").json()] == [second["id"], first["id"]]

    both = client.patch(f"/publish-queue/{first['id']}", json={"title": "新标题", "sort_key": -5})
    assert both.status_code == 200  # 标题与排序可同时更新
    assert [i["id"] for i in client.get("/publish-queue").json()] == [first["id"], second["id"]]


def test_patch_queue_item_400_and_404(api) -> None:
    item = _enqueue_one(api)

    assert client.patch(f"/publish-queue/{item['id']}", json={}).status_code == 400  # 空载荷
    assert client.patch("/publish-queue/missing", json={"title": "x"}).status_code == 404


def test_account_delete_blocked_by_draft_ready(api) -> None:
    acc = _create_account(role="experiment")
    prod = _produce_qualified(api)
    item = client.post("/pipeline/enqueue", json={"production_id": prod["id"]}).json()
    assert item["account_id"] == acc["id"]  # 实验域账号唯一可用，分配给它
    _override_adapter(_FakeAdapter(_DRAFT_OK))
    assert client.post(f"/publish-queue/{item['id']}/publish").status_code == 200

    resp = client.delete(f"/accounts/{acc['id']}")
    assert resp.status_code == 409  # 草稿待发布仍占用账号
