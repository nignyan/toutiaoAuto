"""数据回流测试：表现记录 upsert、建议状态机、存量库 published_at 补列（分析见批次3）。"""

import sqlite3

import pytest

from app.daos import (
    DB,
    ProductionDao,
    PublishQueueDao,
    RefluxRecordDao,
    RefluxSuggestionDao,
)
from app.models import (
    PerformanceRecord,
    Production,
    ProductionType,
    PublishQueueItem,
    PublishStatus,
    QualityStatus,
    RefluxSuggestion,
    ReviewStatus,
    SuggestionKind,
    SuggestionStatus,
)


@pytest.fixture()
def db(tmp_path) -> DB:
    d = DB(tmp_path / "test.db")
    d.migrate()
    return d


# ---- 构造辅助 ----

def _production(db: DB, production_id: str = "p1", **kw) -> Production:
    prod = Production(
        id=production_id,
        event_id=kw.pop("event_id", "ev1"),
        vertical=kw.pop("vertical", ""),
        production_type=kw.pop("production_type", ProductionType.TEXT),
        title=kw.pop("title", "某地突发山火，救援进行中"),
        quality_score=kw.pop("quality_score", 80.0),
        quality_status=kw.pop("quality_status", QualityStatus.QUALIFIED),
        **kw,
    )
    ProductionDao(db).insert(prod)
    return prod


def _published_queue(db: DB, production_id: str, **kw) -> PublishQueueItem:
    item = PublishQueueItem(
        account_id=kw.pop("account_id", "acc1"),
        production_id=production_id,
        status=kw.pop("status", PublishStatus.PUBLISHED),
        published_at=kw.pop("published_at", "2026-09-16T10:30:00+00:00"),
        **kw,
    )
    PublishQueueDao(db).insert(item)
    return item


def _record(production_id: str = "p1", **kw) -> PerformanceRecord:
    return PerformanceRecord(
        production_id=production_id,
        account_id=kw.pop("account_id", "acc1"),
        exposure=kw.pop("exposure", 1000),
        plays=kw.pop("plays", 500),
        completion_rate=kw.pop("completion_rate", 45.0),
        interactions=kw.pop("interactions", 50),
        negative=kw.pop("negative", 2),
        review_status=kw.pop("review_status", ReviewStatus.APPROVED),
        review_note=kw.pop("review_note", ""),
        **kw,
    )


def _suggestion(kind: SuggestionKind = SuggestionKind.FORMAT, **kw) -> RefluxSuggestion:
    return RefluxSuggestion(
        kind=kind,
        text=kw.pop("text", "建议优先图集形态"),
        basis=kw.pop("basis", "图集互动率 8.5% 高于图文 3.1%"),
        impact=kw.pop("impact", "预期互动率提升"),
        status=kw.pop("status", SuggestionStatus.PENDING),
        **kw,
    )


# ---- RefluxRecordDao ----

class TestRefluxRecordDao:
    def test_roundtrip_preserves_all_fields(self, db) -> None:
        dao = RefluxRecordDao(db)
        dao.upsert(_record())
        loaded = dao.get_by_production("p1")
        assert loaded is not None
        assert loaded.account_id == "acc1"
        assert loaded.exposure == 1000
        assert loaded.plays == 500
        assert loaded.completion_rate == 45.0
        assert loaded.interactions == 50
        assert loaded.negative == 2
        assert loaded.review_status == ReviewStatus.APPROVED
        assert loaded.recorded_at  # 默认填充回填时间
        assert loaded.created_at

    def test_upsert_overwrites_metrics_keeps_identity(self, db) -> None:
        dao = RefluxRecordDao(db)
        dao.upsert(_record(exposure=1000))
        first = dao.get_by_production("p1")
        assert first is not None

        dao.upsert(
            _record(exposure=2000, review_status=ReviewStatus.REJECTED, review_note="标题党")
        )
        second = dao.get_by_production("p1")
        assert second is not None
        assert second.id == first.id  # 1:1 upsert 不换主键
        assert second.created_at == first.created_at  # 首次回填时间保留
        assert second.exposure == 2000
        assert second.review_status == ReviewStatus.REJECTED
        assert second.review_note == "标题党"

    def test_list_orders_by_recorded_at_desc(self, db) -> None:
        dao = RefluxRecordDao(db)
        dao.upsert(_record("p1", recorded_at="2026-09-16T01:00:00+00:00"))
        dao.upsert(_record("p2", recorded_at="2026-09-16T03:00:00+00:00"))
        dao.upsert(_record("p3", recorded_at="2026-09-16T02:00:00+00:00"))
        assert [r.production_id for r in dao.list()] == ["p2", "p3", "p1"]
        assert [r.production_id for r in dao.list(limit=2)] == ["p2", "p3"]

    def test_get_missing_returns_none(self, db) -> None:
        assert RefluxRecordDao(db).get_by_production("nope") is None


# ---- RefluxSuggestionDao ----

class TestRefluxSuggestionDao:
    def test_roundtrip_and_status_filter(self, db) -> None:
        dao = RefluxSuggestionDao(db)
        dao.insert(_suggestion(SuggestionKind.FORMAT))
        dao.insert(_suggestion(SuggestionKind.TIMING, status=SuggestionStatus.CONFIRMED))
        assert len(dao.list()) == 2
        assert [s.kind for s in dao.list(status=SuggestionStatus.PENDING)] == [
            SuggestionKind.FORMAT
        ]
        assert [s.kind for s in dao.list(status=SuggestionStatus.CONFIRMED)] == [
            SuggestionKind.TIMING
        ]

    def test_update_status_sets_and_keeps_decided_at(self, db) -> None:
        dao = RefluxSuggestionDao(db)
        sug = _suggestion()
        dao.insert(sug)
        decided = "2026-09-16T12:00:00+00:00"
        dao.update_status(sug.id, SuggestionStatus.CONFIRMED, decided_at=decided)
        loaded = dao.get(sug.id)
        assert loaded is not None
        assert loaded.status == SuggestionStatus.CONFIRMED
        assert loaded.decided_at == "2026-09-16T12:00:00+00:00"

        dao.update_status(sug.id, SuggestionStatus.PENDING)  # 回滚：不清决策时间
        loaded = dao.get(sug.id)
        assert loaded is not None
        assert loaded.status == SuggestionStatus.PENDING
        assert loaded.decided_at == "2026-09-16T12:00:00+00:00"

    def test_delete_pending_with_keeps_decided(self, db) -> None:
        dao = RefluxSuggestionDao(db)
        dao.insert(_suggestion(SuggestionKind.FORMAT))
        dao.insert(_suggestion(SuggestionKind.TIMING, status=SuggestionStatus.REJECTED))
        with db.transaction() as conn:
            dao.delete_pending_with(conn)
        remaining = dao.list()
        assert [s.kind for s in remaining] == [SuggestionKind.TIMING]


# ---- 存量库迁移 ----

_LEGACY_QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS publish_queue (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    production_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    scheduled_for TEXT NOT NULL DEFAULT '',
    publish_result TEXT NOT NULL DEFAULT '',
    sort_key INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""


def test_migrate_adds_published_at_to_legacy_publish_queue_db(tmp_path) -> None:
    path = tmp_path / "legacy_pub.db"
    conn = sqlite3.connect(path)
    conn.execute(_LEGACY_QUEUE_DDL)
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
    assert loaded.published_at == ""  # 补列默认值，旧行存活
    d.migrate()  # 二次迁移幂等
