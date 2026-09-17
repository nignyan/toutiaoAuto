"""只读探针 v4：封面弹层收尾动作校准（完成裁剪/确定）+ 封面入库验证。

v3 结论：喂图成功后弹层进入「封面编辑」态，含「完成裁剪」「确定」按钮。
v4 流程：重走 v3 上传+喂图 → 点「完成裁剪」→ 点「确定」→ 验证 .xigua-poster-editor
出现封面预览图。全程不存草稿不发布。
报告：.scratch/selector-calibration/calibration_report_cover_v4.txt
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
TEST_COVER = Path(".scratch/selector-calibration/test_cover.png").resolve()
REPORT = Path(".scratch/selector-calibration/calibration_report_cover_v4.txt")

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


def dialog_state(page) -> dict:
    return page.evaluate(
        """() => {
            const dlg = document.querySelector('.m-poster-upgrade');
            if (!dlg) return {open: false};
            const r = dlg.getBoundingClientRect();
            return {open: r.width > 10, text: (dlg.innerText || '').replace(/\\s+/g,' ').slice(0, 160)};
        }"""
    )


def click_in_dialog(page, text: str) -> bool:
    for sel in (f".m-poster-upgrade button:has-text('{text}')",
                f".m-poster-upgrade :text('{text}')"):
        el = page.query_selector(sel)
        if el is not None and el.is_visible():
            log(f"  点击 {sel}")
            el.click()
            return True
    log(f"  MISS 弹层内按钮「{text}」")
    return False


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

            page.set_input_files("input[type=file][accept*='video']", str(TEST_VIDEO))
            page.wait_for_selector("text=上传成功", timeout=120_000)
            log("视频上传完成")
            page.wait_for_timeout(3_000)

            # 打开弹层 → 本地上传 → 直塞隐藏 image input（v3 校准结论）
            page.click(".xigua-poster-editor .fake-upload-trigger", timeout=10_000)
            page.wait_for_selector(".m-poster-upgrade", state="visible", timeout=10_000)
            page.click(".m-poster-upgrade :text('本地上传')", timeout=10_000)
            page.wait_for_selector(
                ".xigua-upload-poster-trigger input[type=file]", state="attached", timeout=10_000)
            page.wait_for_timeout(1_000)
            log("== 直塞隐藏 image input（不点拖拽卡，避开原生文件框） ==")
            page.set_input_files(
                ".xigua-upload-poster-trigger input[type=file]", str(TEST_COVER))
            page.wait_for_selector(".m-poster-upgrade :text('完成裁剪')", timeout=30_000)
            log("喂图成功，弹层进入封面编辑态")

            # 收尾动作
            log("== 点「完成裁剪」 ==")
            if not click_in_dialog(page, "完成裁剪"):
                log("RESULT: NO_CROP_BTN")
                return
            page.wait_for_timeout(2_000)
            log(f"弹层状态: {dialog_state(page)}")

            log("== 点「确定」 ==")
            if not click_in_dialog(page, "确定"):
                log("RESULT: NO_CONFIRM_BTN")
                return
            page.wait_for_timeout(3_000)
            log(f"弹层状态: {dialog_state(page)}")
            state = poster_state(page)
            log(f"封面区最终状态: {state}")
            if state.get("big_imgs", 0) > 0 and not dialog_state(page)["open"]:
                log("RESULT: COVER_FLOW_OK（封面已入库表单，弹层关闭；未存草稿未发布）")
            else:
                log("RESULT: COVER_FLOW_PARTIAL（见上文状态，请人工查看浏览器）")
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
