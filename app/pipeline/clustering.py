"""事件聚类：标题 bigram Jaccard 相似度匹配（D7）。

纯函数、不碰数据库：新建/并入只改内存中的 Event 对象，
素材落库由编排层（collect 端点）调用 asset_ingest 完成（见规格 §6.1）。
"""

from pydantic import BaseModel

from app.models import Event, EventStatus, MediaAsset, TimelineEntry
from app.pipeline.collector import RawSignal

DEFAULT_THRESHOLD = 0.35


def title_bigrams(title: str) -> set[str]:
    """去空白后的字符 bigram 集合；单字符标题退化为该字符本身。"""
    chars = [c for c in title if not c.isspace()]
    if len(chars) == 1:
        return {chars[0]}
    return {a + b for a, b in zip(chars, chars[1:])}


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard 相似度；两集合皆空时返回 0。"""
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


class ClusterAssignment(BaseModel):
    """一条信号的聚类归属，供规则追溯。"""

    signal_title: str
    event_id: str
    matched: bool  # True=并入已有事件；False=新建事件


class ClusterReport(BaseModel):
    """一次聚类批次的结果。"""

    created: list[Event] = []
    updated: list[Event] = []
    assignments: list[ClusterAssignment] = []


def _timeline_entry(sig: RawSignal) -> TimelineEntry:
    return TimelineEntry(
        ts=sig.published_at,
        title=sig.title,
        source=sig.source,
        heat=sig.heat,
        source_url=sig.source_url,
    )


def _best_match(sig: RawSignal, pool: list[Event], threshold: float) -> Event | None:
    sig_grams = title_bigrams(sig.title)
    best: Event | None = None
    best_sim = 0.0
    for ev in pool:
        sim = jaccard(sig_grams, title_bigrams(ev.title))
        if sim > best_sim:
            best, best_sim = ev, sim
    return best if best is not None and best_sim >= threshold else None


def _predicted_status(pending_assets: list) -> EventStatus:
    """形态判定预判（纯函数版）：有可用素材 → READY，否则规则 4 → DEFERRED。"""
    usable = [
        a
        for a in pending_assets
        if isinstance(a, MediaAsset) and a.is_usable
    ]
    return EventStatus.READY if usable else EventStatus.DEFERRED


def cluster_signals(
    signals: list[RawSignal],
    existing_events: list[Event] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> ClusterReport:
    """按标题相似度把信号并入已有事件或新建事件（自上而下、先到先得）。"""
    report = ClusterReport()
    existing = list(existing_events) if existing_events else []
    pool = list(existing)
    created_ids: set[str] = set()
    updated_ids: set[str] = set()

    for sig in signals:
        target = _best_match(sig, pool, threshold)
        if target is None:
            ev = Event(
                title=sig.title,
                score=sig.heat,
                status=_predicted_status(sig.pending_assets),
                timeline=[_timeline_entry(sig)],
            )
            pool.append(ev)
            created_ids.add(ev.id)
            report.created.append(ev)
            report.assignments.append(
                ClusterAssignment(signal_title=sig.title, event_id=ev.id, matched=False)
            )
            continue

        # 并入：score 取 max；timeline 追加（非空 source_url 去重）；标题保持首条不变
        target.score = max(target.score, sig.heat)
        entry = _timeline_entry(sig)
        if not sig.source_url or sig.source_url not in {t.source_url for t in target.timeline}:
            target.timeline.append(entry)
        if target.id not in created_ids:
            updated_ids.add(target.id)
        report.assignments.append(
            ClusterAssignment(signal_title=sig.title, event_id=target.id, matched=True)
        )

    report.updated = [ev for ev in existing if ev.id in updated_ids]
    return report
