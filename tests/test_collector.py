"""采集器测试：Fixture 池 + 微博解析/归一化/容错（httpx MockTransport，全离线）。"""

import httpx
import pytest

from app.pipeline.collector import (
    CollectorError,
    FixtureSource,
    RawSignal,
    WeiboHotSearchSource,
    fetch_signals,
)


def _weibo_source(handler) -> WeiboHotSearchSource:
    return WeiboHotSearchSource(
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )


def _weibo_response(entries: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"data": {"realtime": entries}})


# ---- FixtureSource ----

def test_fixture_default_pool_shape() -> None:
    pool = FixtureSource().fetch()
    assert len(pool) == 30
    assert all(0 <= s.heat <= 100 for s in pool)
    with_assets = [s for s in pool if s.pending_assets]
    without_assets = [s for s in pool if not s.pending_assets]
    assert with_assets and without_assets  # 两类信号都存在，供形态判定两条路径使用


def test_fixture_returns_independent_copies() -> None:
    src = FixtureSource()
    a, b = src.fetch(), src.fetch()
    assert a == b
    assert a[0] is not b[0]  # 深拷贝，避免共享可变 pending_assets


def test_fixture_accepts_custom_signals() -> None:
    sig = RawSignal(title="自定义信号", heat=50, source="fixture")
    assert FixtureSource([sig]).fetch() == [sig]


# ---- WeiboHotSearchSource 解析与归一化 ----

def test_weibo_parses_and_normalizes_heat() -> None:
    src = _weibo_source(
        lambda req: _weibo_response(
            [
                {"word": "台风梅花", "num": 100},
                {"word": "地震", "num": 50},
                {"word": "高温", "num": 0},
            ]
        )
    )
    signals = src.fetch()
    assert [s.title for s in signals] == ["台风梅花", "地震", "高温"]
    assert [s.heat for s in signals] == [100.0, 50.0, 0.0]  # min-max 归一
    assert all(s.source == "weibo_hot" for s in signals)
    assert all(s.source_url.startswith("https://s.weibo.com/weibo?q=") for s in signals)


def test_weibo_flat_nums_all_50() -> None:
    src = _weibo_source(
        lambda req: _weibo_response([{"word": "A", "num": 7}, {"word": "B", "num": 7}])
    )
    assert [s.heat for s in src.fetch()] == [50.0, 50.0]


def test_weibo_skips_malformed_entries() -> None:
    src = _weibo_source(
        lambda req: _weibo_response(
            [
                {"word": "有效条目", "num": 30},
                {"num": 99},  # 缺 word
                {"word": "非数字热度", "num": "bad"},  # num 非数值
            ]
        )
    )
    signals = src.fetch()
    assert [s.title for s in signals] == ["有效条目"]
    assert signals[0].heat == 50.0  # 仅剩单条有效条目，极差为 0 → 归一为 50


def test_weibo_http_error_raises_collector_error() -> None:
    def handler(req):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(CollectorError, match="微博热搜采集失败"):
        _weibo_source(handler).fetch()


def test_weibo_bad_structure_raises() -> None:
    src = _weibo_source(lambda req: httpx.Response(200, json={"unexpected": {}}))
    with pytest.raises(CollectorError):
        src.fetch()


def test_weibo_empty_entries_raises() -> None:
    src = _weibo_source(lambda req: _weibo_response([]))
    with pytest.raises(CollectorError, match="没有有效条目"):
        src.fetch()


# ---- fetch_signals 多源聚合与容错 ----

class _BrokenSource:
    name = "broken"

    def fetch(self) -> list[RawSignal]:
        raise CollectorError("源挂了")


def test_fetch_signals_tolerates_single_source_failure() -> None:
    ok = FixtureSource([RawSignal(title="信号1", heat=60, source="fixture")])
    signals, statuses = fetch_signals([_BrokenSource(), ok])

    assert [s.title for s in signals] == ["信号1"]
    assert [st.source for st in statuses] == ["broken", "fixture"]
    assert statuses[0].ok is False and "源挂了" in statuses[0].error
    assert statuses[1].ok is True and statuses[1].count == 1


def test_fetch_signals_aggregates_all_sources() -> None:
    a = FixtureSource([RawSignal(title="A", heat=60, source="fixture")])
    b = FixtureSource(
        [
            RawSignal(title="B", heat=70, source="fixture"),
            RawSignal(title="C", heat=80, source="fixture"),
        ]
    )
    signals, statuses = fetch_signals([a, b])

    assert [s.title for s in signals] == ["A", "B", "C"]
    assert [st.count for st in statuses] == [1, 2]
