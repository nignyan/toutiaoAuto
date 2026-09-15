"""素材入库与重评估测试（D2/D8 口径）。"""

import pytest

from app.daos import DB, EventDao, MediaAssetDao
from app.models import (
    AuthStatus,
    Clarity,
    Event,
    EventStatus,
    MediaAsset,
    MediaType,
)
from app.pipeline.asset_ingest import ingest_asset
from app.pipeline.format_decision import ContentFormat


@pytest.fixture()
def db(tmp_path) -> DB:
    d = DB(tmp_path / "ingest.db")
    d.migrate()
    return d


def _deferred_event(db: DB) -> Event:
    ev = Event(title="某品牌发布会定档", score=55.0, status=EventStatus.DEFERRED)
    EventDao(db).upsert(ev)
    return ev


def _ready_event(db: DB) -> Event:
    ev = Event(title="雅安山火", score=95.0, status=EventStatus.READY)
    EventDao(db).upsert(ev)
    return ev


def _image(auth: AuthStatus = AuthStatus.CLEARED) -> MediaAsset:
    return MediaAsset(type=MediaType.IMAGE, auth_status=auth)


def _video(
    clarity: Clarity = Clarity.CLEAR,
    density: float = 90.0,
    auth: AuthStatus = AuthStatus.CLEARED,
) -> MediaAsset:
    return MediaAsset(type=MediaType.VIDEO, clarity=clarity, info_density=density, auth_status=auth)


def test_ingest_persists_asset_with_event_id(db) -> None:
    ev = _deferred_event(db)
    asset = _image()
    result = ingest_asset(db, ev, asset)

    stored = MediaAssetDao(db).get(asset.id)
    assert stored is not None
    assert stored.event_id == ev.id
    assert result.event_status_changed is False  # 单张图仍命中规则 4


def test_deferred_event_becomes_ready_when_two_cleared_images_added(db) -> None:
    ev = _deferred_event(db)
    r1 = ingest_asset(db, ev, _image())
    assert r1.decision.content_format == ContentFormat.DEFER
    assert r1.event_status_changed is False

    r2 = ingest_asset(db, ev, _image())
    assert r2.decision.content_format == ContentFormat.IMAGE_SLIDESHOW  # 命中规则 2
    assert r2.event_status_changed is True
    assert EventDao(db).get(ev.id).status == EventStatus.READY


def test_deferred_event_ready_via_clear_high_density_video(db) -> None:
    ev = _deferred_event(db)
    result = ingest_asset(db, ev, _video(clarity=Clarity.ULTRACLEAR, density=72))

    assert result.decision.content_format == ContentFormat.VIDEO  # 命中规则 1
    assert result.event_status_changed is True


def test_pending_auth_asset_does_not_unlock_event_d2(db) -> None:
    ev = _deferred_event(db)
    result = ingest_asset(db, ev, _video(auth=AuthStatus.PENDING))

    assert result.decision.content_format == ContentFormat.DEFER  # D2：视同无有效媒体
    assert result.event_status_changed is False
    assert EventDao(db).get(ev.id).status == EventStatus.DEFERRED


def test_source_c_asset_does_not_unlock_event_d2(db) -> None:
    ev = _deferred_event(db)
    blocked = MediaAsset(type=MediaType.IMAGE, source_type="C", auth_status=AuthStatus.CLEARED)
    result = ingest_asset(db, ev, blocked)

    assert result.decision.content_format == ContentFormat.DEFER
    assert result.event_status_changed is False


def test_ready_event_status_unchanged_by_ingest(db) -> None:
    ev = _ready_event(db)
    result = ingest_asset(db, ev, _image())

    assert result.event_status_changed is False
    assert EventDao(db).get(ev.id).status == EventStatus.READY
