# scripts/probes — 一次性真机校准探针

头条号后台 DOM / 发布链路真机取证用的一次性脚本（**非项目常驻代码**）。
证据报告归档在 `.scratch/selector-calibration/`。**验收后本目录可整体删除。**

## 运行前提
- 项目需 editable 安装（脚本内 `from app.publish.toutiao_draft import SELECTORS`）。
- 依赖 Playwright（`rpa` 组）；多数脚本需先启动 CDP Chrome 或准备 profile 登录态，见 `docs/context/RUNBOOK.md`。
- 从项目根运行（脚本内相对路径 `.scratch/`、`.profiles/` 以 cwd 为基准）。

## D14 图文链路校准（2026-09-16）
| 脚本 | 用途 |
| --- | --- |
| calibrate_selectors.py (v3) | 图文页选择器探测 + 自动存草稿生命周期观察 |
| calibrate_draft_verify.py (v4) | 草稿保存全量网络取证 + 草稿箱直查 |
| calibrate_draft_list_check.py (v4b) | 草稿箱 API 直查（fetch draft_list 拿地面真相） |
| calibrate_save_api_capture.py (v4c) | 抓保存 API 请求/响应 body |
| calibrate_save_long_body.py (v4d) | 长正文对照实验 |
| calibrate_save_manual_test.py (v4e) | 人工对照实验（鉴别输入方式 vs 风控） |
| calibrate_save_probe.py | 填稿后保存生命周期监控（网络/页脚/编辑器三层） |
| calibrate_cdp_verify.py (v5) | CDP 链路端到端验证（err_no=0 + 草稿可见） |
| probe_login_state.py | profile 登录态只读探测 |

## D16 视频链路校准（2026-09-17）
| 脚本 | 用途 |
| --- | --- |
| probe_video_permission.py | 视频发布权限只读探测 |
| probe_video_selectors.py | 视频页选择器结构探测（不上传） |
| probe_video_upload_form.py | 上传测试视频 + 表单探测 |
| probe_video_form_ready.py | 上传完成终态二次探测 |