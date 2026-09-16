"""DAO 层测试：建表幂等、事件/素材/成品/账号/队列往返、过滤排序、存量库补列。"""

import sqlite3

import pytest

from app.daos import (
    DB,
    AccountDao,
    EventDao,
    MediaAssetDao,
    ProductionDao,
    PublishQueueDao,
)
from app.models import (
    Account,
    AccountRole,
    AccountStatus,
    AuthStatus,
    Clarity,
    Event,
    EventStatus,
    MediaAsset,
    MediaType,
    Production,
    ProductionType,
    PublishQueueItem,
    PublishStatus,
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


def test_production_get_by_id_and_roundtrip_vertical(production_dao) -> None:
    p = _production(vertical="科技")
    production_dao.insert(p)

    assert production_dao.get(p.id) == p  # 含 vertical 全字段往返
    assert production_dao.get("nope") is None


def test_production_update_account_with(production_dao, db) -> None:
    p = _production()
    production_dao.insert(p)

    with db.transaction() as conn:
        production_dao.update_account_with(conn, p.id, "acc1")
    assert production_dao.get(p.id).account_id == "acc1"


def test_production_update_title(production_dao) -> None:
    p = _production()
    production_dao.insert(p)

    production_dao.update_title(p.id, "运营改后的标题")
    assert production_dao.get(p.id).title == "运营改后的标题"


# ---- 存量库迁移 ----

_LEGACY_PRODUCTION_DDL = """
CREATE TABLE IF NOT EXISTS production (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    production_type TEXT NOT NULL,
    asset_ids_json TEXT NOT NULL DEFAULT '[]',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    cover_asset_id TEXT NOT NULL DEFAULT '',
    rule TEXT NOT NULL DEFAULT '',
    composer TEXT NOT NULL DEFAULT 'template',
    quality_score REAL NOT NULL DEFAULT 0,
    quality_status TEXT NOT NULL,
    checks_json TEXT NOT NULL DEFAULT '[]',
    vetoes_json TEXT NOT NULL DEFAULT '[]',
    account_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""


def test_migrate_adds_vertical_to_legacy_production_db(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(_LEGACY_PRODUCTION_DDL)
    conn.execute(
        "INSERT INTO production (id, event_id, production_type, quality_status, created_at)"
        " VALUES ('p1', 'ev1', 'video', 'qualified', '2026-09-15T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    d = DB(path)
    d.migrate()  # 存量库补列 + 新表幂等创建
    loaded = ProductionDao(d).get("p1")
    assert loaded is not None
    assert loaded.vertical == ""  # 补列默认值，旧行存活
    d.migrate()  # 二次迁移幂等


_LEGACY_PUBLISH_QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS publish_queue (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    production_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    scheduled_for TEXT NOT NULL DEFAULT '',
    publish_result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""


def test_migrate_adds_sort_key_to_legacy_publish_queue_db(tmp_path) -> None:
    path = tmp_path / "legacy_q.db"
    conn = sqlite3.connect(path)
    conn.execute(_LEGACY_PUBLISH_QUEUE_DDL)
    conn.execute(
        "INSERT INTO publish_queue (id, account_id, production_id, created_at)"
        " VALUES ('q1', 'acc1', 'p1', '2026-09-15T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    d = DB(path)
    d.migrate()
    loaded = PublishQueueDao(d).get("q1")
    assert loaded is not None
    assert loaded.sort_key == 0  # 补列默认值，旧行存活且列表仍可排序
    assert [i.id for i in PublishQueueDao(d).list()] == ["q1"]
    d.migrate()  # 二次迁移幂等


# ---- AccountDao ----

@pytest.fixture()
def account_dao(db) -> AccountDao:
    return AccountDao(db)


def _account(name: str = "主域账号", **kw) -> Account:
    return Account(
        name=name,
        vertical=kw.pop("vertical", ""),
        role=kw.pop("role", AccountRole.PRIMARY),
        daily_quota=kw.pop("daily_quota", 3),
        publish_window_start=kw.pop("publish_window_start", "08:00"),
        publish_window_end=kw.pop("publish_window_end", "22:00"),
        status=kw.pop("status", AccountStatus.ACTIVE),
        auto_publish=kw.pop("auto_publish", False),
        profile_dir=kw.pop("profile_dir", "profiles/acc1"),
        **kw,
    )


def test_account_roundtrip_preserves_all_fields(account_dao) -> None:
    a = _account()
    account_dao.upsert(a)

    assert account_dao.get(a.id) == a  # 含 role/auto_publish 全字段往返


def test_account_list_filters_status_and_sorts_by_created(account_dao) -> None:
    old = _account(name="旧账号")
    old.created_at = "2026-09-14T00:00:00+00:00"
    new = _account(name="新账号", status=AccountStatus.INACTIVE)
    new.created_at = "2026-09-16T00:00:00+00:00"
    account_dao.upsert(new)
    account_dao.upsert(old)

    assert [a.name for a in account_dao.list()] == ["旧账号", "新账号"]  # 配置时间升序
    assert [a.name for a in account_dao.list(status=AccountStatus.ACTIVE)] == ["旧账号"]


def test_account_delete_reports_existence(account_dao) -> None:
    a = _account()
    account_dao.upsert(a)

    assert account_dao.delete(a.id) is True
    assert account_dao.get(a.id) is None
    assert account_dao.delete("nope") is False


# ---- PublishQueueDao ----

@pytest.fixture()
def queue_dao(db) -> PublishQueueDao:
    return PublishQueueDao(db)


def _queue_item(account_id: str = "acc1", production_id: str = "p1", **kw) -> PublishQueueItem:
    return PublishQueueItem(
        account_id=account_id,
        production_id=production_id,
        status=kw.pop("status", PublishStatus.PENDING),
        scheduled_for=kw.pop("scheduled_for", ""),
        publish_result=kw.pop("publish_result", ""),
        **kw,
    )


def test_queue_roundtrip_and_get_by_production(queue_dao) -> None:
    item = _queue_item()
    queue_dao.insert(item)

    assert queue_dao.get(item.id) == item
    assert queue_dao.get_by_production("p1") == item
    assert queue_dao.get_by_production("nope") is None


def test_queue_rejects_duplicate_production(queue_dao) -> None:
    queue_dao.insert(_queue_item())

    with pytest.raises(sqlite3.IntegrityError):  # 唯一索引兜底 1:1 幂等
        queue_dao.insert(_queue_item())


def test_queue_list_filters_fifo_order(queue_dao) -> None:
    first = _queue_item(account_id="acc1", production_id="p1")
    second = _queue_item(account_id="acc1", production_id="p2")
    second.created_at = "2026-09-16T01:00:00+00:00"
    other = _queue_item(account_id="acc2", production_id="p3", status=PublishStatus.PUBLISHED)
    other.created_at = "2026-09-16T02:00:00+00:00"
    first.created_at = "2026-09-16T00:00:00+00:00"
    queue_dao.insert(other)
    queue_dao.insert(first)
    queue_dao.insert(second)

    assert [i.production_id for i in queue_dao.list()] == ["p1", "p2", "p3"]  # FIFO
    assert [i.production_id for i in queue_dao.list(account_id="acc1")] == ["p1", "p2"]
    assert [i.production_id for i in queue_dao.list(status=PublishStatus.PUBLISHED)] == ["p3"]
    assert [i.production_id for i in queue_dao.list(limit=2)] == ["p1", "p2"]


def test_queue_count_by_account_on_date_prefix(queue_dao) -> None:
    today_item = _queue_item(account_id="acc1", production_id="p1")
    today_item.created_at = "2026-09-16T03:00:00+00:00"
    another_today = _queue_item(account_id="acc1", production_id="p2")
    another_today.created_at = "2026-09-16T04:00:00+00:00"
    other_account = _queue_item(account_id="acc2", production_id="p3")
    other_account.created_at = "2026-09-16T05:00:00+00:00"
    yesterday = _queue_item(account_id="acc1", production_id="p4")
    yesterday.created_at = "2026-09-15T23:00:00+00:00"
    for item in (today_item, another_today, other_account, yesterday):
        queue_dao.insert(item)

    counts = queue_dao.count_by_account_on("2026-09-16")
    assert counts == {"acc1": 2, "acc2": 1}  # 昨日条目不计入当日配额


def test_queue_count_for_account_with_status(queue_dao) -> None:
    queue_dao.insert(_queue_item(production_id="p1"))
    queue_dao.insert(_queue_item(production_id="p2", status=PublishStatus.PUBLISHED))

    assert queue_dao.count_for_account("acc1") == 2
    assert queue_dao.count_for_account("acc1", status=PublishStatus.PENDING) == 1
    assert queue_dao.count_for_account("acc2") == 0


# ---- PublishQueueDao：发布执行扩展（D13）----

def test_queue_roundtrip_preserves_sort_key_and_draft_ready(queue_dao) -> None:
    item = _queue_item(sort_key=20, status=PublishStatus.DRAFT_READY, publish_result="[x] y")
    queue_dao.insert(item)

    assert queue_dao.get(item.id) == item  # 含 sort_key / draft_ready 全字段往返


def test_queue_update_status_keeps_result_when_none(queue_dao) -> None:
    item = _queue_item(publish_result="[draft_ready] 草稿箱已填好")
    queue_dao.insert(item)

    queue_dao.update_status(item.id, PublishStatus.SKIPPED)
    loaded = queue_dao.get(item.id)
    assert loaded.status == PublishStatus.SKIPPED
    assert loaded.publish_result == "[draft_ready] 草稿箱已填好"  # 跳过不改写派发记录


def test_queue_update_status_overwrites_result(queue_dao) -> None:
    item = _queue_item()
    queue_dao.insert(item)

    queue_dao.update_status(item.id, PublishStatus.FAILED, publish_result="[failed] 上传超时")
    loaded = queue_dao.get(item.id)
    assert loaded.status == PublishStatus.FAILED
    assert loaded.publish_result == "[failed] 上传超时"


def test_queue_update_sort_key_reorders_list(queue_dao) -> None:
    a = _queue_item(production_id="p1")
    b = _queue_item(production_id="p2")
    c = _queue_item(production_id="p3")
    for item in (a, b, c):
        queue_dao.insert(item)

    queue_dao.update_sort_key(b.id, -5)  # 负值排最前
    queue_dao.update_sort_key(a.id, 10)
    assert [i.production_id for i in queue_dao.list()] == ["p2", "p3", "p1"]

    queue_dao.update_sort_key(b.id, 10)  # 同键回退入队序
    assert [i.production_id for i in queue_dao.list()] == ["p3", "p1", "p2"]
