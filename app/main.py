"""应用入口。健康检查 + 管道 API（采集/事件/素材补录/内容生产）。"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI

from app.api.pipeline import router as pipeline_router
from app.daos import DB


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("WORKFLOW_DB", "data/workflow.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = DB(db_path)
    db.migrate()
    app.state.db = db
    yield
    db.close()


app = FastAPI(title="热点内容自动化工作流", version="0.1.0", lifespan=lifespan)

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(router)
app.include_router(pipeline_router)
