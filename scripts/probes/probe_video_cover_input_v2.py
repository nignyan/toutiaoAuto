"""只读探针 v2：视频封面 file input 校准（D16 P1）。

v1 结论：封面组件为 .xigua-poster-editor > .fake-upload-trigger（无原生 file input）；
点内层文本未触发 filechooser。v2 改进：
1. 点击 .fake-upload-trigger 本体（而非文本节点）；
2. 同时监听 filechooser / popup 新标签页 / console；
3. 点击后扫描 body 级弹层（modal/dialog/drawer/popover/upload 类）取证；
4. 若弹层内有「本地上传」入口，继续点击并等 filechooser。
全程不存草稿不发布。报告：.scratch/selector-calibration/calibration_report_cover_v2.txt
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
REPORT = Path(".scratch/selector-calibration/calibration_report_cover_v2.txt")

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


def dump_layers(page, label: str) -> None:
    """扫描 body 级可见弹层与封面相关节点。"""
    info = page.evaluate(
        """() => {
            const sels = ['.byte-modal','.byte-dialog','.byte-drawer','.byte-popover',
                          '[class*="modal"]','[class*="dialog"]','[class*="drawer"]',
                          '[class*="popover"]','[class*="upload"]','[class*="poster"]'];
            const seen = new Set();
            const out = [];
            for (const s of sels) {
                for (const el of document.querySelectorAll(s)) {
                    if (seen.has(el)) continue;
                    seen.add(el);
                    const r = el.getBoundingClientRect();
                    if (r.width < 10 || r.height < 10) continue;
                    const text = (el.innerText || '').replace(/\\s+/g, ' ').slice(0, 150);
                    const cls = (typeof el.className === 'string' ? el.className : '').slice(0, 90);
                    out.push({sel: s, tag: el.tagName.toLowerCase(), cls, text});
                }
            }
            return out;
        }"""
    )
    log(f"-- {label}: 可见弹层/封面相关节点 {len(info)} 处 --")
    for item in info:
        log(f"  [{item['sel']}] <{item['tag']} class={item['cls']!r}> text={item['text']!r}")


def dump_file_inputs(page, label: str) -> list:
    nodes = page.query_selector_all("input[type=file]")
    log(f"-- {label}: input[type=file] 共 {len(nodes)} 处 --")
    for i, n in enumerate(nodes):
        accept = (n.get_attribute("accept") or "")[:60]
        log(f"  [{i}] visible={n.is_visible()} accept={accept!r}")
    return nodes


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
        popups = []
        ctx.on("page", lambda p: popups.append(p))
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

            trigger = page.query_selector(".xigua-poster-editor .fake-upload-trigger")
            if trigger is None:
                log("RESULT: NO_TRIGGER（.fake-upload-trigger 不存在）")
                return
            box = trigger.bounding_box()
            log(f"== 触发器 .fake-upload-trigger bounding_box={box} ==")

            log("== 点击触发器（同时等 filechooser 5s + 弹层取证） ==")
            chooser_el = None
            try:
                with page.expect_file_chooser(timeout=5_000) as info:
                    trigger.click()
                chooser = info.value
                accept = chooser.element.get_attribute("accept") or ""
                log(f"FILECHOOSER: 直接命中 multiple={chooser.multiple} accept={accept[:80]!r}")
                chooser_el = chooser.element
                chooser.set_files(str(TEST_COVER))
            except Exception:
                log("无直接 filechooser → 检查点击后果")
                page.wait_for_timeout(2_000)
                if popups:
                    log(f"POPUP: 新标签页 {len(popups)} 个: "
                        + ", ".join(p.url for p in popups))
                dump_layers(page, "点击触发器后")
                dump_file_inputs(page, "点击触发器后")

                # 弹层内找「本地上传」类入口再点一次
                for sel in ("text=本地上传", "[class*='modal'] :text('上传')",
                            "[class*='drawer'] :text('上传')", "[class*='upload'] :text('本地')"):
                    el = page.query_selector(sel)
                    if el is None or not el.is_visible():
                        continue
                    log(f"== 二级入口 HIT {sel}，点击并等 filechooser 5s ==")
                    try:
                        with page.expect_file_chooser(timeout=5_000) as info2:
                            el.click()
                        chooser = info2.value
                        accept = chooser.element.get_attribute("accept") or ""
                        log(f"FILECHOOSER: 二级命中 multiple={chooser.multiple} accept={accept[:80]!r}")
                        chooser_el = chooser.element
                        chooser.set_files(str(TEST_COVER))
                    except Exception:
                        log("二级点击后仍无 filechooser")
                        page.wait_for_timeout(2_000)
                        dump_layers(page, "二级点击后")
                    break

            if chooser_el is not None:
                log("== 封面文件已选中，等 5s 观察预览 ==")
                page.wait_for_timeout(5_000)
                stats = page.evaluate(
                    """() => {
                        const root = document.querySelector('.xigua-poster-editor');
                        if (!root) return {exists: false};
                        const imgs = root.querySelectorAll('img');
                        return {exists: true, imgs: imgs.length,
                                firstImg: imgs[0] ? (imgs[0].src || '').slice(0, 100) : '',
                                text: (root.innerText || '').replace(/\\s+/g,' ').slice(0, 150)};
                    }"""
                )
                log(f"封面区状态: {stats}")
                dump_layers(page, "封面选中后")
                log("RESULT: COVER_SET_OK（未存草稿未发布，页面留给用户查看）")
            else:
                log("RESULT: COVER_NOT_SET（见上文取证）")
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
