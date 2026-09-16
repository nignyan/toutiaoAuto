"""质检测试：一票否决独立触发、三态判定、阈值边界、公式分项贡献。"""

from app.models import (
    AuthStatus,
    Event,
    MediaAsset,
    MediaType,
    QualityStatus,
    SourceType,
    TimelineEntry,
)
from app.pipeline.quality_check import check_quality


def _event(**kw) -> Event:
    return Event(
        title=kw.pop("title", "某地突发山火，救援进行中"),  # 12 字，命中标题分
        timeline=kw.pop("timeline", _timeline(2)),
        **kw,
    )


def _timeline(n: int) -> list[TimelineEntry]:
    return [
        TimelineEntry(ts=f"2026-09-15T0{i}:00:00+00:00", title=f"信号{i}", heat=80.0)
        for i in range(n)
    ]


def _asset(**kw) -> MediaAsset:
    return MediaAsset(
        type=kw.pop("type", MediaType.IMAGE),
        source_type=kw.pop("source_type", SourceType.A),
        auth_status=kw.pop("auth_status", AuthStatus.CLEARED),
        attribution=kw.pop("attribution", "来源：合作媒体"),
        info_density=kw.pop("info_density", None),
        **kw,
    )


def _ready_assets(n: int = 3, **kw) -> list[MediaAsset]:
    return [_asset(**kw) for _ in range(n)]


# ---- 一票否决（各检查项独立触发） ----

def test_veto_source_missing_when_timeline_empty() -> None:
    result = check_quality(_event(timeline=[]), _ready_assets())
    assert result.vetoes == ["事件来源缺失"]
    assert result.status == QualityStatus.BLOCKED


def test_veto_assets_empty() -> None:
    result = check_quality(_event(), [])
    assert result.vetoes == ["素材不可用"]
    assert result.status == QualityStatus.BLOCKED


def test_veto_auth_not_cleared_when_non_usable_mixed_in() -> None:
    assets = _ready_assets() + [_asset(auth_status=AuthStatus.PENDING)]
    result = check_quality(_event(), assets)
    assert result.vetoes == ["素材授权未确认"]
    assert result.status == QualityStatus.BLOCKED


def test_veto_source_c_is_not_usable() -> None:
    assets = _ready_assets() + [_asset(source_type=SourceType.C)]
    result = check_quality(_event(), assets)
    assert result.vetoes == ["素材授权未确认"]


def test_veto_attribution_missing_on_any_usable_asset() -> None:
    assets = _ready_assets(3)
    assets[1] = _asset(attribution="")
    result = check_quality(_event(), assets)
    assert result.vetoes == ["署名缺失"]
    assert result.status == QualityStatus.BLOCKED


# ---- 三态判定与 75 阈值边界 ----

def test_exact_75_is_qualified() -> None:
    # 50（基础）+ 3 素材 +10 + 3 条时间线 +10 + 标题 12 字 +5 = 75，密度全缺按 0
    result = check_quality(_event(timeline=_timeline(3)), _ready_assets(3))
    assert result.score == 75.0
    assert result.status == QualityStatus.QUALIFIED
    assert result.vetoes == []


def test_74_5_is_held() -> None:
    # 50 + 密度均值 18×0.25=4.5 + 2 素材 +5 + 3 时间线 +10 + 标题 +5 = 74.5
    assets = [_asset(info_density=20.0), _asset(info_density=16.0)]
    result = check_quality(_event(timeline=_timeline(3)), assets)
    assert result.score == 74.5
    assert result.status == QualityStatus.HELD


def test_blocked_overrides_high_score() -> None:
    assets = [_asset(info_density=100.0) for _ in range(3)]
    assets.append(_asset(auth_status=AuthStatus.PENDING))  # 混入未授权 → 否决
    result = check_quality(_event(timeline=_timeline(3)), assets)
    assert result.score > 75
    assert result.status == QualityStatus.BLOCKED  # 有否决时分数不影响三态


# ---- 公式各分项贡献 ----

def test_score_base_50_with_minimal_inputs() -> None:
    # 单素材无密度 + 单条时间线 + 标题过短 → 纯基础分
    result = check_quality(
        _event(title="短标题", timeline=_timeline(1)), [_asset()]
    )
    assert result.score == 50.0


def test_score_density_mean_contribution() -> None:
    # 2 素材密度 80/100 → 均值 90 → +22.5；密度缺失按 0 计
    assets = [_asset(info_density=80.0), _asset(info_density=100.0)]
    result = check_quality(_event(timeline=_timeline(3)), assets)
    # 50 + 22.5 + 5（2 素材）+ 10（3 时间线）+ 5（标题）
    assert result.score == 92.5


def test_score_missing_density_counts_as_zero() -> None:
    assets = [_asset(info_density=None), _asset(info_density=100.0), _asset()]
    result = check_quality(_event(timeline=_timeline(3)), assets)
    # 均值 (0+100+0)/3 = 33.33 → +8.33；50 + 8.33 + 10 + 10 + 5
    assert result.score == 83.33


def test_score_sufficiency_tiers() -> None:
    three = check_quality(_event(timeline=_timeline(1)), _ready_assets(3))
    two = check_quality(_event(timeline=_timeline(1)), _ready_assets(2))
    one = check_quality(_event(timeline=_timeline(1)), _ready_assets(1))
    assert three.score - one.score == 10.0  # 3 张 +10
    assert two.score - one.score == 5.0  # 2 张 +5


def test_score_timeline_tiers() -> None:
    base_assets = _ready_assets(1)
    t3 = check_quality(_event(timeline=_timeline(3)), base_assets)
    t2 = check_quality(_event(timeline=_timeline(2)), base_assets)
    t1 = check_quality(_event(timeline=_timeline(1)), base_assets)
    assert t3.score - t1.score == 10.0
    assert t2.score - t1.score == 5.0


def test_score_title_length_boundaries() -> None:
    assets = _ready_assets(1)
    t9 = check_quality(_event(title="九字标题共九称呼", timeline=_timeline(1)), assets)
    t10 = check_quality(_event(title="十字标题刚好十个字数", timeline=_timeline(1)), assets)
    t30 = check_quality(_event(title="字" * 30, timeline=_timeline(1)), assets)
    t31 = check_quality(_event(title="字" * 31, timeline=_timeline(1)), assets)
    assert t10.score - t9.score == 5.0
    assert t30.score - t31.score == 5.0


# ---- 通过项明细 ----

def test_checks_record_passed_items() -> None:
    result = check_quality(_event(timeline=_timeline(3)), _ready_assets(3))
    assert result.checks == ["事件来源完整", "素材可用", "素材授权已确认", "署名完整"]
