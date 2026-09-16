"""发布执行测试（D13）：内容包构建、结果映射、派发联动、状态流转守卫。"""

import pytest

from app.daos import DB, AccountDao, ProductionDao, PublishQueueDao
from app.models import (
    Account,
    Production,
    ProductionType,
    PublishQueueItem,
    PublishStatus,
    QualityStatus,
)
from app.pipeline.dispatcher import (
    DispatchError,
    build_package,
    confirm_published,
    dispatch_item,
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

def test_build_package_maps_article_with_title_body() -> None:
    prod = Production(
        event_id="ev1", production_type=ProductionType.VIDEO, title="标题X", body="正文Y"
    )
    pkg = build_package(prod)
    assert pkg.title == "标题X"
    assert pkg.body == "正文Y"
    assert pkg.format == ContentFormat.ARTICLE  # MVP 无本地媒体，按图文投递
    assert pkg.video_path is None and pkg.cover_path is None and pkg.tags == []


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


def test_dispatch_needs_login_records_failed_with_reason(db) -> None:
    _account(db)
    _production(db)
    item = _enqueue(db)
    adapter = FakeAdapter(PublishResult(status=AdapterStatus.NEEDS_LOGIN, message="登录态失效"))

    out = dispatch_item(db, item.id, adapter)

    assert out.status == PublishStatus.FAILED
    assert "登录态失效" in out.publish_result


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
    assert PublishQueueDao(db).get(item.id).publish_result == "人工确认已发布"


def test_confirm_rejects_non_draft_ready(db) -> None:
    _account(db)
    _production(db)
    item = _enqueue(db)

    with pytest.raises(DispatchError) as ei:
        confirm_published(db, item.id)
    assert ei.value.kind == "bad_status"
