"""素材等待队列超时归档测试（产品设计 §4.4 口径）。"""

from datetime import datetime, timedelta, timezone

import pytest

from app.daos import DB, EventDao, MediaAssetDao
from app.models import AuthStatus, Event, EventStatus, MediaAsset, MediaType
from app.pipeline.asset_ingest import ingest_asset
from app.pipeline.wait_queue import archive_expired, expired_deferred, wait_started

NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)


def _ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat()


def _deferred(deferred_at: str = "", **kw) -> Event:
    kw.setdefault("title", "某品牌发布会定档")
    kw.setdefault("status", EventStatus.DEFERRED)
    if deferred_at:
        kw["deferred_at"] = deferred_at
    return Event(**kw)


@pytest.fixture()
def db(tmp_path) -> DB:
    d = DB(tmp_path / "wait_queue.db")
    d.migrate()
    return d


# ---- 模型：等待起点兜底 ----

def test_deferred_event_auto_fills_deferred_at() -> None:
    ev = _deferred()
    assert ev.deferred_at != ""


def test_explicit_deferred_at_not_overwritten() -> None:
    ev = _deferred(deferred_at="2026-01-01T00:00:00+00:00")
    assert ev.deferred_at == "2026-01-01T00:00:00+00:00"


def test_non_deferred_event_deferred_at_stays_empty() -> None:
    ev = Event(title="雅安山火", status=EventStatus.READY)
    assert ev.deferred_at == ""


# ---- 纯函数：超时判定 ----

def test_expired_deferred_is_selected() -> None:
    ev = _deferred(deferred_at=_ago(25))
    assert expired_deferred([ev], NOW) == [ev]


def test_fresh_deferred_is_kept() -> None:
    ev = _deferred(deferred_at=_ago(23))
    assert expired_deferred([ev], NOW) == []


def test_exactly_24h_is_not_archived_strictly_exceeds() -> None:
    ev = _deferred(deferred_at=_ago(24))
    assert expired_deferred([ev], NOW) == []


def test_missing_deferred_at_falls_back_to_created_at() -> None:
    ev = _deferred()
    ev.deferred_at = ""  # 模拟存量库旧行
    ev.created_at = _ago(30)
    assert wait_started(ev) == datetime.fromisoformat(_ago(30))
    assert expired_deferred([ev], NOW) == [ev]


def test_non_deferred_events_never_archived() -> None:
    events = [
        Event(title="ready", status=EventStatus.READY, deferred_at=_ago(48)),
        Event(title="produced", status=EventStatus.PRODUCED),
        Event(title="archived", status=EventStatus.ARCHIVED),
    ]
    assert expired_deferred(events, NOW) == []


# ---- 编排：归档落库 ----

def test_archive_expired_updates_only_expired(db) -> None:
    expired = _deferred(title="过期等待", deferred_at=_ago(25))
    fresh = _deferred(title="新鲜等待", deferred_at=_ago(1))
    dao = EventDao(db)
    dao.upsert(expired)
    dao.upsert(fresh)

    report = archive_expired(db, now=NOW)

    assert [e.id for e in report.archived] == [expired.id]
    assert report.checked == 2
    assert dao.get(expired.id).status == EventStatus.ARCHIVED
    assert dao.get(fresh.id).status == EventStatus.DEFERRED


def test_archive_expired_empty_queue_is_noop(db) -> None:
    report = archive_expired(db, now=NOW)
    assert report.archived == []
    assert report.checked == 0


def test_archive_expired_rerun_is_noop(db) -> None:
    expired = _deferred(title="过期等待", deferred_at=_ago(25))
    dao = EventDao(db)
    dao.upsert(expired)

    archive_expired(db, now=NOW)
    rerun = archive_expired(db, now=NOW)

    assert rerun.archived == []
    assert rerun.checked == 0  # 已归档不再出现在等待队列


# ---- 等待队列联动：重试计数 + 归档不再尝试 ----

def _image(auth: AuthStatus = AuthStatus.CLEARED) -> MediaAsset:
    return MediaAsset(type=MediaType.IMAGE, auth_status=auth)


def test_ingest_on_deferred_counts_retry(db) -> None:
    ev = _deferred(deferred_at=_ago(1))
    EventDao(db).upsert(ev)

    ingest_asset(db, ev, _image())  # 单图仍命中规则 4，事件留在等待队列
    stored = EventDao(db).get(ev.id)
    assert stored.status == EventStatus.DEFERRED
    assert stored.deferred_retries == 1


def test_archived_event_not_revived_by_ingest(db) -> None:
    ev = _deferred(title="过期等待", deferred_at=_ago(25))
    ev.status = EventStatus.ARCHIVED
    EventDao(db).upsert(ev)

    ingest_asset(db, ev, _image())
    ingest_asset(db, ev, _image())

    stored = EventDao(db).get(ev.id)
    assert stored.status == EventStatus.ARCHIVED  # 「不再尝试」：补录不复活归档事件
    assert stored.deferred_retries == 0
    assert len(MediaAssetDao(db).list_by_event(ev.id)) == 2  # 素材本身照常落库
