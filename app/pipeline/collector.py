"""热点信号采集：SignalSource 协议 + 微博热搜真实源 + Fixture 模拟源。

设计要点（D6）：
- 协议与 app/publish 的 PublishAdapter 同构，测试用注入式替身，不碰网络；
- 单源失败不影响其他源，fetch_signals 返回逐源状态；
- 微博 num 按 batch min-max 归一为热度 0–100（极差为 0 时取 50，见 D7）。
"""

from datetime import datetime, timezone
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from app.models import AuthStatus, Clarity, MediaAsset, MediaType, SourceType

WEIBO_HOT_URL = "https://weibo.com/ajax/side/hotSearch"


class CollectorError(Exception):
    """单个数据源采集失败。"""


class RawSignal(BaseModel):
    """一条待聚类的热点信号（不落库）。"""

    title: str
    heat: float = Field(ge=0.0, le=100.0)  # 归一化热度 0–100
    source: str
    source_url: str = ""
    published_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    pending_assets: list[MediaAsset] = Field(default_factory=list)


class SourceStatus(BaseModel):
    """单次采集中一个数据源的执行状态。"""

    source: str
    ok: bool = True
    count: int = 0
    error: str = ""


class SignalSource(Protocol):
    """热点信号源协议：一次 fetch 返回一批信号。"""

    name: str

    def fetch(self) -> list[RawSignal]:
        """拉取一批信号，失败抛 CollectorError。"""
        ...


# ---- 微博热搜 ----

def _normalize_heat(nums: list[float]) -> list[float]:
    """batch min-max 归一到 0–100；极差为 0 时全部取 50（D7）。"""
    lo, hi = min(nums), max(nums)
    if hi == lo:
        return [50.0] * len(nums)
    return [round(100.0 * (n - lo) / (hi - lo), 1) for n in nums]


def _search_url(word: str) -> str:
    from urllib.parse import quote

    return f"https://s.weibo.com/weibo?q={quote(word)}"


class WeiboHotSearchSource:
    """微博热搜公开 JSON 适配器（免登录）。"""

    name = "weibo_hot"

    def __init__(self, timeout_s: float = 10.0, client_factory=None) -> None:
        """client_factory: 注入 httpx.Client 工厂（测试用 MockTransport 替换）。"""
        self._timeout_s = timeout_s
        self._client_factory = client_factory

    def fetch(self) -> list[RawSignal]:
        try:
            client = (
                self._client_factory()
                if self._client_factory is not None
                else httpx.Client(timeout=self._timeout_s)
            )
            with client:
                resp = client.get(WEIBO_HOT_URL)
                resp.raise_for_status()
                realtime = resp.json()["data"]["realtime"]
        except CollectorError:
            raise
        except Exception as e:  # 网络层/解析层任何失败都归一为 CollectorError
            raise CollectorError(f"微博热搜采集失败：{e}") from e

        entries = [
            (item["word"], float(item["num"]))
            for item in realtime
            if isinstance(item, dict)
            and item.get("word")
            and isinstance(item.get("num"), (int, float))
        ]
        if not entries:
            raise CollectorError("微博热搜响应中没有有效条目")

        heats = _normalize_heat([num for _, num in entries])
        return [
            RawSignal(
                title=word, heat=heat, source=self.name,
                source_url=_search_url(word),
            )
            for (word, _), heat in zip(entries, heats)
        ]


# ---- Fixture 模拟源 ----

def _video(clarity: Clarity, density: float, auth: AuthStatus = AuthStatus.CLEARED) -> MediaAsset:
    return MediaAsset(
        type=MediaType.VIDEO, clarity=clarity, info_density=density,
        duration_s=42.0, source_type=SourceType.B, auth_status=auth,
        attribution="来源：合作媒体",
    )


def _image(auth: AuthStatus = AuthStatus.CLEARED) -> MediaAsset:
    return MediaAsset(type=MediaType.IMAGE, source_type=SourceType.B, auth_status=auth)


def _sig(title: str, heat: float, assets: list[MediaAsset] | None = None) -> RawSignal:
    return RawSignal(title=title, heat=heat, source="fixture", pending_assets=assets or [])


def _build_default_pool() -> list[RawSignal]:
    """内置模拟信号池：含多组“同事件不同标题”（专测聚类合并）与无素材信号。"""
    return [
        # 组1：山火事件，3 条变体，首条自带可独立成片的视频（规则1）
        _sig("四川雅安山火", 95, [_video(Clarity.CLEAR, 85)]),
        _sig("雅安山火救援", 88),
        _sig("雅安山火扑灭", 70),
        # 组2：台风事件，2 条变体，纯图集（规则2）
        _sig("台风梅花登陆", 92, [_image(), _image()]),
        _sig("台风梅花减弱", 66),
        # 组3：地震事件，2 条变体，视频不足单独立片+单图（规则3）
        _sig("西藏那曲地震", 77, [_video(Clarity.NORMAL, 55), _image()]),
        _sig("那曲地震震感", 61),
        # 组4：无素材信号（规则4 → 素材等待队列）
        _sig("某品牌秋季发布会正式定档", 55),
        # 组5：素材存在但授权未确认（D2：视同无有效媒体 → 规则4）
        _sig("新一代芯片发布 性能提升明显", 81, [_video(Clarity.CLEAR, 90, AuthStatus.PENDING)]),
        # 散点信号
        _sig("国际数学奥赛中国队再夺团体金牌", 64),
        _sig("全国铁路今起实行新列车运行图", 59),
        _sig("多城推出购房新政 优化限购条件", 73, [_image(), _image()]),
        _sig("深海科考船完成万米级下潜任务", 68, [_video(Clarity.ULTRACLEAR, 72)]),
        _sig("新能源汽车出口量创历史新高", 62),
        _sig("多所高校开设人工智能通识课", 47),
        _sig("城市马拉松赛事吸引万人开跑", 58, [_image(), _image()]),
        _sig("网红餐厅卫生问题被立案调查", 84, [_video(Clarity.NORMAL, 55), _image()]),
        _sig("传统村落集中连片保护新规施行", 41),
        _sig("新研究发现咖啡摄入与睡眠时长关联", 44),
        _sig("秋季招聘会首场提供岗位超两万个", 52),
        _sig("国产大飞机新增两条商业航线", 76, [_video(Clarity.CLEAR, 76)]),
        _sig("博物馆暑期参观预约全面数字化", 39),
        _sig("极端高温预警持续 多地启动应急响应", 90, [_image()]),
        _sig("航天员乘组完成第三次出舱活动", 83, [_video(Clarity.CLEAR, 88)]),
        _sig("跨境电商综试区扩容至新一批城市", 57),
        _sig("冷空气来袭北方多地降温明显", 49),
        _sig("非遗工坊带动乡村就业增收", 35),
        _sig("冰壶公开赛中国队晋级决赛", 71, [_image(), _image()]),
        _sig("世界智能制造大会展示人形机器人", 79, [_video(Clarity.CLEAR, 68)]),
        _sig("早高峰地铁新线开通客流平稳", 43),
    ]


DEFAULT_FIXTURE_POOL: list[RawSignal] = _build_default_pool()


class FixtureSource:
    """内置模拟信号源：默认返回静态信号池，也可注入自定义信号（测试）。"""

    name = "fixture"

    def __init__(self, signals: list[RawSignal] | None = None) -> None:
        self._signals = signals

    def fetch(self) -> list[RawSignal]:
        pool = self._signals if self._signals is not None else DEFAULT_FIXTURE_POOL
        return [s.model_copy(deep=True) for s in pool]


# ---- 多源聚合 ----

def fetch_signals(sources: list[SignalSource]) -> tuple[list[RawSignal], list[SourceStatus]]:
    """聚合多源信号；单源失败记录状态并继续（D6 容错）。"""
    signals: list[RawSignal] = []
    statuses: list[SourceStatus] = []
    for src in sources:
        try:
            batch = src.fetch()
            signals.extend(batch)
            statuses.append(SourceStatus(source=src.name, ok=True, count=len(batch)))
        except Exception as e:
            statuses.append(SourceStatus(source=src.name, ok=False, error=str(e)))
    return signals, statuses
