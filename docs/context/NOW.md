# NOW — 当前开发状态

> 最后更新：2026-09-16

## 当前阶段
- 「内容生产引擎 + 自动质检」后端已落地（决策 D9，规格见 `docs/specs/2026-09-16_内容生产引擎_设计文档.md`）：READY 事件 → 模板生成 → 一票否决 + 质量分三态 → Production 事务落库，3 个 API 端点。
- 下一步：账号自动分配 + QUALIFIED 成品入待发布队列（下一迭代）；素材等待队列超时归档；头条选择器真机校准（见 RISKS）。

## 活动里程碑
- [x] 产品设计定稿（2026-09-15）
- [x] AGENTS.md 个性化开发规范合并
- [x] PROJECT_INDEX.md 与 docs/context/ 分层结构
- [x] MVP 代码骨架（FastAPI + SQLite + 形态决策）
- [x] 交互 Demo（demo/，模拟数据 + 真实交互，8 视图）
- [x] 头条草稿箱适配器（app/publish/，auto_publish 默认关闭）
- [x] 热点采集 → 事件聚类 → 素材入库（collector / clustering / asset_ingest + 4 端点）
- [x] 内容生产引擎（后端：composer / quality_check / producer + 3 端点，2026-09-16）
- [ ] 账号自动分配 + 待发布队列入队（后端）
- [ ] 头条后台选择器实测校准

## 主要阻塞
- 无。

## 最近闭环摘要
- 按 D9 规格（`eeabcfe`）分批实现：Production 扩展三态质检字段 + production 表/DAO（`989aef8`）→ ContentComposer 协议 + TemplateComposer（`eb378e6`）→ 一票否决 + 确定性质量分纯函数（`3206042`）→ 生产编排 + 3 API 端点（`88cd12c`）。
- 关键实现：事件状态机 `READY → PRODUCED` 一次性（重复生产 409）；形态判定实时复跑（DEFER 矛盾防御）；`db.transaction` 保证成品落库与事件状态跨表原子；`produce_all` 批量容错（失败进 skipped 不中断）；质检三态 QUALIFIED（≥75）/ HELD / BLOCKED（否决优先于分数）。
- 验证：pytest 121/121（新增 composer 12 / quality_check 15 / producer 11 / DAO 3 / API 9）、ruff 零违规、demo 冒烟 14/14。
- 完成项明细见 `history/2026-09.md`。
