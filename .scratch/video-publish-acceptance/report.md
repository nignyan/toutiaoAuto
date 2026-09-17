# 视频真实发布实机验收报告（D19，2026-09-17）

## 结论
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
