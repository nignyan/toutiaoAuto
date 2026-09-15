"""成品模型。对应产品设计文档 §4.4 内容生产引擎。"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class ProductionType(str, Enum):
    VIDEO = "video"
    IMAGE_SLIDESHOW = "image_slideshow"
    TEXT = "text"


class QualityStatus(str, Enum):
    QUALIFIED = "qualified"  # 质量分 ≥ 75，可进入发布配额
    HELD = "held"  # 留档 + 降级次日重试


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid4().hex


class Production(BaseModel):
    """一次生产的成品。"""

    id: str = Field(default_factory=_new_id)
    event_id: str
    production_type: ProductionType
    asset_ids: list[str] = Field(default_factory=list)
    title: str = ""
    quality_score: float = Field(default=0.0, ge=0.0, le=100.0)
    quality_status: QualityStatus = QualityStatus.HELD
    account_id: str = ""
    created_at: str = Field(default_factory=_now)