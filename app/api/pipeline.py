"""管道相关 API：采集、事件、素材、生产、账号、发布队列与发布执行。"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.daos import (
    DB,
    AccountDao,
    EventDao,
    MediaAssetDao,
    ProductionDao,
    PublishQueueDao,
    RefluxRecordDao,
    RefluxSuggestionDao,
)
from app.models import (
    Account,
    AccountRole,
    AccountStatus,
    AuthStatus,
    Clarity,
    Event,
    EventStatus,
    MediaAsset,
    MediaType,
    PerformanceRecord,
    Production,
    PublishQueueItem,
    PublishStatus,
    QualityStatus,
    RefluxSuggestion,
    ReviewStatus,
    SourceType,
    SuggestionStatus,
)
from app.pipeline.allocator import AllocationError, allocate_for_production, enqueue_all
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
from app.pipeline.dispatcher import (
    DispatchError,
    LocalMedia,
    confirm_published,
    dispatch_item,
    dispatch_item_now,
    skip_item,
    unskip_item,
)
from app.pipeline.format_decision import decide_format
from app.pipeline.producer import ProducerError, produce_all, produce_for_event
from app.pipeline.reflux import (
    AnalysisReport,
    RefluxError,
    analyze,
    compute_report,
    decide_suggestion,
    record_performance,
)
from app.pipeline.wait_queue import archive_expired
from app.publish.adapter import PublishAdapter
from app.publish.toutiao_draft import ToutiaoDraftAdapter

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


def get_adapter() -> PublishAdapter:
    """发布适配器工厂（D13）；测试用 dependency_overrides 注入替身。
    D14：设置环境变量 TOUTIAO_CDP_ENDPOINT 时走 CDP 模式连接用户真实 Chrome
    （profile 模式的自动化指纹会触发头条风控，保存接口 7050）。"""
    return ToutiaoDraftAdapter(cdp_endpoint=os.environ.get("TOUTIAO_CDP_ENDPOINT") or None)


def get_local_media() -> LocalMedia | None:
    """本地媒体文件注入点：默认 None，视频派发时由 dispatcher 自动执行
    素材本地化（下载远程素材到 data/media/，失败落 failed）。测试用
    dependency_overrides 注入 LocalMedia 可强制指定路径、跳过下载。"""
    return None


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


class AccountCreateRequest(BaseModel):
    name: str
    vertical: str = ""
    role: AccountRole = AccountRole.PRIMARY
    daily_quota: int = Field(default=0, ge=0)  # 0 视为不参与自动分配
    publish_window_start: str = ""
    publish_window_end: str = ""
    profile_dir: str = ""


class AccountUpdateRequest(BaseModel):
    """部分更新：仅显式传入的字段生效。"""

    name: str | None = None
    vertical: str | None = None
    role: AccountRole | None = None
    daily_quota: int | None = Field(default=None, ge=0)
    publish_window_start: str | None = None
    publish_window_end: str | None = None
    status: AccountStatus | None = None  # 暂停/恢复走 status
    auto_publish: bool | None = None
    profile_dir: str | None = None


class EnqueueRequest(BaseModel):
    production_id: str


class EnqueueSkip(BaseModel):
    production_id: str
    reason: str


class EnqueueAllResponse(BaseModel):
    enqueued: list[PublishQueueItem]
    skipped: list[EnqueueSkip]


class WaitQueueTimeoutResponse(BaseModel):
    archived: list[Event]
    checked: int  # 扫描的等待中事件数


class QueueItemUpdateRequest(BaseModel):
    """队列项部分更新：行内改标题（落到成品）/ 调整排序，至少显式传入一项。"""

    title: str | None = None
    sort_key: int | None = None


class RefluxRecordRequest(BaseModel):
    """表现数据回填载荷（upsert，每成品一条取最新）。"""

    production_id: str
    exposure: int = Field(default=0, ge=0)
    plays: int = Field(default=0, ge=0)
    completion_rate: float = Field(default=0.0, ge=0.0, le=100.0)  # 百分比口径
    interactions: int = Field(default=0, ge=0)
    negative: int = Field(default=0, ge=0)
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    review_note: str = ""


class RefluxRecordView(BaseModel):
    """表现记录 + 成品/发布上下文（列表展示用）。"""

    record: PerformanceRecord
    production_title: str = ""
    production_type: str = ""
    published_at: str = ""


class AnalyzeResponse(BaseModel):
    """分析报告 + 重建后的待确认建议。"""

    report: AnalysisReport
    suggestions: list[RefluxSuggestion]


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


# ---- 账号矩阵（规格 D10 §6）----

@router.post("/accounts", response_model=Account)
def create_account(body: AccountCreateRequest, db: DB = Depends(get_db)) -> Account:
    account = Account(**body.model_dump())
    AccountDao(db).upsert(account)
    return account


@router.get("/accounts", response_model=list[Account])
def list_accounts(
    status: AccountStatus | None = None,
    db: DB = Depends(get_db),
) -> list[Account]:
    """账号列表（配置时间升序），可按状态过滤。"""
    return AccountDao(db).list(status=status)


@router.patch("/accounts/{account_id}", response_model=Account)
def update_account(
    account_id: str, body: AccountUpdateRequest, db: DB = Depends(get_db)
) -> Account:
    """编辑账号（部分字段更新）；暂停/恢复走 status；域设置保存后立即生效。"""
    account = AccountDao(db).get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    for attr, value in body.model_dump(exclude_unset=True).items():
        setattr(account, attr, value)
    AccountDao(db).upsert(account)
    return account


@router.delete("/accounts/{account_id}")
def delete_account(account_id: str, db: DB = Depends(get_db)) -> dict[str, bool]:
    """删除账号：仅实验域可删（产品口径）；存在待发布/待确认队列项时拒绝。"""
    account = AccountDao(db).get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if account.role != AccountRole.EXPERIMENT:
        raise HTTPException(status_code=409, detail="仅实验域账号可删除")
    queue_dao = PublishQueueDao(db)
    blocking = sum(
        queue_dao.count_for_account(account_id, status=s)
        for s in (PublishStatus.PENDING, PublishStatus.DRAFT_READY)
    )
    if blocking > 0:
        raise HTTPException(status_code=409, detail="账号存在待发布/待确认队列项，不可删除")
    AccountDao(db).delete(account_id)
    return {"deleted": True}


# ---- 账号分配与待发布队列（规格 D10 §5 / §7）----

@router.post("/pipeline/enqueue", response_model=PublishQueueItem)
def enqueue(body: EnqueueRequest, db: DB = Depends(get_db)) -> PublishQueueItem:
    """单成品分配入队：200 队列项；404 成品不存在；409 非 QUALIFIED/已入队/无可用账号。"""
    try:
        return allocate_for_production(db, body.production_id)
    except AllocationError as exc:
        code = 404 if exc.kind == "not_found" else 409
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/pipeline/enqueue/all", response_model=EnqueueAllResponse)
def enqueue_all_endpoint(db: DB = Depends(get_db)) -> EnqueueAllResponse:
    """批量入队全部未入队 QUALIFIED 成品（质量分降序），失败进 skipped 不中断。"""
    report = enqueue_all(db)
    return EnqueueAllResponse(
        enqueued=report.enqueued,
        skipped=[
            EnqueueSkip(production_id=s.production_id, reason=s.reason)
            for s in report.skipped
        ],
    )


@router.post("/pipeline/wait-queue/timeout", response_model=WaitQueueTimeoutResponse)
def wait_queue_timeout(db: DB = Depends(get_db)) -> WaitQueueTimeoutResponse:
    """素材等待队列超时归档：超过 24 小时未凑齐有效素材的等待事件归档，不再尝试。"""
    report = archive_expired(db)
    return WaitQueueTimeoutResponse(archived=report.archived, checked=report.checked)


@router.get("/publish-queue", response_model=list[PublishQueueItem])
def list_publish_queue(
    account_id: str | None = None,
    status: PublishStatus | None = None,
    limit: int = 50,
    db: DB = Depends(get_db),
) -> list[PublishQueueItem]:
    """待发布队列（sort_key 升序，默认退化入队序 FIFO），可按账号/状态过滤。"""
    return PublishQueueDao(db).list(account_id=account_id, status=status, limit=limit)


# ---- 发布执行（规格 D13 §5）----

def _dispatch_error(exc: DispatchError) -> HTTPException:
    code = 404 if exc.kind == "not_found" else 409
    return HTTPException(status_code=code, detail=str(exc))


@router.post("/publish-queue/{item_id}/publish", response_model=PublishQueueItem)
def publish_queue_item(
    item_id: str,
    db: DB = Depends(get_db),
    adapter: PublishAdapter = Depends(get_adapter),
    local_media: LocalMedia | None = Depends(get_local_media),
) -> PublishQueueItem:
    """派发单条队列项到发布适配器（RPA 填稿/存草稿），结果落库。

    图文与视频半自动同口径：存草稿 → draft_ready → 人工在头条后台点发布。
    200 派发完成（draft_ready/published/failed 均属完成）；
    404 队列项不存在；409 状态守卫（仅 pending/failed 可派发）。
    """
    try:
        return dispatch_item(db, item_id, adapter, local_media)
    except DispatchError as exc:
        raise _dispatch_error(exc) from exc


@router.post("/publish-queue/{item_id}/publish-now", response_model=PublishQueueItem)
def publish_queue_item_now(
    item_id: str,
    db: DB = Depends(get_db),
    adapter: PublishAdapter = Depends(get_adapter),
    local_media: LocalMedia | None = Depends(get_local_media),
) -> PublishQueueItem:
    """系统内直达发布（保留入口，内部强制点发布）。

    404 不存在；409 非 pending 或非视频形态。
    """
    try:
        return dispatch_item_now(db, item_id, adapter, local_media)
    except DispatchError as exc:
        raise _dispatch_error(exc) from exc


@router.post("/publish-queue/{item_id}/skip", response_model=PublishQueueItem)
def skip_queue_item(item_id: str, db: DB = Depends(get_db)) -> PublishQueueItem:
    """跳过队列项（可撤销）；404 不存在；409 非 pending。"""
    try:
        return skip_item(db, item_id)
    except DispatchError as exc:
        raise _dispatch_error(exc) from exc


@router.post("/publish-queue/{item_id}/unskip", response_model=PublishQueueItem)
def unskip_queue_item(item_id: str, db: DB = Depends(get_db)) -> PublishQueueItem:
    """撤销跳过，回到待发布；404 不存在；409 非 skipped。"""
    try:
        return unskip_item(db, item_id)
    except DispatchError as exc:
        raise _dispatch_error(exc) from exc


@router.post("/publish-queue/{item_id}/confirm", response_model=PublishQueueItem)
def confirm_queue_item(item_id: str, db: DB = Depends(get_db)) -> PublishQueueItem:
    """人工确认已发布（头条后台点完发布后回系统记录）；404；409 非 draft_ready。"""
    try:
        return confirm_published(db, item_id)
    except DispatchError as exc:
        raise _dispatch_error(exc) from exc


@router.patch("/publish-queue/{item_id}", response_model=PublishQueueItem)
def update_queue_item(
    item_id: str, body: QueueItemUpdateRequest, db: DB = Depends(get_db)
) -> PublishQueueItem:
    """队列项部分更新：行内改标题（落到成品）/ 调整排序（sort_key），至少一项。

    404 队列项不存在；400 空载荷；409 关联成品缺失（理论不发生）。
    """
    queue_dao = PublishQueueDao(db)
    item = queue_dao.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="队列项不存在")
    if body.title is None and body.sort_key is None:
        raise HTTPException(status_code=400, detail="至少提供 title 或 sort_key 之一")
    if body.title is not None and ProductionDao(db).get(item.production_id) is None:
        raise HTTPException(status_code=409, detail="关联成品不存在")  # 事务外预检（锁不可重入）

    with db.transaction() as conn:  # 改标题（production）与排序（队列）跨表原子
        if body.title is not None:
            ProductionDao(db).update_title_with(conn, item.production_id, body.title)
        if body.sort_key is not None:
            queue_dao.update_sort_key_with(conn, item.id, body.sort_key)

    return queue_dao.get(item_id)  # type: ignore[return-value]


# ---- 数据回流（规格 D15 §5：MVP 仅建议动作，不自动调参）----

def _reflux_error(exc: RefluxError) -> HTTPException:
    code = 404 if exc.kind == "not_found" else 409
    return HTTPException(status_code=code, detail=str(exc))


def _record_view(db: DB, record: PerformanceRecord) -> RefluxRecordView:
    """表现记录附成品标题/形态与发布时刻（N+1 查询，MVP 数据量小可接受）。"""
    prod = ProductionDao(db).get(record.production_id)
    item = PublishQueueDao(db).get_by_production(record.production_id)
    return RefluxRecordView(
        record=record,
        production_title=prod.title if prod else "",
        production_type=prod.production_type.value if prod else "",
        published_at=item.published_at if item else "",
    )


@router.post("/reflux/records", response_model=RefluxRecordView)
def upsert_reflux_record(body: RefluxRecordRequest, db: DB = Depends(get_db)) -> RefluxRecordView:
    """回填单成品表现数据（upsert 取最新）+ 平台审核状态。

    200 落库记录；404 成品不存在；409 队列项非 published。
    """
    record = PerformanceRecord(**body.model_dump())
    try:
        persisted = record_performance(db, record)
    except RefluxError as exc:
        raise _reflux_error(exc) from exc
    return _record_view(db, persisted)


@router.get("/reflux/records", response_model=list[RefluxRecordView])
def list_reflux_records(
    limit: int = 50, db: DB = Depends(get_db)
) -> list[RefluxRecordView]:
    """表现记录列表（回填时间倒序，含成品上下文）。"""
    return [_record_view(db, r) for r in RefluxRecordDao(db).list(limit=limit)]


@router.post("/reflux/analyze", response_model=AnalyzeResponse)
def reflux_analyze(db: DB = Depends(get_db)) -> AnalyzeResponse:
    """重算四维分析并重建待确认建议（pending 全量替换，已决策项保留作历史）。"""
    report = analyze(db)
    suggestions = RefluxSuggestionDao(db).list(status=SuggestionStatus.PENDING)
    return AnalyzeResponse(report=report, suggestions=suggestions)


@router.get("/reflux/analysis", response_model=AnalysisReport)
def reflux_analysis(db: DB = Depends(get_db)) -> AnalysisReport:
    """只读分析报告（不重建建议，供前端轮询展示）。"""
    return compute_report(db)


@router.get("/reflux/suggestions", response_model=list[RefluxSuggestion])
def list_reflux_suggestions(
    status: SuggestionStatus | None = None,
    db: DB = Depends(get_db),
) -> list[RefluxSuggestion]:
    """建议动作列表，可按状态过滤（创建时间倒序）。"""
    return RefluxSuggestionDao(db).list(status=status)


@router.post("/reflux/suggestions/{sug_id}/confirm", response_model=RefluxSuggestion)
def confirm_reflux_suggestion(sug_id: str, db: DB = Depends(get_db)) -> RefluxSuggestion:
    """采纳建议（pending → confirmed；MVP 仅记录采纳，不调整任何权重）。"""
    try:
        return decide_suggestion(db, sug_id, "confirm")
    except RefluxError as exc:
        raise _reflux_error(exc) from exc


@router.post("/reflux/suggestions/{sug_id}/reject", response_model=RefluxSuggestion)
def reject_reflux_suggestion(sug_id: str, db: DB = Depends(get_db)) -> RefluxSuggestion:
    """驳回建议（pending → rejected，终态）。"""
    try:
        return decide_suggestion(db, sug_id, "reject")
    except RefluxError as exc:
        raise _reflux_error(exc) from exc


@router.post("/reflux/suggestions/{sug_id}/rollback", response_model=RefluxSuggestion)
def rollback_reflux_suggestion(sug_id: str, db: DB = Depends(get_db)) -> RefluxSuggestion:
    """回滚已采纳建议（confirmed → pending，回到待确认可再采纳）。"""
    try:
        return decide_suggestion(db, sug_id, "rollback")
    except RefluxError as exc:
        raise _reflux_error(exc) from exc
