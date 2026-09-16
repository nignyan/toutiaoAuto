# NOW — 当前开发状态

> 最后更新：2026-09-16

## 当前阶段
- 「数据回流」闭环（D15，口径见 `DECISIONS.md` 与 `docs/specs/2026-09-16_数据回流_设计文档.md`）：表现数据人工回填（每成品 1:1 upsert）→ 四维分析（形态/时段/垂类/标题长度，互动率为基准）→ 确定性生成建议动作 → 运营确认/驳回/回滚，**不自动调参**（D3）；审核状态回流（§4.6 遗留）随表现记录落库。
- 下一步：MVP 全链路已贯通（采集→生产→发布→回流），剩余里程碑为头条视频链路选择器校准（需用户真机环境）与运营实机验收。

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
- [x] 头条后台选择器实测校准 + 存草稿 CDP 路线（图文链路，2026-09-16；视频链路仍占位）
- [x] 数据回流（§4.7，MVP 仅建议动作：reflux 模型/DAO/编排 + 8 端点，2026-09-16）
- [ ] 头条视频链路选择器真机校准（出 MVP 关键路径）

## 主要阻塞
- 无（数据回流的表现数据依赖运营在真实发布后人工回填）。

## 最近闭环摘要
- 数据回流闭环（D15）：`reflux_records`（production_id 唯一，upsert 覆盖取最新，created_at/首次回填保留）+ `reflux_suggestions`（pending/confirmed/rejected；确认→采纳留痕、驳回终态、**回滚回到待确认可再采纳**——拍板口径）；`publish_queue` 新增 `published_at`（confirm/auto_publish 成功时落库，存量库补列迁移）。分析纯函数 `build_report` 四维聚合 + `generate_suggestions` 确定性规则（组样本 ≥2、互动率相对差 ≥30% 且绝对差 ≥1pp、每维度至多 1 条、垂类排除通用且需 ≥2 个非通用垂类）。API 新增 8 端点：`POST/GET /reflux/records`（回填守卫：仅 published 可回填）、`POST /reflux/analyze`（重建 pending 保留已决策）、`GET /reflux/analysis`（只读）、`GET /reflux/suggestions` + confirm/reject/rollback。
- 验证：pytest 284 例全绿（本批新增 63）、ruff 零违规、demo 冒烟 14 项通过（demo 数据回流视图维持 mock，未接线）。
- 工程教训（D15）：PowerShell 无 `&&`/heredoc，git commit 用 `;` 分隔与 `-m`×2；ruff 对 `.scratch/` 一次性探针脚本误报，`extend-exclude` 排除证据区。
- 完成项明细见 `history/2026-09.md`。
