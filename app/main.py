"""应用入口。健康检查 + 管道 API（采集/事件/素材补录/内容生产）。"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI

from app.api.pipeline import router as pipeline_router
from app.daos import DB
from app.pipeline.draft_poller import poller_interval, run_poller
from app.publish.toutiao_draft import ToutiaoDraftAdapter


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("WORKFLOW_DB", "data/workflow.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = DB(db_path)
    db.migrate()
    app.state.db = db

    # 图文发布确认轮询（零依赖 asyncio 后台任务；published_list_url 已真机校准，
    # 未配 TOUTIAO_CDP_ENDPOINT 时仍为空转）
    stop_event = asyncio.Event()
    adapter = ToutiaoDraftAdapter(
        cdp_endpoint=os.environ.get("TOUTIAO_CDP_ENDPOINT") or None
    )
    poller_task = asyncio.create_task(
        run_poller(db, adapter, stop_event, poller_interval())
    )

    yield

    stop_event.set()
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    db.close()


app = FastAPI(title="热点内容自动化工作流", version="0.1.0", lifespan=lifespan)

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(router)
app.include_router(pipeline_router)
