"""媒体素材模型。对应产品设计文档 §4.3 媒体资产池。"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class MediaType(str, Enum):
    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"
    TEXT = "text"


class Clarity(str, Enum):
    """清晰度分级，「清晰度 ≥ 清晰」指 ULTRACLEAR 或 CLEAR。"""

    ULTRACLEAR = "超清"
    CLEAR = "清晰"
    NORMAL = "一般"
    BLURRY = "模糊"


class SourceType(str, Enum):
    """来源分级：A 可直接使用 / B 限定条件使用 / C 禁止使用。"""

    A = "A"
    B = "B"
    C = "C"


class AuthStatus(str, Enum):
    """授权状态，仅 cleared 可进入生产。"""

    CLEARED = "cleared"
    PENDING = "pending"
    BLOCKED = "blocked"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid4().hex


class MediaAsset(BaseModel):
    """入库的媒体资产。"""

    id: str = Field(default_factory=_new_id)
    event_id: str = ""
    type: MediaType
    source_url: str = ""
    # 来源合规与授权
    source_type: SourceType = SourceType.A
    auth_status: AuthStatus = AuthStatus.PENDING
    auth_evidence: str = ""  # 凭证或原始发布链接
    license_business: bool = True  # 是否可商用
    attribution: str = ""  # 署名文本
    # 素材属性
    clarity: Clarity | None = None
    info_density: float | None = Field(  # 信息密度 0–100，入库时由算法侧计算
        default=None, ge=0.0, le=100.0
    )
    duration_s: float | None = None
    fingerprint: str = ""  # 去重指纹
    ingested_at: str = Field(default_factory=_now)

    @property
    def is_usable(self) -> bool:
        """仅授权已确认且不属于禁止来源的素材可进入生产。"""
        return self.auth_status == AuthStatus.CLEARED and self.source_type != SourceType.C