# MAP — 项目路径地图

> 权威来源以仓库实际为准，多版本/发布边界在此标注。最后校核：2026-09-16

## 根目录
- `AGENTS.md`：项目工作规范（提交/测试约束 + 个性化开发规范）。
- `PROJECT_INDEX.md`：项目定位、里程碑、阻塞与导航（快速入口）。
- `热点内容自动化工作流_产品设计.md`：MVP 产品设计的权威文档（信息密度口径、形态决策、授权合规等）。

## 上下文（docs/context/）
- `NOW.md`：当前开发状态与最近闭环。
- `MAP.md`：本文件，资产路径地图。
- `RUNBOOK.md`：构建/运行/验收步骤。
- `DECISIONS.md`：已拍板决策与依据。
- `RISKS.md`：风险与缓解。
- `ROADMAP.md`：演进项排期（四档 + 明确不做清单）。
- `history/`：按月完成事项归档。

## 功能规格（docs/specs/）
- `2026-09-15_热点采集聚类素材入库_设计文档.md`：采集→聚类→素材入库迭代的功能规格（D6–D8）。
- `2026-09-16_内容生产引擎_设计文档.md`：生产引擎 + 自动质检迭代的功能规格（D9）。
- `2026-09-16_账号分配与发布队列_设计文档.md`：账号分配 + 待发布队列入队迭代的功能规格（D10）。
- `2026-09-16_发布执行_设计文档.md`：队列状态流转 + RPA 派发联动 + 队列管理操作的功能规格（D13）。
- `2026-09-16_数据回流_设计文档.md`：表现回填 + 四维分析 + 建议动作确认/驳回/回滚的功能规格（D15）。

## 源码（已落地，2026-09-16 校核）
- `app/`：FastAPI 应用主包
  - `models/`：事件（含 timeline、deferred_at/deferred_retries 等待队列字段）、素材、产物（Production 三态质检 + vertical）、账号（含 role 角色域）、发布队列（Pydantic 领域模型；PublishStatus 五态 pending/draft_ready/published/skipped/failed + sort_key + published_at）、数据回流（PerformanceRecord 每成品 1:1 upsert + RefluxSuggestion 建议动作 pending/confirmed/rejected）
  - `app/pipeline/`：业务管道——`format_decision.py` 形态决策、`collector.py` 采集（微博热搜真实源 + Fixture 模拟源，D6）、`clustering.py` bigram Jaccard 聚类（D7）、`asset_ingest.py` 素材入库（D8，等待队列重试计数）、`composer.py` 内容生成器协议 + 模板实现（D9）、`quality_check.py` 一票否决 + 质量分纯函数（D9）、`producer.py` 生产编排（D9，事务落库 + 批量容错）、`allocator.py` 账号分配与入队编排（D10，配额核算 + 批量容错）、`wait_queue.py` 素材等待队列超时归档（D11，纯函数 + 事务批量归档）、`dispatcher.py` 发布执行（D13/D17，build_package 形态映射 + 派发结果容错落库 + skip/unskip/confirm 状态流转 + published_at 落库 + 视频派发自动素材本地化）、`media_localizer.py` 素材本地化（D18，resolve_targets 纯函数 + localize_media 编排，远程素材下载到 data/media/ 按 asset_id 缓存复用）、`draft_poller.py` 图文草稿定时轮询自动确认（D17，零依赖 asyncio）、`reflux.py` 数据回流（D15，build_report 四维分析纯函数 + generate_suggestions 确定性建议 + record_performance/analyze/decide_suggestion 编排）
  - `publish/`：发布适配层（`adapter.py` 协议 + `toutiao_draft.py` 头条草稿箱 RPA + `cli.py` 登录/填充命令）
  - `daos/`：SQLite 持久化（`db.py` 单连接 + threading.Lock + transaction + 存量库补列迁移【事务内禁止 run/query，只用 *_with(conn)】；`event_dao.py` / `asset_dao.py` / `production_dao.py`（含 update_title）/ `account_dao.py` / `publish_queue_dao.py`（含 update_status 可选 published_at/update_sort_key）/ `reflux_dao.py`（RefluxRecordDao upsert + RefluxSuggestionDao 含 delete_pending_with））
  - `api/` + `main.py`：FastAPI 路由——`/health` + 管道 30 端点：采集/事件/素材补录 4（`POST /pipeline/collect`、`GET /events`、`GET /events/{id}`、`POST /events/{id}/assets`）+ 生产 3（`POST /pipeline/produce`、`POST /pipeline/produce/all`、`GET /productions`）+ 账号与队列 7（`POST /accounts`、`GET /accounts`、`PATCH /accounts/{id}`、`DELETE /accounts/{id}`、`POST /pipeline/enqueue`、`POST /pipeline/enqueue/all`、`GET /publish-queue`）+ 等待队列 1（`POST /pipeline/wait-queue/timeout`）+ 发布执行 7（`POST /publish-queue/{id}/publish|publish-now|skip|unskip|confirm`、`PATCH /publish-queue/{id}`，adapter 经 get_adapter 依赖注入、local_media 经 get_local_media 默认 None 走自动本地化）+ 数据回流 8（`POST/GET /reflux/records`、`POST /reflux/analyze`、`GET /reflux/analysis`、`GET /reflux/suggestions`、`POST /reflux/suggestions/{id}/confirm|reject|rollback`）
- `tests/`：pytest（形态决策 11 / 发布适配器 18 / DAO 28 / 采集 11 / 聚类 15 / 素材入库 6 / composer 12 / 质检 15 / 生产编排 11 / 分配入队 17 / 等待队列归档 13 / 发布执行 21 / 素材本地化 12 / 数据回流 48 / API 45+15，共 311 例）
- `demo/`：运营工作台交互 Demo（纯前端 + localStorage，8 视图；`smoke.test.mjs` 冒烟 14 项）
- `pyproject.toml`：依赖与工具配置（`dev` 测试组 / `rpa` Playwright 组）

## 发布/同步边界
- 当前仅本地 Git；无远端、无发布配置。任何 push/Release 需另行授权。