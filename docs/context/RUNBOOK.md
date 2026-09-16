# RUNBOOK — 运行与验收

> 2026-09-16 核验：命令均在本仓库实际执行通过。

## 构建
- 依赖安装：`pip install -e ".[dev]"`（RPA 另装 `pip install -e ".[rpa]"`）

## 测试与门禁（交付前必须全绿）
- 全量测试：`python -m pytest`（当前 211 例）
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
  6. `POST /publish-queue/{item_id}/publish`（派发到 RPA 适配器填草稿箱；pending/failed 可派发，结果落库 draft_ready/published/failed）
  7. `POST /publish-queue/{item_id}/confirm`（头条后台人工点发布后回系统确认 → published）；`/skip`+`/unskip` 跳过可撤销；`PATCH /publish-queue/{item_id}` 改标题/调 sort_key 排序
  8. `POST /pipeline/wait-queue/timeout`（素材等待队列超时归档：DEFERRED 超 24h 未凑齐素材 → ARCHIVED；幂等可重复调用）
  9. `GET /publish-queue?account_id=...`（待发布队列，sort_key 升序默认 FIFO；`GET /productions?status=qualified` 成品捞回）
- 头条登录：`python -m app.publish.cli login --account-id <id>`（RPA 组，真机校准前 SELECTORS 为占位，派发大概率 failed 并落库原因）

## 发布/清理
- 当前无发布流程；清理工作树仅作可回退移动归档，须按授权执行。
