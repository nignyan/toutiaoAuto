"""数据回流编排（D15）：表现回填 + 多维分析 + 建议动作生成。

MVP 口径（产品文档 §4.7 + D3）：仅输出「建议动作」，人工确认/驳回/回滚，
不自动调整任何权重。与 producer/allocator/dispatcher 同构：错误类型 +
纯函数（build_report / generate_suggestions）+ 编排函数（record_performance /
analyze / decide_suggestion）。
"""

from datetime import datetime, timezone
from typing import Literal, NamedTuple

from pydantic import BaseModel

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
    PublishStatus,
    RefluxSuggestion,
    SuggestionKind,
    SuggestionStatus,
)

# 建议生成阈值（确定性规则，规格 D15 §3.1）：小样本/零分母不出建议
MIN_GROUP_SAMPLE = 2  # 参与比较的组样本量下限
MIN_RELATIVE_GAP = 0.30  # 最优组相对最差组的互动率提升下限
MIN_ABS_GAP = 1.0  # 互动率绝对差下限（百分点），过滤低基数噪声

HOUR_BUCKETS = ("00-06", "06-12", "12-18", "18-24")
TITLE_BUCKETS = ("≤15字", "16-25字", ">25字")

_TYPE_LABELS = {"video": "视频", "image_slideshow": "图集", "text": "图文"}

# 建议动作状态机（规格 D15 §2.2）：回滚回到待确认可再采纳（2026-09-16 拍板）
_SUGGESTION_TRANSITIONS: dict[str, tuple[SuggestionStatus, SuggestionStatus]] = {
    "confirm": (SuggestionStatus.PENDING, SuggestionStatus.CONFIRMED),
    "reject": (SuggestionStatus.PENDING, SuggestionStatus.REJECTED),
    "rollback": (SuggestionStatus.CONFIRMED, SuggestionStatus.PENDING),
}

SuggestionAction = Literal["confirm", "reject", "rollback"]


class RefluxError(Exception):
    """数据回流拒绝：kind 为 not_found / not_published / bad_status，API 层映射 404 / 409。"""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        super().__init__(message)


# ---- 分析响应模型（API 复用）----

class GroupStat(BaseModel):
    """一个分组的表现聚合。互动率/负反馈率 = 合计/总曝光×100，总曝光为 0 时取 0。"""

    key: str
    count: int
    avg_exposure: float
    avg_plays: float
    avg_completion_rate: float
    interaction_rate: float
    negative_rate: float


class AnalysisReport(BaseModel):
    """四维分析报告（规格 D15 §3）。"""

    record_count: int
    by_type: list[GroupStat]
    by_hour: list[GroupStat]
    by_vertical: list[GroupStat]
    by_title_len: list[GroupStat]


class _JoinedRow(NamedTuple):
    """表现记录 join 成品/发布时刻后的分析行。"""

    record: PerformanceRecord
    ptype: str
    vertical: str
    title: str
    hour: str | None  # published_at 无法解析时为 None，不参与时段分析


# ---- 纯函数：分桶与聚合 ----

def hour_bucket(published_at: str) -> str | None:
    """发布时刻（ISO，UTC 基准）→ 4 桶时段；空/非法时刻返回 None。"""
    if not published_at:
        return None
    try:
        dt = datetime.fromisoformat(published_at)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return HOUR_BUCKETS[dt.hour // 6]


def title_bucket(title: str) -> str:
    """标题字符数 → 3 桶（≤15 / 16-25 / >25）。"""
    n = len(title.strip())
    if n <= 15:
        return TITLE_BUCKETS[0]
    return TITLE_BUCKETS[1] if n <= 25 else TITLE_BUCKETS[2]


def _agg(rows: list[_JoinedRow]) -> tuple[float, float, float, float, float]:
    count = len(rows)
    total_exposure = sum(r.record.exposure for r in rows)
    avg_exposure = total_exposure / count
    avg_plays = sum(r.record.plays for r in rows) / count
    avg_completion = sum(r.record.completion_rate for r in rows) / count
    interaction_rate = sum(r.record.interactions for r in rows) / total_exposure * 100
    negative_rate = sum(r.record.negative for r in rows) / total_exposure * 100
    return avg_exposure, avg_plays, avg_completion, interaction_rate, negative_rate


def _group_stats(rows: list[_JoinedRow], key_of) -> list[GroupStat]:
    groups: dict[str, list[_JoinedRow]] = {}
    for row in rows:
        key = key_of(row)
        if key is None:
            continue
        groups.setdefault(key, []).append(row)
    stats = []
    for key, rs in groups.items():
        avg_exposure, avg_plays, avg_completion, interaction_rate, negative_rate = _agg(rs)
        stats.append(
            GroupStat(
                key=key,
                count=len(rs),
                avg_exposure=round(avg_exposure, 2),
                avg_plays=round(avg_plays, 2),
                avg_completion_rate=round(avg_completion, 2),
                interaction_rate=round(interaction_rate, 2),
                negative_rate=round(negative_rate, 2),
            )
        )
    # 稳定排序：样本量降序，同量按键名升序
    return sorted(stats, key=lambda s: (-s.count, s.key))


def build_report(
    records: list[PerformanceRecord],
    productions: dict[str, Production],
    published_ats: dict[str, str],
) -> AnalysisReport:
    """四维聚合（纯函数）：内容形态 / 发布时段 / 热点垂类 / 标题长度。"""
    rows: list[_JoinedRow] = []
    for rec in records:
        prod = productions.get(rec.production_id)
        if prod is None:  # 防御：回填守卫保证成品存在，理论不发生
            continue
        rows.append(
            _JoinedRow(
                record=rec,
                ptype=prod.production_type.value,
                vertical=prod.vertical or "通用",
                title=prod.title,
                hour=hour_bucket(published_ats.get(rec.production_id, "")),
            )
        )
    return AnalysisReport(
        record_count=len(rows),
        by_type=_group_stats(rows, lambda r: r.ptype),
        by_hour=_group_stats(rows, lambda r: r.hour),
        by_vertical=_group_stats(rows, lambda r: r.vertical),
        by_title_len=_group_stats(rows, lambda r: title_bucket(r.title)),
    )


# ---- 纯函数：建议生成 ----

def _best_worst(stats: list[GroupStat]) -> tuple[GroupStat, GroupStat] | None:
    """样本量达标的组内取互动率最优/最差；不满足比较条件返回 None。"""
    eligible = [s for s in stats if s.count >= MIN_GROUP_SAMPLE]
    if len(eligible) < 2:
        return None
    ranked = sorted(eligible, key=lambda s: -s.interaction_rate)
    best, worst = ranked[0], ranked[-1]
    if worst.interaction_rate <= 0:
        return None  # 零分母/零互动基数不出建议
    if best.interaction_rate - worst.interaction_rate < MIN_ABS_GAP:
        return None
    if best.interaction_rate / worst.interaction_rate - 1 < MIN_RELATIVE_GAP:
        return None
    return best, worst


def _make_suggestion(kind: SuggestionKind, best: GroupStat, worst: GroupStat) -> RefluxSuggestion:
    lift = round((best.interaction_rate / worst.interaction_rate - 1) * 100)
    best_label = _TYPE_LABELS.get(best.key, best.key)
    worst_label = _TYPE_LABELS.get(worst.key, worst.key)
    if kind == SuggestionKind.FORMAT:
        text = (
            f"「{best_label}」形态平均互动率 {best.interaction_rate:.1f}%，"
            f"高于「{worst_label}」的 {worst.interaction_rate:.1f}%；"
            f"建议后续优先 {best_label} 形态选题"
        )
    elif kind == SuggestionKind.TIMING:
        text = (
            f"{best.key} 时段发布的内容平均互动率最高（{best.interaction_rate:.1f}%），"
            f"建议优先在该时段发布"
        )
    else:  # VERTICAL
        text = (
            f"「{best.key}」垂类平均互动率最高（{best.interaction_rate:.1f}%），"
            f"建议提高该垂类选题占比"
        )
    return RefluxSuggestion(
        kind=kind,
        text=text,
        basis=(
            f"互动率对比：{best.key} {best.interaction_rate:.1f}%（n={best.count}）"
            f" vs {worst.key} {worst.interaction_rate:.1f}%（n={worst.count}）"
        ),
        impact=f"预期互动率相对提升约 {lift}%",
    )


def generate_suggestions(report: AnalysisReport) -> list[RefluxSuggestion]:
    """由分析报告确定性生成建议动作（每维度至多 1 条，规格 D15 §3.1）。"""
    suggestions: list[RefluxSuggestion] = []
    pairs = (
        (SuggestionKind.FORMAT, report.by_type),
        (SuggestionKind.TIMING, report.by_hour),
        (SuggestionKind.VERTICAL, report.by_vertical),
    )
    for kind, stats in pairs:
        if kind == SuggestionKind.VERTICAL:
            stats = [s for s in stats if s.key != "通用"]  # 通用不参与垂类建议
        compared = _best_worst(stats)
        if compared is not None:
            suggestions.append(_make_suggestion(kind, *compared))
    return suggestions


# ---- 编排 ----

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_performance(db: DB, record: PerformanceRecord) -> PerformanceRecord:
    """回填单成品表现数据（upsert 取最新）：仅已发布成品可回填。"""
    if ProductionDao(db).get(record.production_id) is None:
        raise RefluxError("not_found", f"成品 {record.production_id} 不存在")
    item = PublishQueueDao(db).get_by_production(record.production_id)
    if item is None or item.status != PublishStatus.PUBLISHED:
        state = "无队列项" if item is None else f"状态为 {item.status.value}"
        raise RefluxError("not_published", f"成品未发布（{state}），仅 published 可回填")
    record.account_id = item.account_id  # 冗余落库，免联查
    RefluxRecordDao(db).upsert(record)
    persisted = RefluxRecordDao(db).get_by_production(record.production_id)
    assert persisted is not None  # upsert 刚写入
    return persisted


def compute_report(db: DB) -> AnalysisReport:
    """汇总当前表现数据并四维聚合（只读，供 GET 报告与 analyze 复用）。"""
    records = RefluxRecordDao(db).list()
    productions = {p.id: p for p in ProductionDao(db).list()}
    published_ats = {
        item.production_id: item.published_at for item in PublishQueueDao(db).list()
    }
    return build_report(records, productions, published_ats)


def analyze(db: DB) -> AnalysisReport:
    """重算分析报告并重建待确认建议：pending 全量替换，已决策项保留作历史。"""
    report = compute_report(db)
    suggestions = generate_suggestions(report)
    sug_dao = RefluxSuggestionDao(db)
    with db.transaction() as conn:  # 重建原子：删旧 pending 与插新建议同事务
        sug_dao.delete_pending_with(conn)
        for sug in suggestions:
            sug_dao.insert_with(conn, sug)
    return report


def decide_suggestion(db: DB, sug_id: str, action: SuggestionAction) -> RefluxSuggestion:
    """建议动作决策：confirm / reject / rollback（回滚回到待确认，可再采纳）。"""
    sug = RefluxSuggestionDao(db).get(sug_id)
    if sug is None:
        raise RefluxError("not_found", f"建议 {sug_id} 不存在")
    source, target = _SUGGESTION_TRANSITIONS[action]
    if sug.status != source:
        raise RefluxError(
            "bad_status",
            f"建议状态为 {sug.status.value}，仅 {source.value} 可执行 {action}",
        )
    # 回滚回到 pending 保留原决策时间；确认/驳回记首次决策时间
    decided_at = None if target == SuggestionStatus.PENDING else _utc_now()
    RefluxSuggestionDao(db).update_status(sug_id, target, decided_at=decided_at)
    persisted = RefluxSuggestionDao(db).get(sug_id)
    assert persisted is not None  # 刚更新
    return persisted
