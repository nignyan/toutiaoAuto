# NOW — 当前开发状态

> 最后更新：2026-09-16

## 当前阶段
- 「头条后台真机校准」闭环（D14，口径见 `DECISIONS.md`）：存草稿失败根因确认为自动化指纹风控（保存 API 恒 err_no=7050），拍板 CDP 路线——适配器 `connect_over_cdp` 接管用户真实 Chrome，探针 v5 实测 err_no=0 且草稿箱可见；图文选择器 5 键校准完成。
- 下一步：数据回流（§4.7，MVP 仅建议动作）。

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
- [x] 头条后台选择器实测校准 + 存草稿 CDP 路线（2026-09-16）
- [ ] 数据回流（§4.7，MVP 仅建议动作）

## 主要阻塞
- 无。

## 最近闭环摘要
- 真机校准闭环（D14）：探针 v4 系列网络取证定位根因（自动化指纹触发保存 API err_no=7050，与选择器/内容长度/填法无关），用户拍板 CDP 路线 A；适配器新增 CDP 模式（复用已开头条标签页、退出仅关本进程新建页、`browser.close()` 仅断连不杀用户浏览器），CLI `--cdp-endpoint` / 环境变量 `TOUTIAO_CDP_ENDPOINT` / API `get_adapter` 三处接线；探针 v5 验证 err_no=0 + pgc_id + 草稿箱可见。证据存档 `.scratch/selector-calibration/`。
- 验证：pytest 221 例全绿（本批新增 6：CDP 模式 4 + get_adapter 接线 2）、ruff 零违规。
- 工程教训（D14）：登录态检测以 URL 为最硬信号（未登录 302 到 /auth/**）；「草稿保存中...」footer 指示 30s+ 不翻转，不是可靠完成信号，填稿后固定等待 + 人工草稿箱确认。
- 完成项明细见 `history/2026-09.md`。
