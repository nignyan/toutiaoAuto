# NOW — 当前开发状态

> 最后更新：2026-09-17（D20 视频草稿勘误：半自动改走草稿箱，待真机重验）

## 当前阶段
- D20 勘误已落地（代码+测试全绿）：D19 验收结论撤销（误点「定时发布」假阳性），半自动视频改走草稿箱与图文同口径。
- 下一步：真机重验（POST /publish → 视频存草稿 → 用户草稿箱目验 → 后台点发布 → confirm）。

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
- [x] 视频真实发布实机验收（D19）——结论被 D20 撤销（误点定时发布假阳性，list/v2 核验未发布）
- [ ] D20 勘误重验：视频半自动草稿箱链路真机验收（代码就绪，待真机）

## 主要阻塞
- D20 重验需用户配合（草稿箱目验 + 后台点发布 + 人工 confirm）。遗留：封面 file input 校准（D16 P1）、list/v2 视频覆盖验证（验证后可放开视频轮询确认）、素材自动清理（演进项）。

## 最近闭环摘要
- 视频草稿勘误（D20，2026-09-17）：用户目验发现视频编辑页有「存草稿」按钮，推翻 D16 记录（D16 探针在上传阶段取证漏检）。取证确认编辑页 footer 三按钮（存草稿/定时发布/发布）；`button:has-text('发布')` 子串匹配误点「定时发布」是 D19 假阳性根因（list/v2 核验无该标题，视频未发布）。修复：`video_publish_btn` 改 `.video-batch-footer button.byte-btn-primary`、新增 `video_draft_btn`；半自动视频改走草稿箱（dispatch_item 移除 409 拦截，publish-now 保留为直达发布）；轮询继续排除视频（list/v2 覆盖未验证）。假阳性队列项 c449a0e9 改回 failed 待重验。验证：pytest 311 全绿（改写 2 例）、ruff 零违规。
- 素材本地化（D18，2026-09-17）：新模块 `media_localizer.py`——`resolve_targets` 纯函数（asset_ids 顺序第一个 usable 视频 + 封面仅取图片素材）+ `localize_media` 编排（httpx 下载到 `data/media/<asset_id><ext>`，已存在非空即复用，重试幂等跨成品共享）+ `LocalizationError`（no_video/no_url/download_failed）。`dispatcher._dispatch_with` 在 local_media=None 且 VIDEO 时自动本地化，失败落 failed（publish_result 含「素材本地化失败」）不冒泡；`LocalMedia` 定义移入 media_localizer（dispatcher 再导出兼容）；API `get_local_media` 默认 None；`data/` 入 .gitignore。
- 更早闭环（D19 验收存档、已发布列表校准 D17 收尾、数据回流 D15）明细见 `history/2026-09.md` 与 `DECISIONS.md`。
- 工程教训（D15）：PowerShell 无 `&&`/heredoc，git commit 用 `;` 分隔与 `-m`×2；ruff 对 `.scratch/` 一次性探针脚本误报，`extend-exclude` 排除证据区。
- 完成项明细见 `history/2026-09.md`。
