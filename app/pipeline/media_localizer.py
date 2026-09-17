"""素材本地化：把成品引用的远程素材（视频/封面）下载为本地文件。

视频真实发布前置（NOW.md）：适配器 set_input_files 需要本地路径，而
MediaAsset.source_url 均为远程 URL。与 producer/dispatcher 同构：
错误类型 + 纯函数 + 编排函数；fetch 可注入便于测试。

文件生命周期：data/media/ 按 <asset_id><ext> 持久缓存，已存在且非空即
复用（重试幂等 + 跨成品共享同素材）；MVP 不自动清理（演进项）。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from app.daos import DB, MediaAssetDao
from app.models import MediaAsset, MediaType, Production, ProductionType

_DOWNLOAD_TIMEOUT_S = 60.0
# URL 路径后缀：2–5 位字母数字（.mp4/.mov/.jpg/.png/.webp 等）
_EXT_RE = re.compile(r"\.([A-Za-z0-9]{2,5})$")
_FALLBACK_EXT = {MediaType.VIDEO: ".mp4", MediaType.IMAGE: ".jpg"}


class LocalizationError(Exception):
    """素材本地化拒绝：kind 为 no_video / no_url / download_failed。"""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        super().__init__(message)


@dataclass
class LocalMedia:
    """本地媒体文件路径（素材本地化的产物与注入点）。

    视频形态派发时由 localize_media 自动产出真实路径；调用方显式传入
    （测试替身/人工指定）时直接使用。图文退化形态无需本地文件，全空即可。
    """

    video_path: Path | None = None
    cover_path: Path | None = None
    image_paths: list[Path] = field(default_factory=list)


def resolve_targets(
    prod: Production, assets: list[MediaAsset]
) -> tuple[MediaAsset, MediaAsset | None]:
    """解析视频成品要本地化的目标素材（纯函数）。

    视频：按 prod.asset_ids 编排顺序取第一个 usable 视频，缺失抛 no_video；
    封面：仅当 cover_asset_id 指向 usable 图片素材时返回（指向视频本身
    或不存在则无需封面文件，取 None）。
    """
    by_id = {a.id: a for a in assets if a.is_usable}
    video = next(
        (
            by_id[i]
            for i in prod.asset_ids
            if i in by_id and by_id[i].type == MediaType.VIDEO
        ),
        None,
    )
    if video is None:
        raise LocalizationError("no_video", f"成品 {prod.id} 无可用的视频素材")
    cover = by_id.get(prod.cover_asset_id)
    return video, (cover if cover is not None and cover.type == MediaType.IMAGE else None)


def _ext_of(url: str, media_type: MediaType) -> str:
    """从 URL 路径解析文件后缀，解析不出按媒体类型回退（.mp4 / .jpg）。"""
    match = _EXT_RE.search(url.split("?")[0].split("#")[0])
    if match:
        return f".{match.group(1).lower()}"
    return _FALLBACK_EXT[media_type]


def _default_fetch(url: str) -> bytes:
    try:
        resp = httpx.get(url, timeout=_DOWNLOAD_TIMEOUT_S, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:  # noqa: BLE001 网络/HTTP 错误统一落 download_failed
        raise LocalizationError("download_failed", f"下载失败 {url}: {exc}") from exc


def _download(asset: MediaAsset, root_dir: Path, fetch: Callable[[str], bytes]) -> Path:
    """下载单个素材到 <root_dir>/<asset_id><ext>；已有非空缓存直接复用。"""
    if not asset.source_url:
        raise LocalizationError("no_url", f"素材 {asset.id} 无 source_url，无法下载")
    target = root_dir / f"{asset.id}{_ext_of(asset.source_url, asset.type)}"
    if target.exists() and target.stat().st_size > 0:
        return target
    try:
        data = fetch(asset.source_url)
    except LocalizationError:
        raise
    except Exception as exc:  # noqa: BLE001 注入 fetch 的异常也统一落 download_failed
        raise LocalizationError(
            "download_failed", f"下载失败 {asset.source_url}: {exc}"
        ) from exc
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as exc:
        raise LocalizationError("download_failed", f"写入失败 {target}: {exc}") from exc
    return target


def localize_media(
    db: DB,
    prod: Production,
    root_dir: str | Path = "data/media",
    fetch: Callable[[str], bytes] | None = None,
) -> LocalMedia:
    """把成品引用的远程素材下载为本地文件（编排函数）。

    非 VIDEO 形态返回空 LocalMedia（图文退化无需本地文件，不触发下载）；
    VIDEO 形态下载视频（必需）与封面（可选），任一失败抛 LocalizationError，
    由 dispatcher 捕获落 failed。
    """
    if prod.production_type != ProductionType.VIDEO:
        return LocalMedia()
    assets = MediaAssetDao(db).list_by_event(prod.event_id)
    video, cover = resolve_targets(prod, assets)
    root = Path(root_dir)
    video_path = _download(video, root, fetch or _default_fetch)
    cover_path = _download(cover, root, fetch or _default_fetch) if cover else None
    return LocalMedia(video_path=video_path, cover_path=cover_path)
