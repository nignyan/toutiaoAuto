"""内容生成器（D9 方案 C）。

`ContentComposer` 协议预留 LLM 插槽；MVP 提供零外部依赖的 `TemplateComposer`：
标题模板 + 正文三段（事件摘要 / 时间线 / 素材署名）+ 密度降序编排 + 封面选择。
入参约定：`assets` 已按 D2 过滤（仅 usable）。
"""

from dataclasses import dataclass
from typing import Protocol

from app.models import Event, MediaAsset, MediaType
from app.pipeline.format_decision import ContentFormat, FormatDecision


@dataclass(frozen=True)
class Draft:
    """composer 管道内传输对象，不落库。"""

    title: str
    body: str
    ordered_asset_ids: list[str]
    cover_asset_id: str


class ContentComposer(Protocol):
    """内容生成器协议：后续可替换为 LLM 实现，数据流不动。"""

    def compose(
        self, event: Event, assets: list[MediaAsset], decision: FormatDecision
    ) -> Draft: ...


def resolve_rule(decision: FormatDecision, assets: list[MediaAsset]) -> str:
    """解析命中的形态规则编号（与 format_decision 的规则口径一致）。"""
    if decision.content_format == ContentFormat.VIDEO:
        return "规则1"
    if decision.content_format == ContentFormat.IMAGE_SLIDESHOW:
        has_video = any(a.type == MediaType.VIDEO for a in assets)
        return "规则3" if has_video else "规则2"
    return ""


_TITLE_BY_RULE = {
    "规则1": "视频直击",
    "规则2": "多图直击",
    "规则3": "现场实录",
}


def _density(asset: MediaAsset) -> float:
    return asset.info_density if asset.info_density is not None else 0.0


class TemplateComposer:
    """模板生成器：确定性编排，产出文本上限有限（MVP 接受）。"""

    def compose(
        self, event: Event, assets: list[MediaAsset], decision: FormatDecision
    ) -> Draft:
        rule = resolve_rule(decision, assets)
        title = f"{_TITLE_BY_RULE[rule]}：{event.title}" if rule else event.title
        ordered = _order_assets(assets)
        cover = max(assets, key=_density).id if assets else ""
        return Draft(
            title=title,
            body=_compose_body(event, assets),
            ordered_asset_ids=[a.id for a in ordered],
            cover_asset_id=cover,
        )


def _order_assets(assets: list[MediaAsset]) -> list[MediaAsset]:
    """视频保持原序在前，图片按信息密度降序（缺密度视为 0）排后。"""
    videos = [a for a in assets if a.type == MediaType.VIDEO]
    images = sorted(
        (a for a in assets if a.type == MediaType.IMAGE),
        key=_density,
        reverse=True,  # 稳定排序：同密度保持入库原序
    )
    return videos + images


def _compose_body(event: Event, assets: list[MediaAsset]) -> str:
    sections: list[str] = [f"【事件】{event.title}"]
    if event.summary:
        sections[0] += f"\n{event.summary}"

    timeline_lines = [
        f"- {t.ts} {t.title}" for t in sorted(event.timeline, key=lambda t: t.ts)
    ]
    if timeline_lines:
        sections.append("【时间线】\n" + "\n".join(timeline_lines))

    attribution_lines = [
        f"- {a.attribution}" for a in assets if a.attribution
    ]
    if attribution_lines:
        sections.append("【素材署名】\n" + "\n".join(attribution_lines))

    return "\n\n".join(sections)
