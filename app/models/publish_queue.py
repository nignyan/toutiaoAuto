"""发布队列模型。对应产品设计文档 §4.6。"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class PublishStatus(str, Enum):
    PENDING = "pending"  # 待发布
    DRAFT_READY = "draft_ready"  # 草稿箱已填好，等待人工在头条后台点发布
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
    # 排序键：默认 0 退化为入队序（FIFO）；行内调整后按值升序，同值仍按入队序
    sort_key: int = 0
    created_at: str = Field(default_factory=_now)