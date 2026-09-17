"""图文发布确认定时轮询（draft_poller）测试。"""

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
from app.pipeline.draft_poller import poll_draft_confirms


@pytest.fixture()
def db(tmp_path) -> DB:
    d = DB(tmp_path / "poller.db")
    d.migrate()
    return d


class FakeListAdapter:
    """替身：返回固定的已发布标题列表。"""

    def __init__(self, titles: list[str]):
        self.titles = titles

    def list_published_titles(self, account) -> list[str]:
        return self.titles


def _seed(
    db: DB,
    *,
    account_id: str,
    title: str,
    production_type: ProductionType,
    status: PublishStatus,
) -> PublishQueueItem:
    AccountDao(db).upsert(Account(id=account_id, name=account_id, daily_quota=3))
    prod = Production(
        id=f"prod-{account_id}-{title}",
        event_id="ev1",
        production_type=production_type,
        title=title,
        body="正文",
        quality_status=QualityStatus.QUALIFIED,
    )
    ProductionDao(db).insert(prod)
    item = PublishQueueItem(account_id=account_id, production_id=prod.id, status=status)
    PublishQueueDao(db).insert(item)
    return item


def test_poll_confirms_matching_draft_ready_and_is_idempotent(db) -> None:
    item = _seed(
        db,
        account_id="acc1",
        title="  突发山火  ",
        production_type=ProductionType.TEXT,
        status=PublishStatus.DRAFT_READY,
    )
    adapter = FakeListAdapter(["突发山火"])

    confirmed = poll_draft_confirms(db, adapter)

    assert confirmed == [item.id]
    assert PublishQueueDao(db).get(item.id).status == PublishStatus.PUBLISHED
    # 幂等：已确认项不再 pending，下一轮不命中
    assert poll_draft_confirms(db, adapter) == []


def test_poll_skips_video_and_unmatched(db) -> None:
    video = _seed(
        db,
        account_id="acc1",
        title="视频标题",
        production_type=ProductionType.VIDEO,
        status=PublishStatus.DRAFT_READY,
    )
    article = _seed(
        db,
        account_id="acc1",
        title="未发布图文",
        production_type=ProductionType.TEXT,
        status=PublishStatus.DRAFT_READY,
    )
    adapter = FakeListAdapter(["其他标题"])

    confirmed = poll_draft_confirms(db, adapter)

    assert confirmed == []
    assert PublishQueueDao(db).get(video.id).status == PublishStatus.DRAFT_READY
    assert PublishQueueDao(db).get(article.id).status == PublishStatus.DRAFT_READY


def test_poll_confirms_per_account_titles(db) -> None:
    hit = _seed(
        db,
        account_id="acc1",
        title="命中标题",
        production_type=ProductionType.TEXT,
        status=PublishStatus.DRAFT_READY,
    )
    _seed(
        db,
        account_id="acc2",
        title="命中标题",
        production_type=ProductionType.TEXT,
        status=PublishStatus.DRAFT_READY,
    )

    class PerAccountAdapter:
        def list_published_titles(self, account) -> list[str]:
            return ["命中标题"] if account.id == "acc1" else []

    confirmed = poll_draft_confirms(db, PerAccountAdapter())

    assert confirmed == [hit.id]
    assert PublishQueueDao(db).get(hit.id).status == PublishStatus.PUBLISHED