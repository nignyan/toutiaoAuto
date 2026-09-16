"""生产编排（§7）：READY事件 → 模板生成 → 自动质检 → Production落库。

事件状态机 READY → PRODUCED 一次性，重复生产拒绝；形态判定实时复跑，
素材变化后口径始终最新；跨表更新走 db.transaction 保持原子性。
"""

from dataclasses import dataclass, field

from app.daos import DB, EventDao, MediaAssetDao, ProductionDao
from app.models import EventStatus, Production, ProductionType
from app.pipeline.composer import ContentComposer, TemplateComposer, resolve_rule
from app.pipeline.format_decision import ContentFormat, decide_format
from app.pipeline.quality_check import check_quality

_FORMAT_TO_TYPE = {
    ContentFormat.VIDEO: ProductionType.VIDEO,
    ContentFormat.IMAGE_SLIDESHOW: ProductionType.IMAGE_SLIDESHOW,
    ContentFormat.TEXT: ProductionType.TEXT,
}


class ProducerError(Exception):
    """生产拒绝：kind 为 not_found / not_ready，API 层映射 404 / 409。"""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        super().__init__(message)


@dataclass(frozen=True)
class SkippedEntry:
    """批量生产中被跳过的事件与原因。"""

    event_id: str
    reason: str


@dataclass(frozen=True)
class ProduceAllReport:
    """批量生产结果：单事件失败不影响其余（与 D6 容错同构）。"""

    produced: list[Production] = field(default_factory=list)
    skipped: list[SkippedEntry] = field(default_factory=list)


def produce_for_event(
    db: DB, event_id: str, composer: ContentComposer | None = None
) -> Production:
    """对单个 READY 事件执行生产；落库成品并将事件转为 PRODUCED。"""
    composer = composer if composer is not None else TemplateComposer()
    event_dao = EventDao(db)
    ev = event_dao.get(event_id)
    if ev is None:
        raise ProducerError("not_found", f"事件 {event_id} 不存在")
    if ev.status != EventStatus.READY:
        raise ProducerError(
            "not_ready", f"事件 {event_id} 状态为 {ev.status.value}，不可生产"
        )

    assets = MediaAssetDao(db).list_by_event(event_id)
    usable = [a for a in assets if a.is_usable]
    decision = decide_format(assets)  # 实时复跑，不读历史判定
    if decision.content_format == ContentFormat.DEFER:
        raise ProducerError(
            "not_ready", f"事件 {event_id} 形态判定为 DEFER，与 READY 状态矛盾"
        )

    draft = composer.compose(ev, usable, decision)
    quality = check_quality(ev, usable)

    # 防御性一致性：Draft 素材 id必须全部存在于编排骨箱（usable 子集）
    known = {a.id for a in usable}
    unknown = [i for i in draft.ordered_asset_ids if i not in known]
    if unknown or (draft.cover_asset_id and draft.cover_asset_id not in known):
        raise ValueError(
            f"composer 产出的素材 id 超出编排骨箱：{unknown or draft.cover_asset_id}"
        )

    prod = Production(
        event_id=ev.id,
        production_type=_FORMAT_TO_TYPE[decision.content_format],
        asset_ids=draft.ordered_asset_ids,
        title=draft.title,
        body=draft.body,
        cover_asset_id=draft.cover_asset_id,
        rule=resolve_rule(decision, usable),
        composer=getattr(composer, "name", "template"),
        checks=quality.checks,
        vetoes=quality.vetoes,
        quality_score=quality.score,
        quality_status=quality.status,
    )

    with db.transaction() as conn:  # 成品落库与事件状态跨表原子
        ProductionDao(db).insert_with(conn, prod)
        ev.status = EventStatus.PRODUCED
        event_dao.upsert_with(conn, ev)
    return prod


def produce_all(
    db: DB, composer: ContentComposer | None = None
) -> ProduceAllReport:
    """批量生产全部 READY 事件（score 降序），失败事件进 skipped 不中断。"""
    produced: list[Production] = []
    skipped: list[SkippedEntry] = []
    for ev in EventDao(db).list_all(status=EventStatus.READY):
        try:
            produced.append(produce_for_event(db, ev.id, composer))
        except Exception as exc:  # noqa: BLE001 单事件容错
            reason = exc.kind if isinstance(exc, ProducerError) else f"error: {exc}"
            skipped.append(SkippedEntry(event_id=ev.id, reason=reason))
    return ProduceAllReport(produced=produced, skipped=skipped)
