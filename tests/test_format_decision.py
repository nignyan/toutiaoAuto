"""内容形态决策测试，覆盖产品设计文档 §5 各规则。"""

from app.models import AuthStatus, Clarity, MediaAsset, MediaType, SourceType
from app.pipeline.format_decision import ContentFormat, FormatDecision, decide_format


def _media(
    asset_type: MediaType = MediaType.VIDEO,
    clarity: Clarity | None = None,
    density: float | None = None,
    source_type: SourceType = SourceType.A,
    auth: AuthStatus = AuthStatus.CLEARED,
) -> MediaAsset:
    return MediaAsset(
        type=asset_type,
        clarity=clarity,
        info_density=density,
        source_type=source_type,
        auth_status=auth,
    )


def _assert_format(decision: FormatDecision, expected: ContentFormat) -> None:
    assert decision.content_format == expected


def test_rule1_high_density_clear_video() -> None:
    assets = [_media(clarity=Clarity.CLEAR, density=85)]
    _assert_format(decide_format(assets), ContentFormat.VIDEO)


def test_rule1_ultra_clear_video() -> None:
    assets = [_media(clarity=Clarity.ULTRACLEAR, density=70)]
    _assert_format(decide_format(assets), ContentFormat.VIDEO)


def test_rule1_images_do_not_participate() -> None:
    # 规则 1 只判断视频；多图不影响高信息密度视频独立成片
    assets = [
        _media(clarity=Clarity.CLEAR, density=80),
        _media(asset_type=MediaType.IMAGE, clarity=None, density=None),
        _media(asset_type=MediaType.IMAGE, clarity=None, density=None),
    ]
    _assert_format(decide_format(assets), ContentFormat.VIDEO)


def test_rule3_video_clear_with_images() -> None:
    assets = [
        _media(clarity=Clarity.CLEAR, density=40),  # 未达 70，但清晰
        _media(asset_type=MediaType.IMAGE, clarity=None, density=None),
    ]
    _assert_format(decide_format(assets), ContentFormat.IMAGE_SLIDESHOW)


def test_rule3_video_density_50_with_images() -> None:
    assets = [
        _media(clarity=Clarity.NORMAL, density=55),  # 不清晰但密度 ≥ 50
        _media(asset_type=MediaType.IMAGE, clarity=None, density=None),
    ]
    _assert_format(decide_format(assets), ContentFormat.IMAGE_SLIDESHOW)


def test_rule2_images_only() -> None:
    images = [_media(asset_type=MediaType.IMAGE, clarity=None, density=None) for _ in range(2)]
    _assert_format(decide_format(images), ContentFormat.IMAGE_SLIDESHOW)


def test_rule4_defer_when_no_media() -> None:
    _assert_format(decide_format([]), ContentFormat.DEFER)


def test_rule4_defer_single_image() -> None:
    assets = [_media(asset_type=MediaType.IMAGE, clarity=None, density=None)]
    _assert_format(decide_format(assets), ContentFormat.DEFER)


def test_defer_when_video_below_minimum_and_few_images() -> None:
    # 视频不清晰且密度 < 50，图片不足 2 张 → 落回规则 4
    assets = [
        _media(clarity=Clarity.BLURRY, density=30),
        _media(asset_type=MediaType.IMAGE, clarity=None, density=None),
    ]
    _assert_format(decide_format(assets), ContentFormat.DEFER)


def test_blocked_and_source_c_excluded() -> None:
    # 未授权 / 禁止来源素材视同无有效媒体
    block_listed = [
        _media(clarity=Clarity.CLEAR, density=90, auth=AuthStatus.PENDING),
        _media(clarity=Clarity.CLEAR, density=90, source_type=SourceType.C),
    ]
    _assert_format(decide_format(block_listed), ContentFormat.DEFER)


def test_blocked_video_falls_to_image_slideshow_with_images() -> None:
    assets = [
        _media(clarity=Clarity.CLEAR, density=90, auth=AuthStatus.BLOCKED),  # 不可用
        _media(asset_type=MediaType.IMAGE, clarity=None, density=None),
        _media(asset_type=MediaType.IMAGE, clarity=None, density=None),
    ]
    _assert_format(decide_format(assets), ContentFormat.IMAGE_SLIDESHOW)