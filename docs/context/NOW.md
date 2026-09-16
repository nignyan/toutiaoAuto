# NOW — 当前开发状态

> 最后更新：2026-09-16

## 当前阶段
- 「账号自动分配 + 待发布队列入队」后端已落地（决策 D10，规格见 `docs/specs/2026-09-16_账号分配与发布队列_设计文档.md`）：账号 CRUD（4 端点）→ QUALIFIED 成品按「垂类精确匹配 > 通用主域 > 实验域」分配（测试域/暂停/配额满不参与）→ 队列入队与 `production.account_id` 回填（3 端点）。
- 下一步：发布执行（队列状态流转 + RPA 填稿联动）；素材等待队列超时归档；头条选择器真机校准（见 RISKS）。

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
- [ ] 发布执行（队列状态流转 + RPA 填稿联动）
- [ ] 头条后台选择器实测校准

## 主要阻塞
- 无。

## 最近闭环摘要
- 按 D10 规格分批实现：账号/队列模型 + 表与 DAO + 存量库补列迁移（`4bf5bc7`）→ 分配编排 allocator（`9f0538f`）→ 账号 CRUD + enqueue 7 端点（`0829869`）。
- 关键实现：分配纯函数 `pick_account`（资格三过滤 + 三层级 + 稳定排序）；入队与账号回填 `db.transaction` 原子；队列 `UNIQUE(production_id)` 兜底 1:1；当日配额按 UTC 日期前缀核算、批量中即时生效；`enqueue_all` 预过滤已入队成品、skipped 只记真实失败。
- 验证：pytest 161/161（新增 DAO 11 / allocator 17 / API 12）、ruff 零违规、demo 冒烟 14/14。
- 完成项明细见 `history/2026-09.md`。
