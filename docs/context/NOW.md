# NOW — 当前开发状态

> 最后更新：2026-09-17（已发布列表真机校准收尾）

## 当前阶段
- 「图文/视频双模式发布」闭环（D17）全部收尾：账号级 `auto_publish` 开关统一覆盖两条链路；`published_list_url` 已真机校准回填（list/v2 端点 + article_attr.title 字段），图文定时轮询自动确认链路已打通。
- 下一步：素材本地化（产本地视频/封面，视频真实发布前置）。

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
- [x] 图文/视频双模式发布（后端：build_package 形态映射 + /publish-now 端点 + draft_poller 定时轮询 + 视频适配器修正，2026-09-17）
- [x] 已发布列表真机校准（list/v2 端点 + article_attr.title 回填 SELECTORS，轮询自动确认链路打通，2026-09-17）

## 主要阻塞
- 素材本地化（产本地视频/封面）为视频真实发布前置，拆出独立迭代。其余无阻塞。

## 最近闭环摘要
- 已发布列表真机校准（D17 收尾，2026-09-17）：探针 v1-v4 真机取证（首页候选直查发现线索 → 管理页 25s 捕获交叉验证 → 标题字段终验），确定端点 `/mp/agw/creator_center/list/v2?status=2&type=0&page_size=20&need_stat=true&wenda_type=1&app_id=1231`（status=2=已发布，文章/微头条一并返回）、标题字段 `contents[].article_attr.title`。回填 `SELECTORS["published_list_url"]`，实现 `_parse_published_titles`（code 非 0/结构异常一律空，不误确认）；`list_published_titles` 增加 profile 模式守卫（仅 CDP 生效）。验证：pytest 297 例全绿（新增 4 例）、ruff 零违规、真机端到端适配器拿回 6 条真实标题。探针登记 `scripts/probes/README.md`，决策补记 `DECISIONS.md` D17。
- 图文/视频双模式发布闭环（D17）：账号级 auto_publish 开关覆盖两条链路（全自动直接发布；半自动图文存草稿+定时轮询自动确认、视频走 /publish-now 强制点发布）；build_package 按 production_type 形态映射（LocalMedia 为素材本地化注入点）；视频适配器回填 D16 选择器并删除 save_draft_btn 坏分支；新增 draft_poller 零依赖 asyncio 定时轮询。验证：pytest 293 例全绿（新增 9 例）、ruff 零违规。遗留：published_list_url 待真机校准 + 素材本地化拆出。
- 数据回流闭环（D15）：`reflux_records`（production_id 唯一，upsert 覆盖取最新，created_at/首次回填保留）+ `reflux_suggestions`（pending/confirmed/rejected；确认→采纳留痕、驳回终态、**回滚回到待确认可再采纳**——拍板口径）；`publish_queue` 新增 `published_at`（confirm/auto_publish 成功时落库，存量库补列迁移）。分析纯函数 `build_report` 四维聚合 + `generate_suggestions` 确定性规则（组样本 ≥2、互动率相对差 ≥30% 且绝对差 ≥1pp、每维度至多 1 条、垂类排除通用且需 ≥2 个非通用垂类）。API 新增 8 端点：`POST/GET /reflux/records`（回填守卫：仅 published 可回填）、`POST /reflux/analyze`（重建 pending 保留已决策）、`GET /reflux/analysis`（只读）、`GET /reflux/suggestions` + confirm/reject/rollback。
- 验证：pytest 284 例全绿（本批新增 63）、ruff 零违规、demo 冒烟 14 项通过（demo 数据回流视图维持 mock，未接线）。
- 工程教训（D15）：PowerShell 无 `&&`/heredoc，git commit 用 `;` 分隔与 `-m`×2；ruff 对 `.scratch/` 一次性探针脚本误报，`extend-exclude` 排除证据区。
- 完成项明细见 `history/2026-09.md`。
