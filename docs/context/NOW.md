# NOW — 当前开发状态

> 最后更新：2026-09-16

## 当前阶段
- 「素材等待队列超时归档」后端已落地（决策 D11，口径见 `DECISIONS.md`，需求源产品设计 §4.4）：DEFERRED 事件超 24 小时未凑齐有效素材 → 归档不再尝试；补录尝试计数、归档事件不可被补录复活。
- 下一步：发布执行（队列状态流转 + RPA 填稿联动）；头条选择器真机校准（见 RISKS）。

## 活动里程碑
- [x] 产品设计定稿（2026-09-15）
- [x] AGENTS.md 个性化开发规范合并
- [x] PROJECT_INDEX.md 与 docs/context/ 分层结构
- [x] MVP 代码骨架（FastAPI + SQLite + 形态决策）
- [x] 交互 Demo（demo/，模拟数据 + 真实交互，8 视图）
- [x] 头条草稿箱适配器（app/publish/，auto_publish 默认关闭）
- [x] 热点采集 → 事件聚类 → 素材入库（collector / clustering / asset_ingest + 4 端点）
- [x] 内容生产引擎（后端：composer / quality_check / producer + 3 端点，2026-09-16）
- [x] 账号自动分配 + 待发布队列入队（后端：allocator + 7 端点，2026-09-16）
- [x] 素材等待队列超时归档（后端：wait_queue + 1 端点，2026-09-16）
- [ ] 发布执行（队列状态流转 + RPA 填稿联动）
- [ ] 头条后台选择器实测校准

## 主要阻塞
- 无。

## 最近闭环摘要
- 产品 §4.4 素材等待队列口径落地：`Event.deferred_at`（validator 兜底进入等待队列起点）/ `deferred_retries`（补录尝试计数）字段 + events 表存量库补列；`wait_queue.py` 超时判定纯函数（严格超过 24h，`deferred_at` 缺失回退 `created_at`）+ 事务批量归档编排；`ingest_asset` 对 DEFERRED 事件计重试次数，ARCHIVED 事件补录不复活（「不再尝试」）；API 新增 `POST /pipeline/wait-queue/timeout`（幂等）。
- 验证：pytest 175/175（新增 14）、ruff 零违规、demo 冒烟 14/14。提交 `612ffef`。
- 完成项明细见 `history/2026-09.md`。
