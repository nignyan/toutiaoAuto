"""只读探针 v3：视频封面 file input 校准（D16 P1）。

v2 结论：点 .fake-upload-trigger → 弹层 .m-poster-upgrade（封面截取/本地上传）；
点「本地上传」→ 出现拖拽卡 .byte-upload.xigua-upload-poster-trigger.upload-thumb-trigger-card，
但 filechooser 未触发（「本地上传」只是切 tab）。v3：继续点拖拽卡本体等 filechooser；
每步 dump input[type=file]，确认 byte-upload 是否动态挂载 image input。
报告：.scratch/selector-calibration/calibration_report_cover_v3.txt
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
REPORT = Path(".scratch/selector-calibration/calibration_report_cover_v3.txt")

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


def dump_file_inputs(page, label: str) -> list:
    nodes = page.query_selector_all("input[type=file]")
    log(f"-- {label}: input[type=file] 共 {len(nodes)} 处 --")
    for i, n in enumerate(nodes):
        accept = (n.get_attribute("accept") or "")[:70]
        log(f"  [{i}] visible={n.is_visible()} accept={accept!r}")
    return nodes


def poster_card_html(page) -> None:
    el = page.query_selector(".xigua-upload-poster-trigger")
    if el is None:
        log("-- 拖拽卡不存在 --")
        return
    html = el.evaluate("e => e.outerHTML")
    log(f"-- .xigua-upload-poster-trigger outerHTML（{len(html)} 字符）--")
    log(html[:3000])


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

            # 步骤1：打开封面弹层
            page.click(".xigua-poster-editor .fake-upload-trigger", timeout=10_000)
            page.wait_for_selector(".m-poster-upgrade", state="visible", timeout=10_000)
            log("弹层已打开（.m-poster-upgrade）")

            # 步骤2：切到「本地上传」tab
            local_tab = page.query_selector(".m-poster-upgrade :text('本地上传')")
            if local_tab is None:
                log("RESULT: NO_LOCAL_TAB")
                return
            local_tab.click()
            page.wait_for_timeout(1_500)
            card = page.query_selector(".xigua-upload-poster-trigger")
            if card is None:
                log("RESULT: NO_DRAG_CARD（本地上传 tab 未渲染拖拽卡）")
                return
            log("拖拽卡已出现 .xigua-upload-poster-trigger")
            poster_card_html(page)
            dump_file_inputs(page, "拖拽卡出现后")

            # 步骤3：点拖拽卡，等 filechooser；失败则找隐藏 image input 直塞
            chooser = None
            fed_directly = False
            try:
                with page.expect_file_chooser(timeout=5_000) as info:
                    card.click()
                chooser = info.value
                log(f"FILECHOOSER: 拖拽卡点击命中 accept="
                    f"{(chooser.element.get_attribute('accept') or '')[:80]!r}")
                chooser.set_files(str(TEST_COVER))
                chooser = "fed"
            except Exception:
                log("拖拽卡点击无 filechooser → 检查是否有隐藏 image input 可直接 set")
                page.wait_for_timeout(1_500)
                nodes = dump_file_inputs(page, "拖拽卡点击后")
                img_inputs = [n for n in nodes
                              if "image" in (n.get_attribute("accept") or "")
                              or any(e in (n.get_attribute("accept") or "")
                                     for e in (".jpg", ".png", ".jpeg", ".webp"))]
                if img_inputs:
                    log(f"FOUND_IMAGE_INPUT: {len(img_inputs)} 处，直接 set_input_files")
                    img_inputs[0].set_input_files(str(TEST_COVER))
                    fed_directly = True
                else:
                    poster_card_html(page)

            # 步骤4：走通任一通道后确认封面预览
            page.wait_for_timeout(5_000)
            stats = page.evaluate(
                """() => {
                    const dlg = document.querySelector('.m-poster-upgrade');
                    const root = document.querySelector('.xigua-poster-editor');
                    const grab = el => el ? {
                        imgs: el.querySelectorAll('img').length,
                        firstImg: el.querySelector('img') ? (el.querySelector('img').src||'').slice(0,100) : '',
                        text: (el.innerText||'').replace(/\\s+/g,' ').slice(0,150)} : null;
                    return {dialog: grab(dlg), poster: grab(root)};
                }"""
            )
            log(f"封面区状态: dialog={stats['dialog']}")
            log(f"           poster={stats['poster']}")
            if chooser == "fed" or fed_directly:
                page.wait_for_timeout(3_000)
                stats2 = page.evaluate(
                    """() => {
                        const dlg = document.querySelector('.m-poster-upgrade');
                        return dlg ? {imgs: dlg.querySelectorAll('img').length,
                            text: (dlg.innerText||'').replace(/\\s+/g,' ').slice(0,200)} : null;
                    }"""
                )
                log(f"喂图后弹层状态: {stats2}")
                channel = "filechooser" if chooser == "fed" else "直塞 image input"
                log(f"RESULT: COVER_SET_OK（通道={channel}，弹层留给用户查看，未存草稿未发布）")
            else:
                log("RESULT: COVER_NOT_SET")
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
