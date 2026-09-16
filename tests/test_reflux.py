"""数据回流测试：表现记录 upsert、建议状态机、存量库补列、分析纯函数与编排。"""

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
from app.pipeline.reflux import (
    MIN_GROUP_SAMPLE,
    MIN_RELATIVE_GAP,
    AnalysisReport,
    RefluxError,
    analyze,
    build_report,
    decide_suggestion,
    generate_suggestions,
    hour_bucket,
    record_performance,
    title_bucket,
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


# ---- 分析纯函数：分桶 ----

class TestBuckets:
    @pytest.mark.parametrize(
        ("hour", "bucket"),
        [(0, "00-06"), (5, "00-06"), (6, "06-12"), (11, "06-12"),
         (12, "12-18"), (17, "12-18"), (18, "18-24"), (23, "18-24")],
    )
    def test_hour_bucket_boundaries(self, hour, bucket) -> None:
        ts = f"2026-09-16T{hour:02d}:30:00+00:00"
        assert hour_bucket(ts) == bucket

    def test_hour_bucket_converts_to_utc(self) -> None:
        # 北京时间 08:30 = UTC 00:30 → 00-06 桶
        assert hour_bucket("2026-09-16T08:30:00+08:00") == "00-06"

    @pytest.mark.parametrize("ts", ["", "not-a-time"])
    def test_hour_bucket_invalid_returns_none(self, ts) -> None:
        assert hour_bucket(ts) is None

    @pytest.mark.parametrize(
        ("title", "bucket"),
        [("一" * 15, "≤15字"), ("一" * 16, "16-25字"),
         ("一" * 25, "16-25字"), ("一" * 26, ">25字")],
    )
    def test_title_bucket(self, title, bucket) -> None:
        assert title_bucket(title) == bucket


# ---- 分析纯函数：聚合与建议 ----

def _seed_published(db: DB, production_id: str, ptype: ProductionType, published_at: str,
                    vertical: str = "", title: str = "某地突发山火，救援进行中") -> None:
    _production(db, production_id, production_type=ptype, vertical=vertical, title=title)
    _published_queue(db, production_id, published_at=published_at)


def _report_with(rows: list[tuple[str, ProductionType, str, str, dict]]) -> AnalysisReport:
    """直接构造 build_report 输入：rows = (pid, ptype, published_at, vertical, metrics)。"""
    productions: dict[str, Production] = {}
    records: list[PerformanceRecord] = []
    published_ats: dict[str, str] = {}
    for pid, ptype, published_at, vertical, m in rows:
        productions[pid] = Production(
            id=pid, event_id="ev", vertical=vertical, production_type=ptype, title="标题"
        )
        records.append(_record(pid, **m))
        published_ats[pid] = published_at
    return build_report(records, productions, published_ats)


class TestBuildReport:
    def test_aggregates_known_numbers(self) -> None:
        report = _report_with([
            ("p1", ProductionType.TEXT, "2026-09-16T10:00:00+00:00", "", dict(
                exposure=1000, interactions=100, plays=500, completion_rate=40.0, negative=10)),
            ("p2", ProductionType.TEXT, "2026-09-16T11:00:00+00:00", "", dict(
                exposure=1000, interactions=50, plays=700, completion_rate=60.0, negative=0)),
            ("p3", ProductionType.VIDEO, "2026-09-16T20:00:00+00:00", "社会", dict(
                exposure=500, interactions=5, plays=400, completion_rate=50.0, negative=5)),
        ])
        assert report.record_count == 3
        by_type = {g.key: g for g in report.by_type}
        assert by_type["text"].count == 2
        assert by_type["text"].avg_exposure == 1000.0
        assert by_type["text"].avg_plays == 600.0
        assert by_type["text"].avg_completion_rate == 50.0
        assert by_type["text"].interaction_rate == 7.5  # 150/2000
        assert by_type["text"].negative_rate == 0.5  # 10/2000
        assert by_type["video"].interaction_rate == 1.0  # 5/500
        # 时段：p1/p2 → 06-12 桶，p3 → 18-24 桶
        by_hour = {g.key: g for g in report.by_hour}
        assert by_hour["06-12"].count == 2
        assert by_hour["18-24"].count == 1
        # 垂类：空串归「通用」
        by_vertical = {g.key: g for g in report.by_vertical}
        assert by_vertical["通用"].count == 2
        assert by_vertical["社会"].count == 1

    def test_unparsable_published_at_excluded_from_hour_only(self) -> None:
        report = _report_with([
            ("p1", ProductionType.TEXT, "", "", dict(exposure=100, interactions=1)),
        ])
        assert report.record_count == 1
        assert report.by_hour == []
        assert report.by_type[0].count == 1  # 其他维度不受影响


class TestGenerateSuggestions:
    def _format_pair(self, gap: float) -> list[tuple]:
        """两条 text + 两条 video，互动率按 gap 拉开。"""
        hi = 200
        lo = round(200 / (1 + gap)) if gap < 100 else 2

        def row(pid: str, ptype: ProductionType, hour: int) -> tuple:
            return (pid, ptype, f"2026-09-16T{hour:02d}:00:00+00:00", "",
                    dict(exposure=1000, interactions=hi if ptype == ProductionType.TEXT else lo))

        return [
            row("t1", ProductionType.TEXT, 10),
            row("t2", ProductionType.TEXT, 11),
            row("v1", ProductionType.VIDEO, 20),
            row("v2", ProductionType.VIDEO, 21),
        ]

    def test_format_suggestion_triggered_on_clear_gap(self) -> None:
        report = _report_with(self._format_pair(0.5))  # 图文 20% vs 视频 ~13.3%
        sugs = generate_suggestions(report)
        fmt = [s for s in sugs if s.kind == SuggestionKind.FORMAT]
        assert len(fmt) == 1
        assert fmt[0].status == SuggestionStatus.PENDING
        assert "图文" in fmt[0].text
        assert "n=2" in fmt[0].basis
        assert fmt[0].impact.startswith("预期互动率")

    def test_no_suggestion_when_sample_below_min(self) -> None:
        rows = self._format_pair(0.5)[:3]  # 视频组只剩 1 条 < MIN_GROUP_SAMPLE
        report = _report_with(rows)
        assert all(s.kind != SuggestionKind.FORMAT for s in generate_suggestions(report))

    def test_no_suggestion_when_gap_below_threshold(self) -> None:
        report = _report_with(self._format_pair(0.1))  # 差距 10% < 30%
        assert all(s.kind != SuggestionKind.FORMAT for s in generate_suggestions(report))

    def test_no_suggestion_when_worst_rate_zero(self) -> None:
        rows = self._format_pair(0.5)
        for pid, _, _, _, m in rows:
            if pid.startswith("v"):
                m["interactions"] = 0
        report = _report_with(rows)
        assert all(s.kind != SuggestionKind.FORMAT for s in generate_suggestions(report))

    def test_timing_suggestion_generated(self) -> None:
        rows = []
        for i in range(2):
            rows.append((f"a{i}", ProductionType.TEXT, f"2026-09-16T0{i}:00:00+00:00", "",
                         dict(exposure=1000, interactions=200)))
            rows.append((f"b{i}", ProductionType.TEXT, f"2026-09-16T2{i}:00:00+00:00", "",
                         dict(exposure=1000, interactions=100)))
        sugs = generate_suggestions(_report_with(rows))
        timing = [s for s in sugs if s.kind == SuggestionKind.TIMING]
        assert len(timing) == 1
        assert "00-06" in timing[0].text  # 00-06 桶互动率 20% 高于 20-24 桶 10%

    def test_vertical_suggestion_excludes_generic(self) -> None:
        rows = [
            ("s1", ProductionType.TEXT, "2026-09-16T10:00:00+00:00", "社会",
             dict(exposure=1000, interactions=200)),
            ("s2", ProductionType.TEXT, "2026-09-16T11:00:00+00:00", "社会",
             dict(exposure=1000, interactions=200)),
            ("k1", ProductionType.TEXT, "2026-09-16T12:00:00+00:00", "科技",
             dict(exposure=1000, interactions=100)),
            ("k2", ProductionType.TEXT, "2026-09-16T13:00:00+00:00", "科技",
             dict(exposure=1000, interactions=100)),
            ("g1", ProductionType.TEXT, "2026-09-16T14:00:00+00:00", "",
             dict(exposure=1000, interactions=1)),
        ]
        sugs = generate_suggestions(_report_with(rows))
        vertical = [s for s in sugs if s.kind == SuggestionKind.VERTICAL]
        assert len(vertical) == 1
        assert "社会" in vertical[0].text  # 社会组最优
        assert "通用" not in vertical[0].basis  # 通用组不参与垂类比较

    def test_no_vertical_suggestion_when_all_generic(self) -> None:
        rows = [
            ("g1", ProductionType.TEXT, "2026-09-16T10:00:00+00:00", "",
             dict(exposure=1000, interactions=200)),
            ("g2", ProductionType.TEXT, "2026-09-16T11:00:00+00:00", "",
             dict(exposure=1000, interactions=100)),
        ]
        sugs = generate_suggestions(_report_with(rows))
        assert all(s.kind != SuggestionKind.VERTICAL for s in sugs)

    def test_min_constants_documented_values(self) -> None:
        assert MIN_GROUP_SAMPLE == 2
        assert MIN_RELATIVE_GAP == 0.30


# ---- 编排：回填 / 分析 / 决策 ----

class TestRecordPerformance:
    def test_upsert_backfills_account_from_queue(self, db) -> None:
        _production(db, "p1")
        _published_queue(db, "p1", account_id="acc9")
        out = record_performance(db, _record("p1", account_id=""))
        assert out.account_id == "acc9"

    def test_reentry_keeps_created_at(self, db) -> None:
        _production(db, "p1")
        _published_queue(db, "p1")
        first = record_performance(db, _record("p1", exposure=100))
        second = record_performance(db, _record("p1", exposure=200))
        assert second.id == first.id
        assert second.created_at == first.created_at
        assert second.exposure == 200

    def test_missing_production_raises_not_found(self, db) -> None:
        with pytest.raises(RefluxError) as ei:
            record_performance(db, _record("ghost"))
        assert ei.value.kind == "not_found"

    @pytest.mark.parametrize("status", [PublishStatus.PENDING, PublishStatus.DRAFT_READY])
    def test_unpublished_queue_item_rejected(self, db, status) -> None:
        _production(db, "p1")
        _published_queue(db, "p1", status=status)
        with pytest.raises(RefluxError) as ei:
            record_performance(db, _record("p1"))
        assert ei.value.kind == "not_published"

    def test_missing_queue_item_rejected(self, db) -> None:
        _production(db, "p1")  # 无队列项（HELD 成品）
        with pytest.raises(RefluxError) as ei:
            record_performance(db, _record("p1"))
        assert ei.value.kind == "not_published"


class TestAnalyze:
    def _seed_two_formats(self, db: DB) -> None:
        # 四条同发表于同一时段桶：只拉开形态差距，不触发时段建议
        for pid, ptype, interactions in [
            ("t1", ProductionType.TEXT, 200), ("t2", ProductionType.TEXT, 200),
            ("v1", ProductionType.VIDEO, 100), ("v2", ProductionType.VIDEO, 100),
        ]:
            _seed_published(db, pid, ptype, "2026-09-16T10:00:00+00:00")
            RefluxRecordDao(db).upsert(_record(pid, exposure=1000, interactions=interactions))

    def test_analyze_generates_pending_suggestions(self, db) -> None:
        self._seed_two_formats(db)
        report = analyze(db)
        assert report.record_count == 4
        sugs = RefluxSuggestionDao(db).list(status=SuggestionStatus.PENDING)
        assert len(sugs) == 1
        assert sugs[0].kind == SuggestionKind.FORMAT

    def test_reanalyze_replaces_pending_keeps_decided(self, db) -> None:
        self._seed_two_formats(db)
        analyze(db)
        old = RefluxSuggestionDao(db).list(status=SuggestionStatus.PENDING)[0]
        RefluxSuggestionDao(db).update_status(
            old.id, SuggestionStatus.CONFIRMED, decided_at="2026-09-16T12:00:00+00:00"
        )
        analyze(db)  # 重算：旧 pending 已确认项保留，新建议重新生成
        decided = RefluxSuggestionDao(db).list(status=SuggestionStatus.CONFIRMED)
        pending = RefluxSuggestionDao(db).list(status=SuggestionStatus.PENDING)
        assert [s.id for s in decided] == [old.id]
        assert len(pending) == 1
        assert old.id not in [s.id for s in pending]

    def test_analyze_with_no_records_clears_pending(self, db) -> None:
        RefluxSuggestionDao(db).insert(_suggestion())
        analyze(db)
        assert RefluxSuggestionDao(db).list(status=SuggestionStatus.PENDING) == []


class TestDecideSuggestion:
    def _seed(self, db: DB) -> RefluxSuggestion:
        sug = _suggestion()
        RefluxSuggestionDao(db).insert(sug)
        return sug

    def test_confirm_and_rollback_roundtrip(self, db) -> None:
        sug = self._seed(db)
        confirmed = decide_suggestion(db, sug.id, "confirm")
        assert confirmed.status == SuggestionStatus.CONFIRMED
        assert confirmed.decided_at

        rolled = decide_suggestion(db, sug.id, "rollback")  # 回滚 → 回到待确认
        assert rolled.status == SuggestionStatus.PENDING
        assert rolled.decided_at == confirmed.decided_at  # 决策时间保留

        again = decide_suggestion(db, sug.id, "confirm")  # 可再次采纳
        assert again.status == SuggestionStatus.CONFIRMED

    def test_reject_is_terminal(self, db) -> None:
        sug = self._seed(db)
        assert decide_suggestion(db, sug.id, "reject").status == SuggestionStatus.REJECTED
        with pytest.raises(RefluxError) as ei:
            decide_suggestion(db, sug.id, "rollback")
        assert ei.value.kind == "bad_status"

    @pytest.mark.parametrize(
        ("action", "setup"),
        [("confirm", "confirmed"), ("reject", "rejected"), ("rollback", "pending")],
    )
    def test_invalid_transitions_rejected(self, db, action, setup) -> None:
        status = SuggestionStatus(setup)
        sug = _suggestion(status=status)
        RefluxSuggestionDao(db).insert(sug)
        with pytest.raises(RefluxError) as ei:
            decide_suggestion(db, sug.id, action)
        assert ei.value.kind == "bad_status"

    def test_missing_suggestion_raises_not_found(self, db) -> None:
        with pytest.raises(RefluxError) as ei:
            decide_suggestion(db, "ghost", "confirm")
        assert ei.value.kind == "not_found"
