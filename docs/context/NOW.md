# NOW — 当前开发状态

> 最后更新：2026-09-17（素材本地化落地）

## 当前阶段
- 「素材本地化」（D18）已落地：视频派发时自动下载远程素材（视频/封面）到 `data/media/`，视频真实发布链路就绪。
- 下一步：视频真实发布实机验收（CDP Chrome 9222 + 真实视频队列项走 /publish-now）。

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
- [x] 素材本地化（后端：media_localizer + dispatcher 自动本地化接线，2026-09-17）

## 主要阻塞
- 视频真实发布实机验收需用户配合（CDP Chrome 登录态 + 真实视频队列项）；封面 `.xigua-poster-editor` 内部 file input 校准（D16 P1）待真机。其余无阻塞。

## 最近闭环摘要
- 素材本地化（D18，2026-09-17）：新模块 `media_localizer.py`——`resolve_targets` 纯函数（asset_ids 顺序第一个 usable 视频 + 封面仅取图片素材）+ `localize_media` 编排（httpx 下载到 `data/media/<asset_id><ext>`，已存在非空即复用，重试幂等跨成品共享）+ `LocalizationError`（no_video/no_url/download_failed）。`dispatcher._dispatch_with` 在 local_media=None 且 VIDEO 时自动本地化，失败落 failed（publish_result 含「素材本地化失败」）不冒泡；`LocalMedia` 定义移入 media_localizer（dispatcher 再导出兼容）；API `get_local_media` 默认 None；`data/` 入 .gitignore。验证：pytest 311 例全绿（新增 14 例）、ruff 零违规。遗留：封面 file input 校准（P1）、素材自动清理（演进项）。
- 已发布列表真机校准（D17 收尾，2026-09-17）：探针 v1-v4 真机取证（首页候选直查发现线索 → 管理页 25s 捕获交叉验证 → 标题字段终验），确定端点 `/mp/agw/creator_center/list/v2?status=2&type=0&page_size=20&need_stat=true&wenda_type=1&app_id=1231`（status=2=已发布，文章/微头条一并返回）、标题字段 `contents[].article_attr.title`。回填 `SELECTORS["published_list_url"]`，实现 `_parse_published_titles`（code 非 0/结构异常一律空，不误确认）；`list_published_titles` 增加 profile 模式守卫（仅 CDP 生效）。验证：pytest 297 例全绿（新增 4 例）、ruff 零违规、真机端到端适配器拿回 6 条真实标题。探针登记 `scripts/probes/README.md`，决策补记 `DECISIONS.md` D17。
- 更早闭环（数据回流 D15、图文/视频双模式发布 D17 主体）明细见 `history/2026-09.md`。
- 工程教训（D15）：PowerShell 无 `&&`/heredoc，git commit 用 `;` 分隔与 `-m`×2；ruff 对 `.scratch/` 一次性探针脚本误报，`extend-exclude` 排除证据区。
- 完成项明细见 `history/2026-09.md`。
