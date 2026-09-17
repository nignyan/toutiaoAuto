"""发布执行测试（D13）：内容包构建、结果映射、派发联动、状态流转守卫。"""

from pathlib import Path

import pytest

from app.daos import DB, AccountDao, MediaAssetDao, ProductionDao, PublishQueueDao
from app.models import (
    Account,
    AuthStatus,
    MediaAsset,
    MediaType,
    Production,
    ProductionType,
    PublishQueueItem,
    PublishStatus,
    QualityStatus,
)
from app.pipeline.dispatcher import (
    DispatchError,
    LocalMedia,
    build_package,
    confirm_published,
    dispatch_item,
    dispatch_item_now,
    map_result,
    skip_item,
    unskip_item,
)
from app.publish.adapter import ContentFormat, PublishResult
from app.publish.adapter import PublishStatus as AdapterStatus


@pytest.fixture()
def db(tmp_path) -> DB:
    d = DB(tmp_path / "dispatch.db")
    d.migrate()
    return d


class FakeAdapter:
    """适配器替身：按预设结果返回，记录收到的内容包与账号。"""

    name = "fake"

    def __init__(self, result: PublishResult | None = None, error: Exception | None = None):
        self._result = result
        self._error = error
        self.calls: list[tuple] = []

    def publish(self, package, account) -> PublishResult:
        self.calls.append((package, account))
        if self._error is not None:
            raise self._error
        return self._result


def _account(db: DB, **kw) -> Account:
    acc = Account(
        id=kw.pop("account_id", "acc1"),
        name=kw.pop("name", "主域账号"),
        daily_quota=kw.pop("daily_quota", 3),
        auto_publish=kw.pop("auto_publish", False),
    )
    AccountDao(db).upsert(acc)
    return acc


def _production(db: DB, **kw) -> Production:
    prod = Production(
        id=kw.pop("prod_id", "p1"),
        event_id=kw.pop("event_id", "ev1"),
        production_type=kw.pop("production_type", ProductionType.IMAGE_SLIDESHOW),
        title=kw.pop("title", "多图直击：测试事件"),
        body=kw.pop("body", "【事件】测试事件\n\n【时间线】\n- 08:00 信号"),
        asset_ids=kw.pop("asset_ids", []),
        quality_score=kw.pop("quality_score", 80.0),
        quality_status=kw.pop("quality_status", QualityStatus.QUALIFIED),
    )
    ProductionDao(db).insert(prod)
    return prod


def _enqueue(db: DB, status: PublishStatus = PublishStatus.PENDING, **kw) -> PublishQueueItem:
    item = PublishQueueItem(
        account_id=kw.pop("account_id", "acc1"),
        production_id=kw.pop("production_id", "p1"),
        status=status,
    )
    PublishQueueDao(db).insert(item)
    return item


# ---- 纯函数 ----

def test_build_package_article_for_text_and_slideshow() -> None:
    for ptype in (ProductionType.TEXT, ProductionType.IMAGE_SLIDESHOW):
        prod = Production(
            event_id="ev1", production_type=ptype, title="标题X", body="正文Y"
        )
        pkg = build_package(prod)
        assert pkg.title == "标题X"
        assert pkg.body == "正文Y"
        assert pkg.format == ContentFormat.ARTICLE


def test_build_package_video_requires_local_media() -> None:
    prod = Production(
        event_id="ev1", production_type=ProductionType.VIDEO, title="标题X", body="正文Y"
    )
    # 缺本地视频文件 → ContentPackage 校验失败（正确失败而非误发为图文）
    with pytest.raises(Exception):
        build_package(prod)
    pkg = build_package(prod, LocalMedia(video_path=Path("v.mp4")))
    assert pkg.format == ContentFormat.VIDEO
    assert pkg.video_path == Path("v.mp4")


def test_build_package_rejects_empty_body() -> None:
    prod = Production(event_id="ev1", production_type=ProductionType.TEXT, title="标题", body="")
    with pytest.raises(Exception):  # ContentPackage 校验：图文必须携带正文
        build_package(prod)


def test_map_result_all_adapter_states() -> None:
    assert map_result(PublishResult(status=AdapterStatus.DRAFT_READY)) == PublishStatus.DRAFT_READY
    assert map_result(PublishResult(status=AdapterStatus.PUBLISHED)) == PublishStatus.PUBLISHED
    assert map_result(PublishResult(status=AdapterStatus.NEEDS_LOGIN)) == PublishStatus.FAILED
    assert map_result(PublishResult(status=AdapterStatus.FAILED)) == PublishStatus.FAILED


# ---- dispatch_item ----

def test_dispatch_pending_fills_draft_and_records_draft_ready(db) -> None:
    acc = _account(db)
    _production(db)
    item = _enqueue(db)
    adapter = FakeAdapter(PublishResult(status=AdapterStatus.DRAFT_READY, message="草稿箱已填好"))

    out = dispatch_item(db, item.id, adapter)

    assert out.status == PublishStatus.DRAFT_READY
    assert out.publish_result == "[draft_ready] 草稿箱已填好"
    pkg, got_acc = adapter.calls[0]
    assert pkg.title == "多图直击：测试事件" and "【事件】" in pkg.body
    assert got_acc.id == acc.id
    assert PublishQueueDao(db).get(item.id).status == PublishStatus.DRAFT_READY


def test_dispatch_auto_publish_account_records_published(db) -> None:
    _account(db, auto_publish=True)
    _production(db)
    item = _enqueue(db)
    adapter = FakeAdapter(PublishResult(status=AdapterStatus.PUBLISHED, message="已自动发布"))

    out = dispatch_item(db, item.id, adapter)

    assert out.status == PublishStatus.PUBLISHED
    assert out.publish_result == "[published] 已自动发布"
    assert out.published_at  # 自动发布成功即记录发布时刻（数据回流时段分析基准）
    assert PublishQueueDao(db).get(item.id).published_at == out.published_at


def test_dispatch_needs_login_records_failed_with_reason(db) -> None:
    _account(db)
    _production(db)
    item = _enqueue(db)
    adapter = FakeAdapter(PublishResult(status=AdapterStatus.NEEDS_LOGIN, message="登录态失效"))

    out = dispatch_item(db, item.id, adapter)

    assert out.status == PublishStatus.FAILED
    assert "登录态失效" in out.publish_result
    assert out.published_at == ""  # 非发布路径不落发布时刻


def test_dispatch_adapter_exception_records_failed_not_raise(db) -> None:
    _account(db)
    _production(db)
    item = _enqueue(db)
    adapter = FakeAdapter(error=RuntimeError("未安装 playwright"))

    out = dispatch_item(db, item.id, adapter)

    assert out.status == PublishStatus.FAILED
    assert "未安装 playwright" in out.publish_result


def test_dispatch_invalid_package_records_failed(db) -> None:
    _account(db)
    _production(db, body="")  # 图文内容包要求正文非空
    item = _enqueue(db)

    out = dispatch_item(db, item.id, FakeAdapter())

    assert out.status == PublishStatus.FAILED
    assert "error:" in out.publish_result


def test_dispatch_missing_production_or_account_records_failed(db) -> None:
    _account(db)
    _production(db)
    orphan_prod = _enqueue(db, production_id="ghost")  # 成品缺失
    orphan_acc = _enqueue(db, production_id="p1", account_id="ghost")  # 账号缺失

    for item in (orphan_prod, orphan_acc):
        out = dispatch_item(db, item.id, FakeAdapter())
        assert out.status == PublishStatus.FAILED
        assert "缺失" in out.publish_result


def test_dispatch_failed_item_can_retry(db) -> None:
    _account(db)
    _production(db)
    item = _enqueue(db)
    failing = FakeAdapter(PublishResult(status=AdapterStatus.FAILED, message="上传超时"))
    dispatch_item(db, item.id, failing)

    ok = FakeAdapter(PublishResult(status=AdapterStatus.DRAFT_READY, message="草稿箱已填好"))
    out = dispatch_item(db, item.id, ok)  # failed 可重新派发

    assert out.status == PublishStatus.DRAFT_READY


@pytest.mark.parametrize(
    "status", [PublishStatus.DRAFT_READY, PublishStatus.SKIPPED, PublishStatus.PUBLISHED]
)
def test_dispatch_rejects_non_dispatchable_status(db, status) -> None:
    _account(db)
    _production(db)
    item = _enqueue(db, status=status)

    with pytest.raises(DispatchError) as ei:
        dispatch_item(db, item.id, FakeAdapter())
    assert ei.value.kind == "bad_status"


def test_dispatch_missing_item_raises_not_found(db) -> None:
    with pytest.raises(DispatchError) as ei:
        dispatch_item(db, "nope", FakeAdapter())
    assert ei.value.kind == "not_found"


# ---- skip / unskip / confirm ----

def test_skip_pending_then_unskip_restores(db) -> None:
    _account(db)
    _production(db)
    item = _enqueue(db)
    PublishQueueDao(db).update_status(
        item.id, PublishStatus.PENDING, publish_result="[failed] 旧派发记录"
    )

    skipped = skip_item(db, item.id)
    assert skipped.status == PublishStatus.SKIPPED

    back = unskip_item(db, item.id)
    assert back.status == PublishStatus.PENDING
    loaded = PublishQueueDao(db).get(item.id)
    assert loaded.status == PublishStatus.PENDING
    assert loaded.publish_result == "[failed] 旧派发记录"  # 跳过/撤销不改写派发记录


def test_skip_rejects_non_pending(db) -> None:
    _account(db)
    _production(db)
    item = _enqueue(db, status=PublishStatus.FAILED)

    with pytest.raises(DispatchError) as ei:
        skip_item(db, item.id)
    assert ei.value.kind == "bad_status"


def test_unskip_rejects_non_skipped(db) -> None:
    _account(db)
    _production(db)
    item = _enqueue(db)

    with pytest.raises(DispatchError) as ei:
        unskip_item(db, item.id)
    assert ei.value.kind == "bad_status"


def test_confirm_draft_ready_records_published(db) -> None:
    _account(db)
    _production(db)
    item = _enqueue(db)
    PublishQueueDao(db).update_status(
        item.id, PublishStatus.DRAFT_READY, publish_result="[draft_ready] 草稿箱已填好"
    )

    out = confirm_published(db, item.id)

    assert out.status == PublishStatus.PUBLISHED
    assert out.publish_result == "人工确认已发布"
    assert out.published_at  # 确认发布记录发布时刻
    reloaded = PublishQueueDao(db).get(item.id)
    assert reloaded.publish_result == "人工确认已发布"
    assert reloaded.published_at == out.published_at


def test_confirm_rejects_non_draft_ready(db) -> None:
    _account(db)
    _production(db)
    item = _enqueue(db)

    with pytest.raises(DispatchError) as ei:
        confirm_published(db, item.id)
    assert ei.value.kind == "bad_status"


# ---- 视频链路（半自动草稿箱 + dispatch_item_now 直达发布）----

def _video_production(db, **kw) -> Production:
    return _production(db, production_type=ProductionType.VIDEO, **kw)


def test_dispatch_video_semi_auto_drafts(db) -> None:
    """D20 勘误：视频有草稿能力，半自动派发走草稿箱（draft_ready），不再 409 拦截。"""
    _account(db)  # auto_publish=False
    _video_production(db)
    item = _enqueue(db)
    adapter = FakeAdapter(
        PublishResult(status=AdapterStatus.DRAFT_READY, message="视频草稿已保存")
    )

    out = dispatch_item(db, item.id, adapter, LocalMedia(video_path=Path("v.mp4")))

    assert out.status == PublishStatus.DRAFT_READY
    _, got_acc = adapter.calls[0]
    assert got_acc.auto_publish is False  # 不强制点发布


def test_dispatch_video_auto_publish_ok(db) -> None:
    _account(db, auto_publish=True)
    _video_production(db)
    item = _enqueue(db)
    adapter = FakeAdapter(PublishResult(status=AdapterStatus.PUBLISHED, message="已自动发布"))

    out = dispatch_item(db, item.id, adapter, LocalMedia(video_path=Path("v.mp4")))

    assert out.status == PublishStatus.PUBLISHED


def test_dispatch_item_now_video_forces_publish(db) -> None:
    acc = _account(db)  # auto_publish=False
    _video_production(db)
    item = _enqueue(db)
    adapter = FakeAdapter(PublishResult(status=AdapterStatus.PUBLISHED, message="已自动发布"))

    out = dispatch_item_now(db, item.id, adapter, LocalMedia(video_path=Path("v.mp4")))

    assert out.status == PublishStatus.PUBLISHED
    _, got_acc = adapter.calls[0]
    assert got_acc.auto_publish is True  # 半自动人工确认 = 强制点发布
    assert got_acc.id == acc.id


def test_dispatch_video_auto_localizes_without_injected_media(db, tmp_path, monkeypatch) -> None:
    """不传 local_media 时视频派发自动执行素材本地化（下载远程素材）。"""
    _account(db, auto_publish=True)
    _video_production(db, asset_ids=["v1"])
    MediaAssetDao(db).insert(
        MediaAsset(
            id="v1",
            event_id="ev1",
            type=MediaType.VIDEO,
            source_url="https://x/video.mp4",
            auth_status=AuthStatus.CLEARED,
        )
    )
    monkeypatch.chdir(tmp_path)  # 隔离默认根目录 data/media/
    monkeypatch.setattr(
        "app.pipeline.media_localizer._default_fetch", lambda url: b"VIDEO"
    )
    item = _enqueue(db)
    adapter = FakeAdapter(PublishResult(status=AdapterStatus.PUBLISHED, message="已自动发布"))

    out = dispatch_item(db, item.id, adapter)  # 不传 local_media

    assert out.status == PublishStatus.PUBLISHED
    pkg, _ = adapter.calls[0]
    assert pkg.video_path == Path("data/media/v1.mp4")
    assert pkg.video_path.read_bytes() == b"VIDEO"


def test_dispatch_video_localization_failure_records_failed(db) -> None:
    """素材本地化失败（无可用视频素材）落 failed，不冒泡、不投适配器。"""
    _account(db, auto_publish=True)
    _video_production(db, asset_ids=["ghost"])  # asset_ids 指向不存在的素材
    item = _enqueue(db)
    adapter = FakeAdapter(PublishResult(status=AdapterStatus.PUBLISHED, message="已自动发布"))

    out = dispatch_item(db, item.id, adapter)

    assert out.status == PublishStatus.FAILED
    assert "素材本地化失败" in out.publish_result
    assert adapter.calls == []


def test_dispatch_item_now_rejects_non_video(db) -> None:
    _account(db)
    _production(db)  # IMAGE_SLIDESHOW → 图文
    item = _enqueue(db)

    with pytest.raises(DispatchError) as ei:
        dispatch_item_now(db, item.id, FakeAdapter())
    assert ei.value.kind == "bad_status"


def test_dispatch_item_now_rejects_non_pending(db) -> None:
    _account(db)
    _video_production(db)
    item = _enqueue(db, status=PublishStatus.DRAFT_READY)

    with pytest.raises(DispatchError) as ei:
        dispatch_item_now(db, item.id, FakeAdapter())
    assert ei.value.kind == "bad_status"
