"""聚类测试：bigram/Jaccard 纯函数 + 并入/新建/阈值边界 + 状态预判（D7/D2）。"""

from app.models import AuthStatus, Clarity, Event, EventStatus, MediaAsset, MediaType
from app.pipeline.clustering import (
    DEFAULT_THRESHOLD,
    cluster_signals,
    jaccard,
    title_bigrams,
)
from app.pipeline.collector import RawSignal

# ---- 纯函数 ----

def test_title_bigrams_strips_whitespace() -> None:
    assert title_bigrams("ab cd") == {"ab", "bc", "cd"}


def test_title_bigrams_single_char_falls_back_to_char() -> None:
    assert title_bigrams("火") == {"火"}


def test_jaccard_identical_and_disjoint() -> None:
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a"}, {"b"}) == 0.0
    assert jaccard(set(), set()) == 0.0


# ---- 工具 ----

def _sig(title: str, heat: float = 80.0, assets=None, url: str = "") -> RawSignal:
    return RawSignal(
        title=title, heat=heat, source="fixture", source_url=url, pending_assets=assets or []
    )


def _video(
    clarity: Clarity = Clarity.CLEAR,
    density: float = 85.0,
    auth: AuthStatus = AuthStatus.CLEARED,
) -> MediaAsset:
    return MediaAsset(type=MediaType.VIDEO, clarity=clarity, info_density=density, auth_status=auth)


def _image() -> MediaAsset:
    return MediaAsset(type=MediaType.IMAGE)


# ---- cluster_signals ----

def test_similar_signals_merge_into_one_event() -> None:
    report = cluster_signals(
        [
            _sig("雅安山火救援", 88),
            _sig("雅安山火扑灭", 70),
        ]
    )
    assert len(report.created) == 1
    assert report.updated == []
    ev = report.created[0]
    assert ev.score == 88.0  # 取 max
    assert len(ev.timeline) == 2
    assert [a.matched for a in report.assignments] == [False, True]
    assert all(a.event_id == ev.id for a in report.assignments)


def test_merge_into_existing_event_keeps_title_and_takes_max_score() -> None:
    existing = Event(title="西藏那曲地震", score=77.0)
    report = cluster_signals([_sig("那曲地震震感", 61)], [existing])

    assert report.created == []
    assert [e.id for e in report.updated] == [existing.id]
    assert existing.score == 77.0
    assert existing.title == "西藏那曲地震"  # 标题保持首条不变
    assert len(existing.timeline) == 1


def test_dissimilar_signal_creates_new_event() -> None:
    existing = Event(title="台风梅花登陆浙江沿海", score=92.0)
    report = cluster_signals([_sig("博物馆暑期参观预约全面数字化", 39)], [existing])

    assert len(report.created) == 1
    assert report.updated == []
    assert report.created[0].score == 39.0


def test_threshold_boundary_is_inclusive() -> None:
    s1 = _sig("abcdef")
    s2 = _sig("abcxyz")
    sim = jaccard(title_bigrams("abcdef"), title_bigrams("abcxyz"))
    at_threshold = cluster_signals([s1, s2], [], threshold=sim)  # == 阈值应并入
    assert len(at_threshold.created) == 1
    just_below = cluster_signals([_sig("abcdef"), _sig("abcxyz")], [], threshold=sim + 0.01)
    assert len(just_below.created) == 2


def test_default_threshold_is_configured() -> None:
    assert DEFAULT_THRESHOLD == 0.35


def test_duplicate_source_url_not_duplicated_in_timeline() -> None:
    url = "https://s.weibo.com/weibo?q=%E5%9C%B0%E9%9C%87"
    report = cluster_signals(
        [_sig("那曲发生地震", 77, url=url), _sig("那曲发生地震", 61, url=url)]
    )
    ev = report.created[0]
    assert len(ev.timeline) == 1  # 同 URL 信号并入但时间线去重
    assert ev.score == 77.0


def test_empty_url_signals_all_append_timeline() -> None:
    report = cluster_signals([_sig("甲事件标题一", 60), _sig("甲事件标题一", 55)])
    assert len(report.created[0].timeline) == 2  # 空 URL 不参与去重


def test_created_event_ready_with_usable_assets() -> None:
    report = cluster_signals([_sig("深海科考完成下潜", 68, assets=[_video()])])
    ev = report.created[0]
    assert ev.status == EventStatus.READY


def test_created_event_deferred_without_assets() -> None:
    report = cluster_signals([_sig("某品牌发布会定档", 55)])
    assert report.created[0].status == EventStatus.DEFERRED


def test_pending_auth_assets_treated_as_no_media_d2() -> None:
    # D2：授权未确认素材视同无有效媒体 → DEFERRED
    report = cluster_signals(
        [_sig("新一代芯片发布", 81, assets=[_video(auth=AuthStatus.PENDING)])]
    )
    assert report.created[0].status == EventStatus.DEFERRED


def test_source_c_assets_treated_as_no_media_d2() -> None:
    blocked = MediaAsset(type=MediaType.IMAGE, source_type="C", auth_status=AuthStatus.CLEARED)
    report = cluster_signals([_sig("禁用来源事件", 66, assets=[blocked, blocked])])
    assert report.created[0].status == EventStatus.DEFERRED


def test_batch_internal_merging_three_variants() -> None:
    report = cluster_signals(
        [
            _sig("四川雅安山火", 95),
            _sig("雅安山火救援", 88),
            _sig("雅安山火扑灭", 70),
        ]
    )
    assert len(report.created) == 1
    ev = report.created[0]
    assert ev.score == 95.0
    assert len(ev.timeline) == 3
    assert len(report.assignments) == 3
