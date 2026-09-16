# RUNBOOK — 运行与验收

> 2026-09-16 核验：命令均在本仓库实际执行通过。

## 构建
- 依赖安装：`pip install -e ".[dev]"`（RPA 另装 `pip install -e ".[rpa]"`）

## 测试与门禁（交付前必须全绿）
- 全量测试：`python -m pytest`（当前 161 例）
- 静态检查：`python -m ruff check .`（E/F/I，行宽 100，零违规）
- Demo 冒烟：`node demo/smoke.test.mjs`（14 项；不改动 demo/ 时仍需回归）

## 运行
- 服务：`uvicorn app.main:app --reload`（默认库 `data/workflow.db`，可用环境变量 `WORKFLOW_DB` 覆盖；存量库启动时自动补列迁移）
- 快速验证管线：
  1. `POST /pipeline/collect`（触发采集聚类，可 body 指定 sources）
  2. `POST /events/{id}/assets`（补录素材；DEFERRED 事件自动重评估转 READY）
  3. `POST /pipeline/produce` body `{"event_id": "..."}`（单事件生产；`/pipeline/produce/all` 批量）
  4. `POST /accounts` body `{"name": "主域账号", "daily_quota": 5}`（配置账号；暂停/恢复走 `PATCH /accounts/{id}`；仅实验域可 `DELETE`）
  5. `POST /pipeline/enqueue` body `{"production_id": "..."}`（QUALIFIED 成品分配入队；`/pipeline/enqueue/all` 批量，质量分降序）
  6. `GET /publish-queue?account_id=...`（待发布队列，FIFO；`GET /productions?status=qualified` 成品捞回）
- 头条登录：`python -m app.publish.cli login`（RPA 组，真机校准前 SELECTORS 为占位）

## 发布/清理
- 当前无发布流程；清理工作树仅作可回退移动归档，须按授权执行。
