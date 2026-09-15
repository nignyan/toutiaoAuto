"""账号模型。对应产品设计文档 §4.6 账号与发布工作台。"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class AccountStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid4().hex


class Account(BaseModel):
    """头条账号配置。"""

    id: str = Field(default_factory=_new_id)
    name: str
    vertical: str = ""  # 账号垂类
    daily_quota: int = Field(default=0, ge=0)  # 日产量
    publish_window_start: str = ""  # 发布时间窗口（HH:MM）
    publish_window_end: str = ""
    status: AccountStatus = AccountStatus.ACTIVE
    created_at: str = Field(default_factory=_now)