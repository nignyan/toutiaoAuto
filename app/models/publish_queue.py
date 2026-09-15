"""发布队列模型。对应产品设计文档 §4.6。"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class PublishStatus(str, Enum):
    PENDING = "pending"  # 待发布
    PUBLISHED = "published"
    SKIPPED = "skipped"
    FAILED = "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid4().hex


class PublishQueueItem(BaseModel):
    """账号当日待发布队列项。"""

    id: str = Field(default_factory=_new_id)
    account_id: str
    production_id: str
    status: PublishStatus = PublishStatus.PENDING
    scheduled_for: str = ""
    publish_result: str = ""
    created_at: str = Field(default_factory=_now)