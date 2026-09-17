# 热点内容自动化工作流

> 从全网热点采集到头条号发布回流，全链路自动化的内容运营系统（MVP）。

## 项目简介

一套用 AI 辅助构建的内容运营自动化系统，覆盖从素材发现到发布复盘的一体化闭环：

```
热点采集 → 选题聚类 → 素材入库 → 内容生产 → 智能质检
    → 账号分配 → 发布队列 → RPA 自动发布 → 数据回流分析
```

系统每天自动采集全网热点、按主题聚类成可选题材，AI 生成图文/视频内容，经自动质检打分后，智能分配到不同账号，最后通过浏览器自动化（Playwright RPA）发布到头条号，并把发布后的表现数据回流用于复盘与调优。

## 核心能力

| 模块 | 能力 |
| --- | --- |
| 采集聚类 | 多源热点采集、主题聚类、事件状态机（READY/PRODUCED 等状态流转） |
| 素材入库 | 图文/视频素材补录，DEFERRED 事件凑齐素材后自动转 READY |
| 内容生产 | 模板化图文内容生成、成品级重生产能力 |
| 智能质检 | 质量评分（≥75 合格 / <75 留存 / 触红线阻断） |
| 账号分配 | ACTIVE 账号按配额分配，垂类精确匹配 > 通用 > 实验域 |
| 发布队列 | pending/draft_ready/published/skipped/failed 五态，FIFO + 手动排序 |
| RPA 发布 | 图文存草稿箱、视频存草稿，支持 CDP 接管真实浏览器复用登录态 |
| 数据回流 | 表现数据手动回填 + 四维分析（形态/时段/垂类/标题长度）+ 建议动作人工决策 |

## 技术栈

- **后端**：Python 3.13+ / FastAPI / Uvicorn
- **存储**：SQLite（MVP 阶段，启动时自动补列迁移）
- **RPA**（可选依赖）：Playwright，通过 CDP 接管已登录的真实 Chrome 复用会话

## 目录结构

```
app/         FastAPI 应用（api / pipeline / publish / daos / models）
tests/       pytest 全量测试
demo/        运营工作台交互 Demo
scripts/     一次性探针脚本（真机选择器校准）
docs/        设计文档 / 规格 / 上下文记忆
```

## 快速开始

```bash
# 安装（RPA 发布链路另装 [rpa]）
pip install -e ".[dev]"

# 运行服务
uvicorn app.main:app --reload

# 全量测试 + 静态检查
python -m pytest
python -m ruff check .
```

服务默认使用 `data/workflow.db`，可通过环境变量 `WORKFLOW_DB` 覆盖路径。

## 使用说明

完整接口说明见 [系统设计文档](./系统设计文档.md)，产品规划见 [热点内容自动化工作流_产品设计.md](./热点内容自动化工作流_产品设计.md)，运行与验收步骤见 [docs/context/RUNBOOK.md](./docs/context/RUNBOOK.md)。

> 注：头条号发布链路依赖已登录的真实 Chrome（CDP 模式），登录态保存于本地 `.profiles/`（已 gitignore）。首次需在该窗口内登录头条号，详见 RUNBOOK。