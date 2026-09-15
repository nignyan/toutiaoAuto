"""发布适配层：统一内容包与适配器协议，上层队列不感知渠道差异。"""

from .adapter import ContentPackage, PublishAdapter, PublishResult, PublishStatus

__all__ = [
    "ContentPackage",
    "PublishAdapter",
    "PublishResult",
    "PublishStatus",
]