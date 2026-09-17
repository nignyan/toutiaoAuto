"""只读探针 v7：封面流程完整闭环（含二次确认弹窗）。

v6 定案：点「确定」后弹二次确认「完成后无法继续编辑，是否确定完成？」，
需再点二次弹窗内的「确定」。v7 完整流程：
上传视频 → fake-upload-trigger → 本地上传 → 直塞隐藏 image input
→（非 16:9 先完成裁剪）→ 确定 → 二次确认「确定」→ 验证封面入库。
全程不存草稿不发布。报告：.scratch/selector-calibration/calibration_report_cover_v7.txt
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
REPORT = Path(".scratch/selector-calibration/calibration_report_cover_v7.txt")

SECOND_CONFIRM = ".Dialog-container:has-text('完成后无法继续编辑')"

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

            # 等编辑态出现（16:9 直接确定；否则先完成裁剪）
            sure = crop = None
            for _ in range(10):
                page.wait_for_timeout(3_000)
                crop = page.query_selector(".m-poster-upgrade button:has-text('完成裁剪')")
                sure = page.query_selector(".m-poster-upgrade button.btn-sure")
                if sure or crop:
                    break
            if crop is not None:
                log("点「完成裁剪」")
                crop.click()
                page.wait_for_timeout(2_000)
                sure = page.query_selector(".m-poster-upgrade button.btn-sure")
            if sure is None:
                log("RESULT: NO_SURE_BTN")
                return

            log("点「确定」（一级）")
            sure.click()
            page.wait_for_timeout(2_000)

            second = page.query_selector(f"{SECOND_CONFIRM} button.btn-sure") \
                or page.query_selector(f"{SECOND_CONFIRM} button:has-text('确定')")
            if second is None:
                log("RESULT: NO_SECOND_CONFIRM（二次弹窗未出现或结构变化）")
                return
            log("点「确定」（二次确认）")
            second.click()

            closed = False
            for i in range(10):
                page.wait_for_timeout(3_000)
                dlg = page.query_selector(".m-poster-upgrade")
                if dlg is None or not dlg.is_visible():
                    closed = True
                    log(f"弹层已关闭（t={(i + 1) * 3}s）")
                    break
            ps = poster_state(page)
            log(f"封面区最终状态: {ps}")
            if closed and ps.get("big_imgs", 0) > 0:
                log("RESULT: COVER_FLOW_OK（封面已入库表单；未存草稿未发布，页面留给用户查看）")
            elif closed:
                log("RESULT: DIALOG_CLOSED_NO_PREVIEW（弹层关闭但封面区未见预览）")
            else:
                log("RESULT: DIALOG_STUCK（二次确认后 30s 仍未关）")
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
