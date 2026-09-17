"""发布执行编排（D13）：队列状态流转 + RPA 填稿联动。

dispatch_item 把一条队列项派发到 PublishAdapter：由 Production 构建标准内容包，
适配器结果（含异常）统一落库为队列状态；skip/unskip/confirm 为受守卫约束的
纯状态流转。与 producer/allocator 同构：错误类型 + 纯函数 + 编排函数。
"""

from datetime import datetime, timezone

from app.daos import DB, AccountDao, ProductionDao, PublishQueueDao
from app.models import Production, ProductionType, PublishQueueItem, PublishStatus
from app.pipeline.media_localizer import (
    LocalizationError,
    LocalMedia,
    localize_media,
)
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DispatchError(Exception):
    """发布执行拒绝：kind 为 not_found / bad_status，API 层映射 404 / 409。"""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        super().__init__(message)


def map_result(result: PublishResult) -> PublishStatus:
    """适配器结果映射为队列状态（纯函数）。"""
    return _RESULT_MAP[result.status]


# 生产形态 → 投递内容包形态的显式映射（生产侧 ProductionType 与投递侧
# ContentFormat 命名不同，此处单点对齐，不合并两套枚举）。
_FORMAT_MAP = {
    ProductionType.VIDEO: ContentFormat.VIDEO,
    ProductionType.IMAGE_SLIDESHOW: ContentFormat.ARTICLE,  # 图集 MVP 退化为图文
    ProductionType.TEXT: ContentFormat.ARTICLE,
}


def build_package(
    production: Production, local_media: LocalMedia | None = None
) -> ContentPackage:
    """由成品构建标准内容包（纯函数）。

    按 production_type 决定内容包形态；视频本地媒体文件来自 local_media
    （素材本地化产物或调用方显式注入）。视频缺 video_path 会触发
    ContentPackage 校验失败，由调用方落 failed。
    """
    fmt = _FORMAT_MAP[production.production_type]
    media = local_media or LocalMedia()
    return ContentPackage(
        title=production.title,
        body=production.body,
        format=fmt,
        video_path=media.video_path,
        cover_path=media.cover_path,
        image_paths=media.image_paths,
    )


def _load_item(db: DB, item_id: str) -> PublishQueueItem:
    item = PublishQueueDao(db).get(item_id)
    if item is None:
        raise DispatchError("not_found", f"队列项 {item_id} 不存在")
    return item


def dispatch_item(
    db: DB, item_id: str, adapter: PublishAdapter, local_media: LocalMedia | None = None
) -> PublishQueueItem:
    """派发单条队列项：内容包投递到适配器，结果状态与原因落库。

    视频半自动同样走草稿箱（D20 勘误：视频编辑页有「存草稿」按钮），
    与图文同口径：draft_ready → 人工在头条后台点发布。系统内直达发布
    仍走 dispatch_item_now（/publish-now，强制点发布）。
    """
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
    return _dispatch_with(db, item, prod, account, adapter, local_media)


def dispatch_item_now(
    db: DB, item_id: str, adapter: PublishAdapter, local_media: LocalMedia | None = None
) -> PublishQueueItem:
    """本系统触发视频发布（系统内直达发布的保留入口）。

    仅 pending 且视频形态可发布；内部强制 auto_publish=True 直接点发布，
    复用 _dispatch_with 投递逻辑。半自动审核走 dispatch_item 草稿箱链路（D20）。
    """
    item = _load_item(db, item_id)
    if item.status != PublishStatus.PENDING:
        raise DispatchError(
            "bad_status", f"队列项状态为 {item.status.value}，仅 pending 可本系统发布"
        )
    prod = ProductionDao(db).get(item.production_id)
    account = AccountDao(db).get(item.account_id)
    if prod is None or account is None:
        return _record_failure(db, item, "成品或账号缺失，无法构建内容包")
    if prod.production_type != ProductionType.VIDEO:
        raise DispatchError("bad_status", "本系统发布仅用于视频链路")
    account = account.model_copy(update={"auto_publish": True})
    return _dispatch_with(db, item, prod, account, adapter, local_media)


def _dispatch_with(
    db: DB,
    item: PublishQueueItem,
    prod: Production,
    account,
    adapter: PublishAdapter,
    local_media: LocalMedia | None = None,
) -> PublishQueueItem:
    """构建内容包并投递适配器，结果落库（dispatch_item / dispatch_item_now 共用）。"""
    if local_media is None and prod.production_type == ProductionType.VIDEO:
        # 素材本地化：视频派发时自动下载远程素材；失败落 failed（原因可见），
        # 不冒泡为 5xx；调用方显式传入 local_media 时跳过下载。
        try:
            local_media = localize_media(db, prod)
        except LocalizationError as exc:
            return _record_failure(db, item, f"素材本地化失败: {exc}")

    try:
        package = build_package(prod, local_media)
    except Exception as exc:  # noqa: BLE001 内容包校验失败（如正文为空）按失败落库
        return _record_failure(db, item, f"error: {exc}")

    try:
        result = adapter.publish(package, account)
    except Exception as exc:  # noqa: BLE001 适配器异常（未装 Playwright/页面异常）不冒泡
        return _record_failure(db, item, f"error: {exc}")

    queue_status = map_result(result)
    publish_result = f"[{result.status.value}] {result.message}"
    published_at = _utc_now() if queue_status == PublishStatus.PUBLISHED else None
    PublishQueueDao(db).update_status(
        item.id, queue_status, publish_result, published_at=published_at
    )
    item.status = queue_status
    item.publish_result = publish_result
    if published_at is not None:
        item.published_at = published_at
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


def _mark_published(db: DB, item: PublishQueueItem, reason: str) -> PublishQueueItem:
    """把队列项标为已发布并落 published_at（人工确认 / 轮询自动确认共用）。"""
    published_at = _utc_now()
    PublishQueueDao(db).update_status(
        item.id,
        PublishStatus.PUBLISHED,
        publish_result=reason,
        published_at=published_at,
    )
    item.status = PublishStatus.PUBLISHED
    item.publish_result = reason
    item.published_at = published_at
    return item


def confirm_published(db: DB, item_id: str) -> PublishQueueItem:
    """人工确认已发布（头条后台点完发布后回系统记录）：仅 draft_ready 可确认。"""
    item = _load_item(db, item_id)
    if item.status != PublishStatus.DRAFT_READY:
        raise DispatchError(
            "bad_status", f"队列项状态为 {item.status.value}，仅 draft_ready 可确认发布"
        )
    return _mark_published(db, item, "人工确认已发布")
