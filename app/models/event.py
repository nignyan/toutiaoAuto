"""事件模型。对应产品设计文档 §4.2 事件聚类与选题中心。"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class EventStatus(str, Enum):
    """事件生产流程状态。"""

    READY = "ready"  # 待生产
    DEFERRED = "deferred"  # 暂缓生产，进入素材等待队列
    PRODUCED = "produced"  # 已产出
    ARCHIVED = "archived"  # 已归档（含等待超时归档）


class TimelineEntry(BaseModel):
    """事件时间线条目：一次并入信号的时间线记录。"""

    ts: str  # ISO 时间
    title: str
    source: str = ""
    heat: float = 0.0
    source_url: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid4().hex


class Event(BaseModel):
    """聚类后的事件卡片。"""

    id: str = Field(default_factory=_new_id)
    title: str
    summary: str = ""
    score: float = Field(default=0.0, ge=0.0)  # 热点评分（MVP：归一化热度 0–100，并入取 max）
    status: EventStatus = EventStatus.READY
    timeline: list[TimelineEntry] = Field(default_factory=list)  # 并入信号的时间线
    created_at: str = Field(default_factory=_now)
    deferred_at: str = ""  # 进入素材等待队列时间；DEFERRED 时必填（validator 兜底）
    deferred_retries: int = Field(default=0, ge=0)  # 等待期间素材补录尝试次数

    @model_validator(mode="after")
    def _fill_deferred_at(self) -> "Event":
        """进入素材等待队列时自动记录起点（显式传入的值不覆盖）。"""
        if self.status == EventStatus.DEFERRED and not self.deferred_at:
            self.deferred_at = _now()
        return self