# MAP — 项目路径地图

> 权威来源以仓库实际为准，多版本/发布边界在此标注。最后校核：2026-09-15

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

## 源码（已落地，2026-09-15 校核）
- `app/`：FastAPI 应用主包
  - `models/`：事件、素材、产物、账号、发布队列（Pydantic 领域模型）
  - `pipeline/`：业务管道（`format_decision.py` 形态决策；采集 / 聚类 / 素材入库待新增）
  - `publish/`：发布适配层（`adapter.py` 协议 + `toutiao_draft.py` 头条草稿箱 RPA + `cli.py` 登录/填充命令）
  - `daos/`：SQLite 连接封装（表结构与业务 DAO 待实现）
  - `api/` + `main.py`：FastAPI 路由（当前仅 `/health`）
- `tests/`：pytest（形态决策 11 例 / 发布适配器 10 例 / API 1 例）
- `demo/`：运营工作台交互 Demo（纯前端 + localStorage，8 视图；`smoke.test.mjs` 冒烟 14 项）
- `pyproject.toml`：依赖与工具配置（`dev` 测试组 / `rpa` Playwright 组）

## 发布/同步边界
- 当前仅本地 Git；无远端、无发布配置。任何 push/Release 需另行授权。