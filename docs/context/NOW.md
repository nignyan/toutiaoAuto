# NOW — 当前开发状态

> 最后更新：2026-09-15

## 当前阶段
- 「热点采集 → 事件聚类 → 素材入库」后端已落地（决策 D6–D8，规格见 `docs/specs/`）；真实微博热搜源联调通过。
- 下一步：内容生产引擎（后端，衔接形态判定产物）；素材等待队列超时归档；头条选择器真机校准（见 RISKS）。

## 活动里程碑
- [x] 产品设计定稿（2026-09-15）
- [x] AGENTS.md 个性化开发规范合并
- [x] PROJECT_INDEX.md 与 docs/context/ 分层结构
- [x] MVP 代码骨架（FastAPI + SQLite + 形态决策）
- [x] 交互 Demo（demo/，模拟数据 + 真实交互，8 视图）
- [x] 头条草稿箱适配器（app/publish/，auto_publish 默认关闭）
- [x] 热点采集 → 事件聚类 → 素材入库（collector / clustering / asset_ingest + 4 端点）
- [ ] 内容生产引擎（后端）
- [ ] 头条后台选择器实测校准

## 主要阻塞
- 无。

## 最近闭环摘要
- 按 brainstorming 流程拍板 D6–D8，产出设计规格 `docs/specs/2026-09-15_热点采集聚类素材入库_设计文档.md`（03335b6）。
- 分 4 批实现 SignalSource 协议 + 微博/Fixture 双源、bigram Jaccard 聚类（0.35 可配）、素材入库与 DEFERRED→READY 重评估、4 个 API 端点（4d72048…92ee093）。
- 验证：pytest 71/71、ruff 通过、demo 冒烟 14/14；真实微博源 52 条信号端到端落库通过（真实热搜无媒体，事件按 D8 进入素材等待队列）。
- 实测记录：微博接口需浏览器请求头（403 → `DEFAULT_HEADERS`，2026-09-15 有效）。
- 完成项明细见 `history/2026-09.md`。
