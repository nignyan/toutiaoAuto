"""只读探针 v6：封面「确定」后遮罩层取证（D16 P1 收尾）。

v5 结论：16:9 图直接进「封面编辑」态（无完成裁剪步骤）；点「确定」首次点击命中，
但弹层未关且出现 div.mask 拦截后续点击；console 有平台 JS 错误（reading 'network'）。
v6：点「确定」后长轮询 30s，dump mask 所属 Dialog-container 子树与全部弹层文本，
判定是 loading/二次确认/卡死。全程不存草稿不发布。
报告：.scratch/selector-calibration/calibration_report_cover_v6.txt
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

DEFAULT_ENDPOINT = "http://localhost:9222"
VIDEO_URL = "https://mp.toutiao.com/profile_v4/xigua/upload-video"
TEST_VIDEO = Path("data/media/d17c5f242c23449697d02bd344a840d8.mp4").resolve()
TEST_COVER = Path(".scratch/selector-calibration/test_cover_16x9.png").resolve()
REPORT = Path(".scratch/selector-calibration/calibration_report_cover_v6.txt")

lines: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    lines.append(msg)


def _cdp_alive(endpoint: str) -> bool:
    try:
        with urlopen(endpoint + "/json/version", timeout=2) as r:
            json.loads(r.read())
        return True
    except Exception:
        return False


def overlay_state(page) -> list:
    """列出所有可见的 Dialog-container / mask / loading 层。"""
    return page.evaluate(
        """() => {
            const out = [];
            for (const el of document.querySelectorAll('.Dialog-container, [class*="mask"], [class*="loading"], [class*="spin"]')) {
                const r = el.getBoundingClientRect();
                if (r.width < 10 || r.height < 10) continue;
                const cls = (typeof el.className === 'string' ? el.className : '').slice(0, 80);
                const text = (el.innerText || '').replace(/\\s+/g, ' ').slice(0, 120);
                out.push({cls, text});
            }
            return out.slice(0, 15);
        }"""
    )


def poster_state(page) -> dict:
    return page.evaluate(
        """() => {
            const root = document.querySelector('.xigua-poster-editor');
            if (!root) return {exists: false};
            const imgs = [...root.querySelectorAll('img')].filter(i => i.getBoundingClientRect().width > 20);
            return {exists: true, big_imgs: imgs.length,
                    firstImg: imgs[0] ? (imgs[0].src || '').slice(0, 120) : '',
                    text: (root.innerText || '').replace(/\\s+/g,' ').slice(0, 120)};
        }"""
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp-endpoint", default=DEFAULT_ENDPOINT)
    args = parser.parse_args()

    if not _cdp_alive(args.cdp_endpoint):
        log(f"RESULT: CDP_NOT_RUNNING（{args.cdp_endpoint} 未监听）")
        raise SystemExit(2)
    for p, name in ((TEST_VIDEO, "NO_TEST_VIDEO"), (TEST_COVER, "NO_TEST_COVER")):
        if not p.exists():
            log(f"RESULT: {name}（{p} 不存在）")
            raise SystemExit(2)

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp_endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = next((p for p in ctx.pages if "mp.toutiao.com" in p.url), None) or ctx.new_page()
        created = "mp.toutiao.com" not in page.url
        try:
            page.goto(VIDEO_URL, wait_until="domcontentloaded")
            page.wait_for_selector("input[type=file]", state="attached", timeout=20_000)
            if "/auth/" in page.url:
                log("RESULT: NOT_LOGGED_IN")
                return
            log(f"== 视频上传页: {page.url} ==")

            # 先强制刷新，清掉上一轮探针遗留的弹层状态
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector("input[type=file]", state="attached", timeout=20_000)
            if "上传成功" not in (page.evaluate("() => document.body.innerText") or ""):
                page.set_input_files("input[type=file][accept*='video']", str(TEST_VIDEO))
                page.wait_for_selector("text=上传成功", timeout=120_000)
            log("视频就绪")
            page.wait_for_timeout(3_000)

            page.click(".xigua-poster-editor .fake-upload-trigger", timeout=10_000)
            page.wait_for_selector(".m-poster-upgrade", state="visible", timeout=10_000)
            page.click(".m-poster-upgrade :text('本地上传')", timeout=10_000)
            page.wait_for_selector(
                ".xigua-upload-poster-trigger input[type=file]", state="attached", timeout=10_000)
            page.set_input_files(
                ".xigua-upload-poster-trigger input[type=file]", str(TEST_COVER))

            # 等「确定」出现（16:9 无完成裁剪步骤）
            sure = None
            for _ in range(10):
                page.wait_for_timeout(3_000)
                sure = page.query_selector(".m-poster-upgrade button.btn-sure")
                if sure is not None:
                    break
            if sure is None:
                log("RESULT: NO_SURE_BTN")
                return
            log("== 点「确定」（.btn-sure）后长轮询 30s ==")
            sure.click()
            closed = False
            for i in range(10):
                page.wait_for_timeout(3_000)
                dlg = page.query_selector(".m-poster-upgrade")
                visible = dlg is not None and dlg.is_visible()
                st = overlay_state(page)
                log(f"  [t={(i + 1) * 3}s] dialog_visible={visible} overlays={st}")
                if not visible:
                    closed = True
                    break

            ps = poster_state(page)
            log(f"封面区最终状态: {ps}")
            if closed and ps.get("big_imgs", 0) > 0:
                log("RESULT: COVER_FLOW_OK（封面已入库表单；未存草稿未发布）")
            elif closed:
                log("RESULT: DIALOG_CLOSED_NO_PREVIEW（弹层关闭但封面区未见预览）")
            else:
                log("RESULT: DIALOG_STUCK（确定后弹层 30s 未关，见取证；"
                    "请用户在浏览器窗口手动点「确定」验证人工路径）")
        finally:
            if created:
                try:
                    page.close()
                except Exception:
                    pass
            browser.close()

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    log(f"\n报告已写入 {REPORT}")


if __name__ == "__main__":
    main()
