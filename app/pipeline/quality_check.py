"""自动质检（§4.5）：一票否决 + 确定性质量分。

独立纯函数，可复用于发布配额前的复检。引用比例超限检查不实现：
素材无原文文本可比对，属于假检查（D9 拍板记录）。
"""

from dataclasses import dataclass, field

from app.models import Event, MediaAsset, QualityStatus

PASS_SCORE = 75.0

# 一票否决项与通过项明细（一一对应，落在 Production.checks / vetoes 上）
_VETO_SOURCE_MISSING = "事件来源缺失"
_VETO_ASSETS_EMPTY = "素材不可用"
_VETO_AUTH_NOT_CLEARED = "素材授权未确认"
_VETO_ATTRIBUTION_MISSING = "署名缺失"
_PASS_SOURCE_COMPLETE = "事件来源完整"
_PASS_ASSETS_AVAILABLE = "素材可用"
_PASS_AUTH_CLEARED = "素材授权已确认"
_PASS_ATTRIBUTION_COMPLETE = "署名完整"


@dataclass(frozen=True)
class QualityResult:
    """质检结果（不落库，落在 Production 质检字段上）。"""

    score: float
    checks: list[str] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)
    status: QualityStatus = QualityStatus.HELD


def check_quality(event: Event, assets: list[MediaAsset]) -> QualityResult:
    """对事件与参与生产的素材执行一票否决与质量分计算。

    入参约定：`assets` 为参与本成品的素材清单（生产流程传入 usable 子集），
    混入非 usable 素材视为调用方误传，一票否决兜底。
    """
    vetoes: list[str] = []
    checks: list[str] = []

    usable = [a for a in assets if a.is_usable]

    # 一票否决（命中任一 → BLOCKED）
    if not event.timeline:
        vetoes.append(_VETO_SOURCE_MISSING)
    else:
        checks.append(_PASS_SOURCE_COMPLETE)

    if not assets:
        vetoes.append(_VETO_ASSETS_EMPTY)
    else:
        checks.append(_PASS_ASSETS_AVAILABLE)

    if len(usable) != len(assets):
        vetoes.append(_VETO_AUTH_NOT_CLEARED)
    else:
        checks.append(_PASS_AUTH_CLEARED)

    if usable and any(not a.attribution for a in usable):
        vetoes.append(_VETO_ATTRIBUTION_MISSING)
    elif usable:
        checks.append(_PASS_ATTRIBUTION_COMPLETE)

    # 确定性质量分（0–100）
    score = 50.0
    if usable:
        mean_density = sum(a.info_density if a.info_density is not None else 0.0 for a in usable)
        score += mean_density / len(usable) * 0.25
    if len(usable) >= 3:
        score += 10.0
    elif len(usable) == 2:
        score += 5.0
    if len(event.timeline) >= 3:
        score += 10.0
    elif len(event.timeline) == 2:
        score += 5.0
    if 10 <= len(event.title) <= 30:
        score += 5.0
    score = round(min(score, 100.0), 2)

    if vetoes:
        status = QualityStatus.BLOCKED
    elif score >= PASS_SCORE:
        status = QualityStatus.QUALIFIED
    else:
        status = QualityStatus.HELD

    return QualityResult(score=score, checks=checks, vetoes=vetoes, status=status)
