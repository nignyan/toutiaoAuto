"""内容形态决策。

实现产品设计文档 §5：素材可用性从强到弱的判定，自上而下、命中即止。
优先级：规则 4（无有效媒体）→ 规则 1（视频独立成片）→ 规则 3（视频+图片混编）→ 规则 2（图集）。
"""

from dataclasses import dataclass
from enum import Enum

from app.models import Clarity, MediaAsset, MediaType


class ContentFormat(str, Enum):
    """形态判定优先级产物。"""

    VIDEO = "video"
    IMAGE_SLIDESHOW = "image_slideshow"
    TEXT = "text"
    DEFER = "defer"


@dataclass(frozen=True)
class FormatDecision:
    """形态决策结果。"""

    content_format: ContentFormat
    reason: str


def _is_clear_clarity(asset: MediaAsset) -> bool:
    return asset.clarity in (Clarity.ULTRACLEAR, Clarity.CLEAR)


def _density(asset: MediaAsset) -> float:
    return asset.info_density if asset.info_density is not None else 0.0


def decide_format(assets: list[MediaAsset]) -> FormatDecision:
    """根据事件可用素材判定优先产物品类（命中即止）。

    仅授权已确认（clear）且来源非禁止（C）的素材参与判定，其余视同无有效媒体。
    """
    usable = [a for a in assets if a.is_usable]
    videos = [a for a in usable if a.type == MediaType.VIDEO]
    images = [a for a in usable if a.type == MediaType.IMAGE]

    # 规则 1：有清晰且信息密度 ≥ 70 的视频，可直接独立成片（图片不参与）
    if any(_is_clear_clarity(v) and _density(v) >= 70 for v in videos):
        return FormatDecision(
            ContentFormat.VIDEO,
            "规则1：存在高信息密度清晰视频，可独立成片",
        )

    # 规则 3：视频与图片兼有，视频达「清晰」或「信息密度 ≥ 50」之一，作引子 + 图片补充
    if videos and images and any(
        _is_clear_clarity(v) or _density(v) >= 50 for v in videos
    ):
        return FormatDecision(
            ContentFormat.IMAGE_SLIDESHOW,
            "规则3：视频作引子片段，图片承担背景与时间线",
        )

    # 规则 2：无足够可用视频，且现场/新闻图片 ≥ 2 张
    if len(images) >= 2:
        return FormatDecision(
            ContentFormat.IMAGE_SLIDESHOW,
            "规则2：无可用视频成片，采用多张图集呈现",
        )

    # 规则 4：仅有文字或有效媒体不足，暂缓生产进入素材等待队列
    return FormatDecision(
        ContentFormat.DEFER,
        "规则4：无有效媒体，暂缓生产进入素材等待队列",
    )