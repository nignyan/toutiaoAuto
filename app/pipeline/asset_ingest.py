"""素材入库与暂缓事件重评估（D8）。

素材双入口之一：手动补录 / 编排层批量入库统一走 ingest_asset；
密度与清晰度在入库时落库（值由调用方提供），授权默认 pending（D2）。
"""

from dataclasses import dataclass

from app.daos import DB, EventDao, MediaAssetDao
from app.models import Event, EventStatus, MediaAsset
from app.pipeline.format_decision import ContentFormat, FormatDecision, decide_format


@dataclass(frozen=True)
class IngestReport:
    """一次素材入库的结果。"""

    asset: MediaAsset
    decision: FormatDecision
    event_status_changed: bool


def ingest_asset(db: DB, event: Event, asset: MediaAsset) -> IngestReport:
    """落库素材；若事件处于素材等待队列（DEFERRED），入库后重评估形态。"""
    asset.event_id = event.id
    asset_dao = MediaAssetDao(db)
    asset_dao.insert(asset)

    decision = decide_format(asset_dao.list_by_event(event.id))
    changed = False
    if event.status == EventStatus.DEFERRED:
        event.deferred_retries += 1  # 等待期间补录尝试计数（「已重试 n 次」）
        if decision.content_format != ContentFormat.DEFER:
            event.status = EventStatus.READY
            changed = True
        EventDao(db).upsert(event)  # 计数与状态转换一次落库

    return IngestReport(asset=asset, decision=decision, event_status_changed=changed)
