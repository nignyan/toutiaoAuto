"""数据回流模型。对应产品设计文档 §4.7（MVP 仅建议动作，不自动调参）。"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class ReviewStatus(str, Enum):
    """平台审核状态（发布后头条侧审核结果回流）。"""

    PENDING_REVIEW = "pending_review"  # 待审核
    APPROVED = "approved"  # 审核通过
    REJECTED = "rejected"  # 审核驳回


class SuggestionKind(str, Enum):
    """建议动作类型（分析维度 → 反哺对象的 MVP 映射）。"""

    FORMAT = "format"  # 内容形态：优先表现更好的形态
    TIMING = "timing"  # 发布时段：优先表现更好的时段
    VERTICAL = "vertical"  # 热点垂类：垂类选题倾斜


class SuggestionStatus(str, Enum):
    """建议动作状态机：pending → confirmed / rejected；confirmed → pending（回滚）。"""

    PENDING = "pending"  # 待确认
    CONFIRMED = "confirmed"  # 已采纳（MVP 仅记录，不落权重）
    REJECTED = "rejected"  # 已驳回


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid4().hex


class PerformanceRecord(BaseModel):
    """单个成品的表现回流记录（每成品 1:1，重复回填覆盖取最新）。"""

    id: str = Field(default_factory=_new_id)
    production_id: str
    account_id: str = ""  # 冗余自队列项，免联查
    exposure: int = Field(default=0, ge=0)  # 曝光
    plays: int = Field(default=0, ge=0)  # 播放
    completion_rate: float = Field(default=0.0, ge=0.0, le=100.0)  # 完播率（百分比）
    interactions: int = Field(default=0, ge=0)  # 互动合计（赞评转）
    negative: int = Field(default=0, ge=0)  # 负反馈
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    review_note: str = ""  # 审核备注（如驳回原因）
    recorded_at: str = Field(default_factory=_now)  # 本次回填时间
    created_at: str = Field(default_factory=_now)  # 首次回填时间


class RefluxSuggestion(BaseModel):
    """建议动作：人工确认后才生效（MVP 仅记录采纳，不调整任何权重）。"""

    id: str = Field(default_factory=_new_id)
    kind: SuggestionKind
    text: str = ""  # 建议文案
    basis: str = ""  # 数据依据摘要
    impact: str = ""  # 预期影响
    status: SuggestionStatus = SuggestionStatus.PENDING
    created_at: str = Field(default_factory=_now)
    decided_at: str = ""  # 首次决策（采纳/驳回）时间
