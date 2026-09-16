# NOW — 当前开发状态

> 最后更新：2026-09-16

## 当前阶段
- 「发布执行」后端已落地（决策 D13，口径见 `DECISIONS.md`，规格见 `docs/specs/2026-09-16_发布执行_设计文档.md`，需求源产品设计 §4.6）：队列状态机新增 draft_ready；RPA 派发联动（build_package 图文内容包 + 适配器结果容错落库）；跳过/撤销/人工确认/行内改标题/排序调整全量对齐 §4.6；账号删除守卫扩展至 draft_ready。
- 下一步：头条后台选择器真机校准（SELECTORS 为占位，见 RISKS）；数据回流（§4.7）在其后。

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
- [x] 发布执行（后端：dispatcher + 6 端点，队列 draft_ready 状态机 + sort_key，2026-09-16）
- [ ] 头条后台选择器实测校准
- [ ] 数据回流（§4.7，MVP 仅建议动作）

## 主要阻塞
- 无（真机校准需用户提供头条账号环境，属外部依赖）。

## 最近闭环摘要
- 发布执行闭环（D13）：5 批提交（规格 → 模型/DAO → dispatcher → API → 文档/demo）；队列状态机 pending/draft_ready/published/skipped/failed + sort_key 排序；派发仅 pending/failed、适配器异常与失败容错落库；demo 队列视图同步两段式发布（填草稿箱 → 头条后台点发布 → 回系统确认）。
- 验证：pytest 211 例全绿（新增 36）、ruff 零违规、demo 冒烟 14/14。提交哈希见 `history/2026-09.md`。
- 工程教训（D13）：`DB.transaction()` 持非重入锁，事务内调用 `db.run/query` 会死锁，只用 `*_with(conn)`；已记 RISKS.md。
- 完成项明细见 `history/2026-09.md`。
