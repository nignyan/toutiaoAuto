"""账号模型。对应产品设计文档 §4.6 账号与发布工作台。"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class AccountStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class AccountRole(str, Enum):
    """角色域（产品设计文档 §4.6 多域结构）。"""

    PRIMARY = "primary"  # 主域：承载稳定垂类内容，自动分配第二层级
    TEST = "test"  # 测试域：选题与形态实验，不参与自动分配
    EXPERIMENT = "experiment"  # 实验域：分配链最末层级，可删除


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid4().hex


class PublishChannel(str, Enum):
    TOUTIAO = "toutiao"


class PublishAdapterKind(str, Enum):
    DRAFT = "draft"  # 只填草稿箱，人工点发布
    # 预留：API = "api"（官方接口，需 MCN 资质）


class Account(BaseModel):
    """头条账号配置。"""

    id: str = Field(default_factory=_new_id)
    name: str
    vertical: str = ""  # 账号垂类
    role: AccountRole = AccountRole.PRIMARY  # 角色域，域设置保存后立即生效
    daily_quota: int = Field(default=0, ge=0)  # 日产量（当日入队上限，0 不参与分配）
    publish_window_start: str = ""  # 发布时间窗口（HH:MM）
    publish_window_end: str = ""
    status: AccountStatus = AccountStatus.ACTIVE
    channel: PublishChannel = PublishChannel.TOUTIAO
    adapter: PublishAdapterKind = PublishAdapterKind.DRAFT
    # 自动发布开关：默认关闭（只填草稿箱，人工点发布）；开启后适配器填完直接点发布
    auto_publish: bool = False
    # 该账号的浏览器持久化登录态目录（每账号独立，天然隔离）
    profile_dir: str = ""
    created_at: str = Field(default_factory=_now)