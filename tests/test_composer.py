"""内容生成器测试：标题模板、正文三段、编排与封面、空素材边界。"""

import pytest

from app.models import (
    AuthStatus,
    Clarity,
    Event,
    EventStatus,
    MediaAsset,
    MediaType,
    SourceType,
    TimelineEntry,
)
from app.pipeline.composer import TemplateComposer
from app.pipeline.format_decision import ContentFormat, FormatDecision, decide_format

composer = TemplateComposer()


def _event(**kw) -> Event:
    return Event(
        title=kw.pop("title", "某地突发山火，救援进行中"),
        summary=kw.pop("summary", "火势已得到初步控制"),
        status=kw.pop("status", EventStatus.READY),
        timeline=kw.pop(
            "timeline",
            [
                TimelineEntry(ts="2026-09-15T08:00:00+00:00", title="首报", heat=80.0),
                TimelineEntry(ts="2026-09-15T09:00:00+00:00", title="救援跟进", heat=85.0),
            ],
        ),
        **kw,
    )


def _asset(**kw) -> MediaAsset:
    return MediaAsset(
        event_id=kw.pop("event_id", "ev1"),
        type=kw.pop("type", MediaType.IMAGE),
        source_type=kw.pop("source_type", SourceType.A),
        auth_status=kw.pop("auth_status", AuthStatus.CLEARED),
        attribution=kw.pop("attribution", "来源：合作媒体"),
        clarity=kw.pop("clarity", Clarity.CLEAR),
        info_density=kw.pop("info_density", 80.0),
        **kw,
    )


# ---- 标题模板（各规则） ----

def test_title_rule1_video_only() -> None:
    assets = [_asset(type=MediaType.VIDEO, info_density=85.0)]
    decision = FormatDecision(ContentFormat.VIDEO, "规则1：存在高信息密度清晰视频")
    draft = composer.compose(_event(), assets, decision)
    assert draft.title == "视频直击：某地突发山火，救援进行中"


def test_title_rule2_images_only() -> None:
    assets = [_asset(info_density=60.0), _asset(info_density=70.0)]
    draft = composer.compose(_event(), assets, decide_format(assets))
    assert draft.title == "多图直击：某地突发山火，救援进行中"


def test_title_rule3_video_plus_images() -> None:
    assets = [
        _asset(type=MediaType.VIDEO, info_density=55.0),
        _asset(info_density=60.0),
        _asset(info_density=70.0),
    ]
    draft = composer.compose(_event(), assets, decide_format(assets))
    assert draft.title == "现场实录：某地突发山火，救援进行中"


# ---- 正文三段结构 ----

def test_body_three_sections_with_summary_timeline_attribution() -> None:
    assets = [_asset(info_density=60.0), _asset(info_density=70.0, attribution="来源：现场记者")]
    draft = composer.compose(_event(), assets, decide_format(assets))
    sections = draft.body.split("\n\n")
    assert sections[0] == "【事件】某地突发山火，救援进行中\n火势已得到初步控制"
    assert sections[1].startswith("【时间线】")
    assert sections[2] == "【素材署名】\n- 来源：合作媒体\n- 来源：现场记者"


def test_body_omits_empty_summary_and_attribution_sections() -> None:
    assets = [_asset(attribution=""), _asset(attribution="", info_density=60.0)]
    draft = composer.compose(_event(summary="", ), assets, decide_format(assets))
    assert "【事件】" in draft.body
    assert "【素材署名】" not in draft.body


# ---- 时间线 ts 升序 ----

def test_body_timeline_sorted_by_ts_ascending() -> None:
    ev = _event(
        timeline=[
            TimelineEntry(ts="2026-09-15T10:00:00+00:00", title="后发"),
            TimelineEntry(ts="2026-09-15T07:00:00+00:00", title="先发"),
            TimelineEntry(ts="2026-09-15T08:30:00+00:00", title="中间"),
        ]
    )
    assets = [_asset(), _asset(info_density=65.0)]
    draft = composer.compose(ev, assets, decide_format(assets))
    timeline_section = next(s for s in draft.body.split("\n\n") if s.startswith("【时间线】"))
    titles = [line for line in timeline_section.split("\n")[1:]]
    assert titles == [
        "- 2026-09-15T07:00:00+00:00 先发",
        "- 2026-09-15T08:30:00+00:00 中间",
        "- 2026-09-15T10:00:00+00:00 后发",
    ]


# ---- 编排与封面 ----

def test_ordered_assets_videos_first_original_order_then_images_by_density() -> None:
    assets = [
        _asset(id="img_high", info_density=90.0),
        _asset(id="vid1", type=MediaType.VIDEO, info_density=55.0),
        _asset(id="img_none", info_density=None),
        _asset(id="vid2", type=MediaType.VIDEO, info_density=95.0),
        _asset(id="img_low", info_density=40.0),
    ]
    draft = composer.compose(_event(), assets, decide_format(assets))
    assert draft.ordered_asset_ids == ["vid1", "vid2", "img_high", "img_low", "img_none"]
    assert draft.cover_asset_id == "vid2"  # 信息密度最高者（视频也参与封面竞选）


def test_cover_empty_when_no_assets() -> None:
    draft = composer.compose(_event(), [], FormatDecision(ContentFormat.DEFER, "规则4"))
    assert draft.ordered_asset_ids == []
    assert draft.cover_asset_id == ""


def test_resolve_rule_text_matches_decision() -> None:
    from app.pipeline.composer import resolve_rule

    video_assets = [_asset(type=MediaType.VIDEO, info_density=85.0)]
    assert resolve_rule(
        FormatDecision(ContentFormat.VIDEO, "规则1"), video_assets
    ) == "规则1"
    assert resolve_rule(
        FormatDecision(ContentFormat.IMAGE_SLIDESHOW, "规则3"),
        [_asset(type=MediaType.VIDEO), _asset()],
    ) == "规则3"
    assert resolve_rule(
        FormatDecision(ContentFormat.IMAGE_SLIDESHOW, "规则2"), [_asset()]
    ) == "规则2"
    assert resolve_rule(FormatDecision(ContentFormat.DEFER, "规则4"), []) == ""


@pytest.mark.parametrize(
    ("fmt", "rule", "expected_prefix"),
    [
        (ContentFormat.VIDEO, "规则1", "视频直击"),
        (ContentFormat.IMAGE_SLIDESHOW, "规则2", "多图直击"),
        (ContentFormat.IMAGE_SLIDESHOW, "规则3", "现场实录"),
    ],
)
def test_title_prefixes_by_rule(fmt: ContentFormat, rule: str, expected_prefix: str) -> None:
    assets = [_asset(info_density=60.0), _asset(info_density=70.0)]
    if rule == "规则3":
        assets.append(_asset(type=MediaType.VIDEO, info_density=55.0))
    draft = composer.compose(_event(), assets, FormatDecision(fmt, rule))
    assert draft.title.startswith(expected_prefix)
