"""管道相关 API：采集触发、事件查询、素材补录、内容生产（规格 §7 / §8）。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.daos import DB, EventDao, MediaAssetDao, ProductionDao
from app.models import (
    AuthStatus,
    Clarity,
    Event,
    EventStatus,
    MediaAsset,
    MediaType,
    Production,
    QualityStatus,
    SourceType,
)
from app.pipeline.asset_ingest import ingest_asset
from app.pipeline.clustering import ClusterAssignment, cluster_signals
from app.pipeline.collector import (
    FixtureSource,
    SignalSource,
    SourceStatus,
    WeiboHotSearchSource,
    fetch_signals,
)
from app.pipeline.composer import ContentComposer, TemplateComposer
from app.pipeline.format_decision import decide_format
from app.pipeline.producer import ProducerError, produce_all, produce_for_event

router = APIRouter(tags=["pipeline"])


# ---- 依赖 ----

def get_db(request: Request) -> DB:
    return request.app.state.db


def get_sources() -> list[SignalSource]:
    """默认数据源集合；测试用 app.dependency_overrides 注入替身。"""
    return [FixtureSource(), WeiboHotSearchSource()]


def get_composer() -> ContentComposer:
    """composer 工厂（D9 方案 C）；测试用 dependency_overrides 注入替身。"""
    return TemplateComposer()


# ---- 请求/响应模型 ----

class CollectRequest(BaseModel):
    sources: list[str] = Field(default_factory=list)  # 为空时跑全部默认源


class CollectResponse(BaseModel):
    created: list[Event]
    updated: list[Event]
    assignments: list[ClusterAssignment]
    sources: list[SourceStatus]


class AssetIngestRequest(BaseModel):
    type: MediaType
    source_url: str = ""
    source_type: SourceType = SourceType.A
    auth_status: AuthStatus = AuthStatus.PENDING
    auth_evidence: str = ""
    license_business: bool = True
    attribution: str = ""
    clarity: Clarity | None = None
    info_density: float | None = Field(default=None, ge=0.0, le=100.0)
    duration_s: float | None = None
    fingerprint: str = ""


class EventDetailResponse(BaseModel):
    event: Event
    assets: list[MediaAsset]
    decision_format: str
    decision_reason: str


class IngestResponse(BaseModel):
    asset: MediaAsset
    decision_format: str
    decision_reason: str
    event_status_changed: bool


class ProduceRequest(BaseModel):
    event_id: str


class ProduceSkip(BaseModel):
    event_id: str
    reason: str


class ProduceAllResponse(BaseModel):
    produced: list[Production]
    skipped: list[ProduceSkip]


# ---- 端点 ----

@router.post("/pipeline/collect", response_model=CollectResponse)
def collect(
    body: CollectRequest | None = None,
    sources: list[SignalSource] = Depends(get_sources),
    db: DB = Depends(get_db),
) -> CollectResponse:
    if body is not None and body.sources:
        available = sorted({s.name for s in sources})
        wanted = set(body.sources)
        sources = [s for s in sources if s.name in wanted]
        if not sources:
            raise HTTPException(
                status_code=400, detail=f"未找到请求的数据源，可用：{available}"
            )

    signals, statuses = fetch_signals(sources)
    event_dao = EventDao(db)
    report = cluster_signals(signals, event_dao.list_all())

    for ev in report.created:
        event_dao.upsert(ev)
    for ev in report.updated:
        event_dao.upsert(ev)

    # 编排层素材入库：仅新建事件携带的 pending_assets（规格 §6.1）
    for sig, asg in zip(signals, report.assignments):
        if asg.matched or not sig.pending_assets:
            continue
        ev = event_dao.get(asg.event_id)
        if ev is None:  # 理论上不会发生（刚 upsert 过）
            continue
        for asset in sig.pending_assets:
            ingest_asset(db, ev, asset)

    return CollectResponse(
        created=report.created,
        updated=report.updated,
        assignments=report.assignments,
        sources=statuses,
    )


@router.get("/events", response_model=list[Event])
def list_events(
    status: EventStatus | None = None,
    limit: int = 50,
    db: DB = Depends(get_db),
) -> list[Event]:
    return EventDao(db).list_all(status=status, limit=limit)


@router.get("/events/{event_id}", response_model=EventDetailResponse)
def get_event(event_id: str, db: DB = Depends(get_db)) -> EventDetailResponse:
    ev = EventDao(db).get(event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    assets = MediaAssetDao(db).list_by_event(event_id)
    decision = decide_format(assets)
    return EventDetailResponse(
        event=ev,
        assets=assets,
        decision_format=decision.content_format.value,
        decision_reason=decision.reason,
    )


@router.post("/events/{event_id}/assets", response_model=IngestResponse)
def add_asset(
    event_id: str, body: AssetIngestRequest, db: DB = Depends(get_db)
) -> IngestResponse:
    ev = EventDao(db).get(event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    asset = MediaAsset(**body.model_dump())
    result = ingest_asset(db, ev, asset)
    return IngestResponse(
        asset=result.asset,
        decision_format=result.decision.content_format.value,
        decision_reason=result.decision.reason,
        event_status_changed=result.event_status_changed,
    )


@router.post("/pipeline/produce", response_model=Production)
def produce(
    body: ProduceRequest,
    db: DB = Depends(get_db),
    composer: ContentComposer = Depends(get_composer),
) -> Production:
    """单事件生产：200 成品；404 事件不存在；409 非 READY 或已生产。"""
    try:
        return produce_for_event(db, body.event_id, composer)
    except ProducerError as exc:
        code = 404 if exc.kind == "not_found" else 409
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/pipeline/produce/all", response_model=ProduceAllResponse)
def produce_all_endpoint(
    db: DB = Depends(get_db),
    composer: ContentComposer = Depends(get_composer),
) -> ProduceAllResponse:
    """批量生产全部 READY 事件，失败事件进 skipped 不中断。"""
    report = produce_all(db, composer)
    return ProduceAllResponse(
        produced=report.produced,
        skipped=[ProduceSkip(event_id=s.event_id, reason=s.reason) for s in report.skipped],
    )


@router.get("/productions", response_model=list[Production])
def list_productions(
    status: QualityStatus | None = None,
    limit: int = 50,
    db: DB = Depends(get_db),
) -> list[Production]:
    """成品列表（留档捞回入口），可按质检状态过滤。"""
    return ProductionDao(db).list(status=status, limit=limit)
