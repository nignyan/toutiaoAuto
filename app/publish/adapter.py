"""发布适配器协议与内容包定义。

任何渠道（头条草稿箱 / 未来官方 API）都实现 PublishAdapter，
上层发布队列只依赖这里的抽象。
"""

from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator


class ContentFormat(str, Enum):
    VIDEO = "video"
    SLIDESHOW = "slideshow"
    ARTICLE = "article"


class ContentPackage(BaseModel):
    """一条待发布内容的标准内容包。"""

    title: str
    body: str = ""  # 正文（图文/图集用）
    format: ContentFormat = ContentFormat.VIDEO
    video_path: Path | None = None
    cover_path: Path | None = None
    image_paths: list[Path] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_assets(self) -> "ContentPackage":
        if not self.title.strip():
            raise ValueError("内容包标题不能为空")
        needs_video = self.format in (ContentFormat.VIDEO, ContentFormat.SLIDESHOW)
        if needs_video and self.video_path is None:
            raise ValueError(f"{self.format.value} 形态必须携带视频文件")
        if self.format == ContentFormat.ARTICLE and not self.body.strip():
            raise ValueError("图文形态必须携带正文")
        return self


class PublishStatus(str, Enum):
    DRAFT_READY = "draft_ready"  # 草稿箱已填好，等待人工点发布
    PUBLISHED = "published"  # 已自动发布（auto_publish=True 时）
    NEEDS_LOGIN = "needs_login"  # 登录态失效，需扫码重登
    FAILED = "failed"


class PublishResult(BaseModel):
    status: PublishStatus
    message: str = ""
    draft_url: str = ""


@runtime_checkable
class PublishAdapter(Protocol):
    """发布适配器协议：把一个内容包投递到指定账号。"""

    def publish(self, package: ContentPackage, account) -> PublishResult:
        """投递内容包。

        语义约定：
        - account.auto_publish=False 时只填草稿箱并返回 DRAFT_READY；
        - account.auto_publish=True 时填完直接发布并返回 PUBLISHED。
        """
        ...