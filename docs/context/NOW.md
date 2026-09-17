# NOW — 当前开发状态

> 最后更新：2026-09-17（D21 视频封面 file input 真机校准 + 适配器接线）

## 当前阶段
- MVP 发布链路真机验收全部完成：图文草稿箱（D14）、视频直达发布语义修复 + 半自动草稿箱（D20 重验通过）、视频封面上传（D21）。
- 演进项已排期（2026-09-17）：见 `ROADMAP.md`（四档 + 明确不做清单）；下一迭代候选 = ROADMAP 第一档。

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
- [x] D20 勘误重验：视频半自动草稿箱链路真机闭环（存草稿→人工后台发布→confirm→list/v2 核验，2026-09-17）
- [x] 视频封面 file input 校准 + 适配器接线（D21，弹层→本地上传→隐藏 input→确定→二次确认，2026-09-17）

## 主要阻塞
- 无。遗留（非阻塞）：视频轮询自动确认（维持人工 confirm 的有意取舍，见 D20）、素材自动清理（演进项）。

## 最近闭环摘要
- 视频封面 file input 校准（D21，2026-09-17）：真机探针 v1-v7 取证封面上传完整链路——`.fake-upload-trigger` 弹「封面截取」弹层 → 切「本地上传」→ 拖拽卡内**隐藏 image file input**（直塞 `set_input_files`，无需点卡触发原生框）→ 16:9 直接进编辑态/非 16:9 先「完成裁剪」→「确定」→ 二次确认「完成后无法继续编辑」。关键坑：封面须 ≥1920×1080（618×1000 小图编辑态不渲染卡住）。SELECTORS 删旧 `video_cover`、新增 7 键，`_fill_draft` 视频封面分支改调 `_set_video_cover`。pytest 313（新增 2 例）、ruff 零违规。D16 P1 / D18 出界遗留就此关闭。
- D20 勘误重验通过（2026-09-17）：视频半自动草稿箱链路真机闭环——publish → RPA 点「存草稿」→ draft_ready → 用户后台目验/改标题/点发布 → confirm → published → list/v2 交叉核验通过（列表 6→7 条）。验证发现：视频确认进入 list/v2，但标题会被人工改动，按生产标题精确匹配的轮询对视频不可靠 → 维持人工 confirm 为主（有意取舍）。假阳性队列项 c449a0e9 同条复验成功（本地化缓存复用）。MVP 发布链路真机验收就此收官。
- 视频草稿勘误（D20，2026-09-17）：用户目验发现视频编辑页有「存草稿」按钮，推翻 D16 记录（D16 探针在上传阶段取证漏检）。取证确认编辑页 footer 三按钮（存草稿/定时发布/发布）；`button:has-text('发布')` 子串匹配误点「定时发布」是 D19 假阳性根因（list/v2 核验无该标题，视频未发布）。修复：`video_publish_btn` 改 `.video-batch-footer button.byte-btn-primary`、新增 `video_draft_btn`；半自动视频改走草稿箱（dispatch_item 移除 409 拦截，publish-now 保留为直达发布）；轮询继续排除视频。pytest 311 全绿（改写 2 例）、ruff 零违规。
- 素材本地化（D18，2026-09-17）：新模块 `media_localizer.py`——`resolve_targets` 纯函数（asset_ids 顺序第一个 usable 视频 + 封面仅取图片素材）+ `localize_media` 编排（httpx 下载到 `data/media/<asset_id><ext>`，已存在非空即复用，重试幂等跨成品共享）+ `LocalizationError`（no_video/no_url/download_failed）。`dispatcher._dispatch_with` 在 local_media=None 且 VIDEO 时自动本地化，失败落 failed（publish_result 含「素材本地化失败」）不冒泡；`LocalMedia` 定义移入 media_localizer（dispatcher 再导出兼容）；API `get_local_media` 默认 None；`data/` 入 .gitignore。
- 更早闭环（D19 验收存档、已发布列表校准 D17 收尾、数据回流 D15）明细见 `history/2026-09.md` 与 `DECISIONS.md`。
- 工程教训（D15）：PowerShell 无 `&&`/heredoc，git commit 用 `;` 分隔与 `-m`×2；ruff 对 `.scratch/` 一次性探针脚本误报，`extend-exclude` 排除证据区。
- 完成项明细见 `history/2026-09.md`。
