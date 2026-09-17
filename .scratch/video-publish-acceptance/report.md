# 视频真实发布实机验收报告（D19，2026-09-17）

> **⚠️ D20 勘误（2026-09-17）**：本报告「一次通过」结论已被撤销——验收实际误点了
> 「定时发布」按钮（见下方勘误节），视频未发布。真实结论以 D20 为准。

## 结论（已撤销）
`POST /publish-queue/{id}/publish-now` 全链路**一次通过**：素材本地化 → CDP 接管真实 Chrome → 视频上传 → 填标题 → 点发布 → 队列 `published`。

## 现场事实
- 账号：真机校准账号 `8b3ad15c...`（primary/active，今日配额 0→1/5）
- CDP Chrome：9222 端口已运行，复用已有 mp.toutiao.com 标签页，登录态有效（探针 probe_cdp_login_state.py）
- 测试事件：`f20009cd...` 影视飓风Tim称iPhoneDuo烫到握不住（/pipeline/collect 新建，timeline=2）
- 测试素材：`d17c5f24...` video，Big Buck Bunny 10s/1MB 样例片（test-videos.co.uk，cleared/B，清晰，密度 80，署名「来源：验收测试样例」）
- 生产：`74f18398...` video / QUALIFIED 80 分（规则 1）
- 队列项：`c449a0e9b5ae48dcbbff0105d532baf1`，标题 PATCH 为「系统联调测试视频（可忽略）」

## 关键结果
```
POST /publish-queue/c449a0e9.../publish-now
HTTP 200
status: published
publish_result: [published] 已自动发布
published_at: 2026-09-17T05:33:03.345394+00:00
```
- 素材本地化落盘：`data/media/d17c5f242c23449697d02bd344a840d8.mp4`（991,017 字节，与源一致）
- 服务进程环境变量 `TOUTIAO_CDP_ENDPOINT=http://localhost:9222`

## 门禁
- pytest 311 passed / ruff 零违规（验收后回归）

## 造数路线教训
- `TemplateComposer._order_assets` 视频按入库原序排前：旧事件 `b5b434aa` 已有空 source_url 的种子视频素材，排在首位会导致本地化 no_url 必败。故改走 collect 新事件 + 只灌真实 URL 素材，天然首位。
- 复用 READY 事件 `7a4a8820` 的路线放弃原因：其可用图片素材 attribution 为空，参与生产即触发「署名缺失」一票否决。

## 遗留
- 封面 `.xigua-poster-editor` 内部 file input 校准（D16 P1）：本次成品无图片素材跳过封面步骤，主链路不受影响，仍待真机校准。
- 头条平台侧：测试视频公开可见，验收后需人工删除。

---

# D20 勘误（2026-09-17，用户目验触发）

## 触发
用户目验 RPA 打开的视频发布编辑页，指出页面明确有「存草稿」按钮——与 D16「视频页无存草稿按钮」记录冲突。

## 探针取证（probe_video_draft_btn.py / probe_video_action_buttons.py）
- 上传阶段（无视频）：无任何动作按钮，仅有「发布视频」页签——D16 探针在此阶段取证，故漏检。
- 编辑阶段（上传完成后）footer 三按钮，均为 `BUTTON > SPAN`，容器 `div.video-batch-footer > div.button-group`：
  - 存草稿：`BUTTON.byte-btn byte-btn-default ...`
  - 定时发布：`BUTTON.byte-btn byte-btn-default ...`
  - 发布：`BUTTON.byte-btn byte-btn-primary ...`（唯一主样式）

## D19 假阳性根因
`video_publish_btn = button:has-text('发布')` 子串匹配命中「定时发布」（DOM 序在「发布」之前）→ 误点定时发布 → 弹定时面板，视频未发布；适配器点击后即返回，队列被误标 published。**list/v2 已发布列表核验：无该测试标题（仅 6 条旧内容）**，假阳性坐实。

## 处置
- 队列项 c449a0e9：published → failed（publish_result 注明勘误，published_at 清空）
- SELECTORS：`video_publish_btn` 改 `.video-batch-footer button.byte-btn-primary`；新增 `video_draft_btn = .video-batch-footer button:has-text('存草稿')`
- 半自动视频改走草稿箱（D20 用户拍板），与图文同口径；publish-now 保留为系统内直达发布入口
- 轮询自动确认继续排除视频（list/v2 视频覆盖未验证），视频确认走人工 confirm

## 修正后重验
- 待补：POST /publish-queue/c449a0e9/publish（半自动草稿路径）→ draft_ready → 用户草稿箱目验 + 后台点发布 → confirm → published。
