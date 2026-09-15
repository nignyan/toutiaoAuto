"""应用入口。MVP 提供健康检查；业务路由在后续迭代挂载。"""

from fastapi import APIRouter, FastAPI

app = FastAPI(title="热点内容自动化工作流", version="0.1.0")

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(router)