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
- `history/`：按月完成事项归档。

## 功能规格（docs/specs/）
- `2026-09-15_热点采集聚类素材入库_设计文档.md`：采集→聚类→素材入库迭代的功能规格（D6–D8）。
- `2026-09-16_内容生产引擎_设计文档.md`：生产引擎 + 自动质检迭代的功能规格（D9）。
- `2026-09-16_账号分配与发布队列_设计文档.md`：账号分配 + 待发布队列入队迭代的功能规格（D10）。

## 源码（已落地，2026-09-16 校核）
- `app/`：FastAPI 应用主包
  - `models/`：事件（含 timeline）、素材、产物（Production 三态质检 + vertical）、账号（含 role 角色域）、发布队列（Pydantic 领域模型）
  - `pipeline/`：业务管道——`format_decision.py` 形态决策、`collector.py` 采集（微博热搜真实源 + Fixture 模拟源，D6）、`clustering.py` bigram Jaccard 聚类（D7）、`asset_ingest.py` 素材入库（D8）、`composer.py` 内容生成器协议 + 模板实现（D9）、`quality_check.py` 一票否决 + 质量分纯函数（D9）、`producer.py` 生产编排（D9，事务落库 + 批量容错）、`allocator.py` 账号分配与入队编排（D10，配额核算 + 批量容错）
  - `publish/`：发布适配层（`adapter.py` 协议 + `toutiao_draft.py` 头条草稿箱 RPA + `cli.py` 登录/填充命令）
  - `daos/`：SQLite 持久化（`db.py` 单连接 + threading.Lock + transaction + 存量库补列迁移；`event_dao.py` / `asset_dao.py` / `production_dao.py` / `account_dao.py` / `publish_queue_dao.py`）
  - `api/` + `main.py`：FastAPI 路由——`/health` + 管道 14 端点：采集/事件/素材补录 4（`POST /pipeline/collect`、`GET /events`、`GET /events/{id}`、`POST /events/{id}/assets`）+ 生产 3（`POST /pipeline/produce`、`POST /pipeline/produce/all`、`GET /productions`）+ 账号与队列 7（`POST /accounts`、`GET /accounts`、`PATCH /accounts/{id}`、`DELETE /accounts/{id}`、`POST /pipeline/enqueue`、`POST /pipeline/enqueue/all`、`GET /publish-queue`）
- `tests/`：pytest（形态决策 11 / 发布适配器 10 / DAO 22 / 采集 11 / 聚类 15 / 素材入库 6 / composer 12 / 质检 15 / 生产编排 11 / 分配入队 17 / API 31，共 161 例）
- `demo/`：运营工作台交互 Demo（纯前端 + localStorage，8 视图；`smoke.test.mjs` 冒烟 14 项）
- `pyproject.toml`：依赖与工具配置（`dev` 测试组 / `rpa` Playwright 组）

## 发布/同步边界
- 当前仅本地 Git；无远端、无发布配置。任何 push/Release 需另行授权。