"""素材本地化测试：目标解析纯函数、下载编排、缓存复用与错误归类。"""

from pathlib import Path

import pytest

from app.daos import DB, MediaAssetDao
from app.models import (
    AuthStatus,
    MediaAsset,
    MediaType,
    Production,
    ProductionType,
    SourceType,
)
from app.pipeline.media_localizer import (
    LocalizationError,
    LocalMedia,
    localize_media,
    resolve_targets,
)


@pytest.fixture()
def db(tmp_path) -> DB:
    d = DB(tmp_path / "localizer.db")
    d.migrate()
    return d


def _asset(aid: str, event_id: str = "ev1", **kw) -> MediaAsset:
    return MediaAsset(
        id=aid,
        event_id=event_id,
        type=kw.pop("type", MediaType.VIDEO),
        source_url=kw.pop("source_url", ""),
        auth_status=kw.pop("auth_status", AuthStatus.CLEARED),
        source_type=kw.pop("source_type", SourceType.A),
    )


def _prod(**kw) -> Production:
    return Production(
        id=kw.pop("prod_id", "p1"),
        event_id=kw.pop("event_id", "ev1"),
        production_type=kw.pop("production_type", ProductionType.VIDEO),
        title="视频直击：测试事件",
        body="脚本",
        asset_ids=kw.pop("asset_ids", ["v1"]),
        cover_asset_id=kw.pop("cover_asset_id", ""),
    )


def _fake_fetch(calls: list[str], payload: bytes = b"DATA"):
    def fetch(url: str) -> bytes:
        calls.append(url)
        return payload

    return fetch


# ---- resolve_targets（纯函数）----

def test_resolve_targets_picks_first_usable_video_in_order() -> None:
    assets = [_asset("v2"), _asset("v1"), _asset("img1", type=MediaType.IMAGE)]
    prod = _prod(asset_ids=["v1", "img1"])  # 编排序 v1 在前，v2 未编入

    video, cover = resolve_targets(prod, assets)

    assert video.id == "v1"
    assert cover is None


def test_resolve_targets_skips_unusable_video() -> None:
    pending = _asset("v1", auth_status=AuthStatus.PENDING)  # 未授权不可用
    ok = _asset("v2")
    prod = _prod(asset_ids=["v1", "v2"])

    video, _ = resolve_targets(prod, [pending, ok])

    assert video.id == "v2"


def test_resolve_targets_cover_only_for_image_asset() -> None:
    video = _asset("v1", source_url="https://x/v.mp4")
    image = _asset("img1", type=MediaType.IMAGE)
    as_video_cover = _prod(asset_ids=["v1"], cover_asset_id="v1")  # 封面指向视频本身

    _, cover = resolve_targets(as_video_cover, [video, image])
    assert cover is None

    as_image_cover = _prod(asset_ids=["v1"], cover_asset_id="img1")
    _, cover = resolve_targets(as_image_cover, [video, image])
    assert cover is not None and cover.id == "img1"

    _, cover = resolve_targets(as_image_cover, [video])  # 封面素材不存在
    assert cover is None


def test_resolve_targets_no_video_raises() -> None:
    prod = _prod(asset_ids=["img1"])
    with pytest.raises(LocalizationError) as ei:
        resolve_targets(prod, [_asset("img1", type=MediaType.IMAGE)])
    assert ei.value.kind == "no_video"


# ---- localize_media（编排）----

def test_localize_non_video_returns_empty_without_download(db) -> None:
    calls: list[str] = []
    out = localize_media(db, _prod(production_type=ProductionType.TEXT), fetch=_fake_fetch(calls))

    assert out == LocalMedia()
    assert calls == []  # 图文退化形态不触发下载


def test_localize_video_downloads_video_and_image_cover(db, tmp_path) -> None:
    MediaAssetDao(db).insert(_asset("v1", source_url="https://x/video.mp4"))
    MediaAssetDao(db).insert(_asset("img1", type=MediaType.IMAGE, source_url="https://x/cover.jpg"))
    prod = _prod(asset_ids=["v1"], cover_asset_id="img1")
    calls: list[str] = []

    out = localize_media(db, prod, root_dir=tmp_path / "media", fetch=_fake_fetch(calls))

    assert out.video_path == tmp_path / "media" / "v1.mp4"
    assert out.cover_path == tmp_path / "media" / "img1.jpg"
    assert out.video_path.read_bytes() == b"DATA"
    assert sorted(calls) == ["https://x/cover.jpg", "https://x/video.mp4"]


def test_localize_ext_fallback_without_url_suffix(db, tmp_path) -> None:
    MediaAssetDao(db).insert(_asset("v1", source_url="https://x/download?token=abc"))
    calls: list[str] = []

    out = localize_media(db, _prod(asset_ids=["v1"]), root_dir=tmp_path, fetch=_fake_fetch(calls))

    assert out.video_path == tmp_path / "v1.mp4"  # 无后缀回退 .mp4，query 不参与解析


def test_localize_reuses_existing_cache(db, tmp_path) -> None:
    MediaAssetDao(db).insert(_asset("v1", source_url="https://x/video.mp4"))
    cached = tmp_path / "v1.mp4"
    cached.write_bytes(b"OLD")  # 预置非空缓存
    calls: list[str] = []

    out = localize_media(db, _prod(asset_ids=["v1"]), root_dir=tmp_path, fetch=_fake_fetch(calls))

    assert out.video_path == cached
    assert cached.read_bytes() == b"OLD"  # 不重下、不覆盖
    assert calls == []


def test_localize_missing_source_url_raises(db, tmp_path) -> None:
    MediaAssetDao(db).insert(_asset("v1", source_url=""))
    with pytest.raises(LocalizationError) as ei:
        localize_media(db, _prod(asset_ids=["v1"]), root_dir=tmp_path, fetch=_fake_fetch([]))
    assert ei.value.kind == "no_url"


def test_localize_download_failure_raises_download_failed(db, tmp_path) -> None:
    MediaAssetDao(db).insert(_asset("v1", source_url="https://x/video.mp4"))

    def bad_fetch(url: str) -> bytes:
        raise ConnectionError("网络不可达")

    with pytest.raises(LocalizationError) as ei:
        localize_media(db, _prod(asset_ids=["v1"]), root_dir=tmp_path, fetch=bad_fetch)
    assert ei.value.kind == "download_failed"
    assert "网络不可达" in str(ei.value)


def test_localize_no_usable_video_raises(db, tmp_path) -> None:
    prod = _prod(asset_ids=["ghost"])  # asset_ids 指向不存在的素材
    with pytest.raises(LocalizationError) as ei:
        localize_media(db, prod, root_dir=tmp_path, fetch=_fake_fetch([]))
    assert ei.value.kind == "no_video"


def test_local_media_paths_are_path_objects(db, tmp_path) -> None:
    """视频路径为 Path，可直接供适配器 set_input_files 使用。"""
    MediaAssetDao(db).insert(_asset("v1", source_url="https://x/video.mp4"))
    out = localize_media(db, _prod(asset_ids=["v1"]), root_dir=tmp_path, fetch=_fake_fetch([]))
    assert isinstance(out.video_path, Path)
