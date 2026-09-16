"""素材等待队列超时归档（产品设计 §4.4）。

判定为暂缓生产的事件进入素材等待队列持续尝试获取素材；超过 24 小时
仍未凑齐有效素材则归档，不再尝试（热点时效已失效，继续保留只会让
等待队列膨胀）。触发沿用 D8/D9/D10 方案一：仅 API 手动触发，无定时器。
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.daos import DB, EventDao
from app.models import Event, EventStatus

WAIT_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class TimeoutArchiveReport:
    """一次超时归档的结果。"""

    archived: list[Event] = field(default_factory=list)
    checked: int = 0  # 扫描的等待中（DEFERRED）事件数


def _parse_ts(raw: str) -> datetime:
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo is None:  # 存量库可能出现无时区时间串，按 UTC 处理
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def wait_started(ev: Event) -> datetime:
    """等待起点：deferred_at 优先，为空（存量 deferred 数据）回退 created_at。"""
    return _parse_ts(ev.deferred_at or ev.created_at)


def expired_deferred(
    events: list[Event], now: datetime, window: timedelta = WAIT_WINDOW
) -> list[Event]:
    """纯函数：等待时长严格超过窗口的 DEFERRED 事件（口径「超过 24 小时」）。"""
    return [
        ev
        for ev in events
        if ev.status == EventStatus.DEFERRED and now - wait_started(ev) > window
    ]


def archive_expired(db: DB, now: datetime | None = None) -> TimeoutArchiveReport:
    """把等待队列中超时的事件归档（DEFERRED → ARCHIVED），批量落库走事务。"""
    now = now or datetime.now(timezone.utc)
    waiting = EventDao(db).list_all(status=EventStatus.DEFERRED)
    expired = expired_deferred(waiting, now)
    if expired:
        event_dao = EventDao(db)
        with db.transaction() as conn:
            for ev in expired:
                ev.status = EventStatus.ARCHIVED
                event_dao.upsert_with(conn, ev)
    return TimeoutArchiveReport(archived=expired, checked=len(waiting))
