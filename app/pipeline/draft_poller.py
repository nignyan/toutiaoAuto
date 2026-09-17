"""发布确认定时轮询（D16 后续）：扫描 draft_ready 图文项，命中头条「已发布
内容列表」则自动转 published，消除「运营在头条点发布后需回系统手动 confirm」。

视频半自动同样走草稿箱（D20），但确认保留人工 confirm：list/v2 对视频的
覆盖未真机验证，轮询暂排除视频，验证可覆盖后再放开。
"""

import asyncio
import os

from app.daos import DB, AccountDao, ProductionDao, PublishQueueDao
from app.models import ProductionType, PublishStatus
from app.pipeline.dispatcher import _mark_published


def poll_draft_confirms(db: DB, adapter) -> list[str]:
    """扫描全部 draft_ready 图文项，命中已发布列表则自动转 published（幂等）。

    按账号分组只查一次已发布列表；命中判定=标题归一化精确相等；只取 draft_ready，
    已确认项下一轮不再命中。
    """
    confirmed: list[str] = []
    items = PublishQueueDao(db).list(status=PublishStatus.DRAFT_READY)

    by_account: dict[str, list] = {}
    for item in items:
        by_account.setdefault(item.account_id, []).append(item)

    for account_id, acct_items in by_account.items():
        account = AccountDao(db).get(account_id)
        if account is None:
            continue
        titles = {t.strip() for t in adapter.list_published_titles(account)}
        for item in acct_items:
            prod = ProductionDao(db).get(item.production_id)
            # D20：视频 draft_ready 暂不走轮询，确认以人工 confirm 为准（list/v2 视频覆盖未验证）
            if prod is None or prod.production_type == ProductionType.VIDEO:
                continue
            if prod.title.strip() in titles:
                _mark_published(db, item, "轮询自动确认已发布")
                confirmed.append(item.id)
    return confirmed


def poller_interval() -> int:
    """轮询间隔（秒），环境变量 AUTO_CONFIRM_INTERVAL 可调，默认 300。"""
    raw = os.environ.get("AUTO_CONFIRM_INTERVAL", "300")
    try:
        return max(1, int(raw))
    except ValueError:
        return 300


async def run_poller(db: DB, adapter, stop_event: asyncio.Event, interval_s: int) -> None:
    """后台轮询循环：每 interval_s 扫一次；stop_event 置位后退出。

    Playwright 为同步 API，明细查询放进 asyncio.to_thread 避免阻塞事件循环。
    """
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(poll_draft_confirms, db, adapter)
        except Exception:  # noqa: BLE001 单轮异常不中断循环，下轮重试
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            pass