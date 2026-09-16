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
    BLOCKED = "blocked"  # 一票否决拦截，禁止发布


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid4().hex


class Production(BaseModel):
    """一次生产的成品。"""

    id: str = Field(default_factory=_new_id)
    event_id: str
    vertical: str = ""  # 成品垂类标签；空 = 通用，不参与垂类精确匹配
    production_type: ProductionType
    asset_ids: list[str] = Field(default_factory=list)
    title: str = ""
    body: str = ""  # 正文（图文/图集）或脚本解说词（视频）
    cover_asset_id: str = ""  # 封面素材 id，无可选素材时留空
    rule: str = ""  # 命中的形态规则（规则1 / 规则2 / 规则3）
    composer: str = "template"  # 生成器标识，预留 llm 等
    checks: list[str] = Field(default_factory=list)  # 质检检查项明细
    vetoes: list[str] = Field(default_factory=list)  # 一票否决明细
    quality_score: float = Field(default=0.0, ge=0.0, le=100.0)
    quality_status: QualityStatus = QualityStatus.HELD
    account_id: str = ""
    created_at: str = Field(default_factory=_now)