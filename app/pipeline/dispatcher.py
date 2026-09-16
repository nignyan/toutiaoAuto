"""发布执行编排（D13）：队列状态流转 + RPA 填稿联动。

dispatch_item 把一条队列项派发到 PublishAdapter：由 Production 构建标准内容包，
适配器结果（含异常）统一落库为队列状态；skip/unskip/confirm 为受守卫约束的
纯状态流转。与 producer/allocator 同构：错误类型 + 纯函数 + 编排函数。
"""

from app.daos import DB, AccountDao, ProductionDao, PublishQueueDao
from app.models import Production, PublishQueueItem, PublishStatus
from app.publish.adapter import (
    ContentFormat,
    ContentPackage,
    PublishAdapter,
    PublishResult,
)
from app.publish.adapter import (
    PublishStatus as AdapterPublishStatus,
)

# 派发允许的来源状态：failed 可重试；draft_ready 拒绝（避免重复草稿）
_DISPATCHABLE = (PublishStatus.PENDING, PublishStatus.FAILED)

# 适配器结果 → 队列状态映射（规格 D13 §4）
_RESULT_MAP = {
    AdapterPublishStatus.DRAFT_READY: PublishStatus.DRAFT_READY,
    AdapterPublishStatus.PUBLISHED: PublishStatus.PUBLISHED,
    AdapterPublishStatus.NEEDS_LOGIN: PublishStatus.FAILED,
    AdapterPublishStatus.FAILED: PublishStatus.FAILED,
}


class DispatchError(Exception):
    """发布执行拒绝：kind 为 not_found / bad_status，API 层映射 404 / 409。"""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        super().__init__(message)


def map_result(result: PublishResult) -> PublishStatus:
    """适配器结果映射为队列状态（纯函数）。"""
    return _RESULT_MAP[result.status]


def build_package(production: Production) -> ContentPackage:
    """由成品构建标准内容包（纯函数）。

    MVP 出界说明（规格 D13 §1）：素材均为远程 URL、无本地媒体文件，
    内容包按图文形态只填标题/正文/标签；媒体上传列演进项。
    """
    return ContentPackage(
        title=production.title,
        body=production.body,
        format=ContentFormat.ARTICLE,
    )


def _load_item(db: DB, item_id: str) -> PublishQueueItem:
    item = PublishQueueDao(db).get(item_id)
    if item is None:
        raise DispatchError("not_found", f"队列项 {item_id} 不存在")
    return item


def dispatch_item(db: DB, item_id: str, adapter: PublishAdapter) -> PublishQueueItem:
    """派发单条队列项：内容包投递到适配器，结果状态与原因落库。"""
    item = _load_item(db, item_id)
    if item.status not in _DISPATCHABLE:
        raise DispatchError(
            "bad_status",
            f"队列项状态为 {item.status.value}，仅 pending/failed 可派发",
        )

    prod = ProductionDao(db).get(item.production_id)
    account = AccountDao(db).get(item.account_id)
    if prod is None or account is None:  # 防御：1:1 约束下理论不发生
        return _record_failure(db, item, "成品或账号缺失，无法构建内容包")

    try:
        package = build_package(prod)
    except Exception as exc:  # noqa: BLE001 内容包校验失败（如正文为空）按失败落库
        return _record_failure(db, item, f"error: {exc}")

    try:
        result = adapter.publish(package, account)
    except Exception as exc:  # noqa: BLE001 适配器异常（未装 Playwright/页面异常）不冒泡
        return _record_failure(db, item, f"error: {exc}")

    queue_status = map_result(result)
    publish_result = f"[{result.status.value}] {result.message}"
    PublishQueueDao(db).update_status(item.id, queue_status, publish_result)
    item.status = queue_status
    item.publish_result = publish_result
    return item


def _record_failure(db: DB, item: PublishQueueItem, message: str) -> PublishQueueItem:
    PublishQueueDao(db).update_status(
        item.id, PublishStatus.FAILED, publish_result=f"[failed] {message}"
    )
    item.status = PublishStatus.FAILED
    item.publish_result = f"[failed] {message}"
    return item


def skip_item(db: DB, item_id: str) -> PublishQueueItem:
    """跳过队列项（可撤销）：仅 pending 可跳过。"""
    item = _load_item(db, item_id)
    if item.status != PublishStatus.PENDING:
        raise DispatchError(
            "bad_status", f"队列项状态为 {item.status.value}，仅 pending 可跳过"
        )
    PublishQueueDao(db).update_status(item.id, PublishStatus.SKIPPED)
    item.status = PublishStatus.SKIPPED
    return item


def unskip_item(db: DB, item_id: str) -> PublishQueueItem:
    """撤销跳过：仅 skipped 可回到 pending。"""
    item = _load_item(db, item_id)
    if item.status != PublishStatus.SKIPPED:
        raise DispatchError(
            "bad_status", f"队列项状态为 {item.status.value}，仅 skipped 可撤销"
        )
    PublishQueueDao(db).update_status(item.id, PublishStatus.PENDING)
    item.status = PublishStatus.PENDING
    return item


def confirm_published(db: DB, item_id: str) -> PublishQueueItem:
    """人工确认已发布（头条后台点完发布后回系统记录）：仅 draft_ready 可确认。"""
    item = _load_item(db, item_id)
    if item.status != PublishStatus.DRAFT_READY:
        raise DispatchError(
            "bad_status", f"队列项状态为 {item.status.value}，仅 draft_ready 可确认发布"
        )
    PublishQueueDao(db).update_status(
        item.id, PublishStatus.PUBLISHED, publish_result="人工确认已发布"
    )
    item.status = PublishStatus.PUBLISHED
    item.publish_result = "人工确认已发布"
    return item
