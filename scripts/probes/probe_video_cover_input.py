"""只读探针：视频封面 file input 校准（D16 P1 遗留项）。

流程：连 CDP → 上传测试视频 → 等「上传成功」→ 取证封面组件结构：
1. 列出页面全部 input[type=file]（含 accept）；
2. 导出 .xigua-poster-editor 子树 HTML；
3. 点击「上传封面」触发器，捕获 filechooser 事件或点击后新出现的 image file input；
4. 选中测试封面图后复查封面区预览状态。
全程不点存草稿/发布，探针结束后关闭本次新建标签页。
报告写入 .scratch/selector-calibration/calibration_report_cover.txt。
用法：python scripts/probes/probe_video_cover_input.py [--cdp-endpoint http://localhost:9222]
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
REPORT = Path(".scratch/selector-calibration/calibration_report_cover.txt")

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


def file_inputs(page, label: str) -> list:
    nodes = page.query_selector_all("input[type=file]")
    log(f"-- {label}: input[type=file] 共 {len(nodes)} 处 --")
    for i, n in enumerate(nodes):
        accept = (n.get_attribute("accept") or "")[:80]
        visible = n.is_visible()
        log(f"  [{i}] visible={visible} accept={accept!r}")
    return nodes


def dump_poster_html(page, label: str, limit: int = 5000) -> None:
    el = page.query_selector(".xigua-poster-editor")
    if el is None:
        log(f"-- {label}: .xigua-poster-editor 不存在 --")
        return
    html = el.evaluate("e => e.outerHTML")
    log(f"-- {label}: .xigua-poster-editor outerHTML（{len(html)} 字符，截断 {limit}）--")
    log(html[:limit])


def find_upload_cover_trigger(page):
    """找「上传封面」可点击触发器：优先 poster 容器内文本节点，回退全局文本。"""
    for sel in (
        ".xigua-poster-editor :text('上传封面')",
        ".form-item-poster :text('上传封面')",
        "text=上传封面",
    ):
        try:
            el = page.query_selector(sel)
        except Exception:
            continue
        if el is not None and el.is_visible():
            log(f"  触发器候选 HIT {sel}")
            return el
        log(f"  触发器候选 MISS {sel}")
    return None


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp-endpoint", default=DEFAULT_ENDPOINT)
    args = parser.parse_args()

    if not _cdp_alive(args.cdp_endpoint):
        log(f"RESULT: CDP_NOT_RUNNING（{args.cdp_endpoint} 未监听）")
        raise SystemExit(2)
    if not TEST_VIDEO.exists():
        log(f"RESULT: NO_TEST_VIDEO（{TEST_VIDEO} 不存在）")
        raise SystemExit(2)
    if not TEST_COVER.exists():
        log(f"RESULT: NO_TEST_COVER（先运行 scripts/probes/make_test_cover.py 生成 {TEST_COVER}）")
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
                log("RESULT: NOT_LOGGED_IN（被重定向到登录页）")
                return
            log(f"== 视频上传页: {page.url} ==")

            log(f"== 上传测试视频: {TEST_VIDEO.name} ({TEST_VIDEO.stat().st_size} bytes) ==")
            page.set_input_files("input[type=file][accept*='video']", str(TEST_VIDEO))
            try:
                page.wait_for_selector("text=上传成功", timeout=120_000)
                log("视频上传完成（出现「上传成功」）")
            except Exception:
                log("RESULT: UPLOAD_TIMEOUT（120s 内未出现「上传成功」）")
                return
            page.wait_for_timeout(3_000)  # 等表单稳定

            file_inputs(page, "上传视频后（点封面触发器前）")
            dump_poster_html(page, "封面组件初始结构")

            log("== 点击「上传封面」触发器 ==")
            trigger = find_upload_cover_trigger(page)
            chooser_file_input = None
            if trigger is None:
                log("RESULT: NO_TRIGGER（未找到「上传封面」可点击元素）")
            else:
                # 路径 A：点击直接弹出原生文件选择器（filechooser 事件）
                try:
                    with page.expect_file_chooser(timeout=5_000) as info:
                        trigger.click()
                    chooser = info.value
                    log(f"FILECHOOSER: 命中（can_multiple={chooser.multiple}, "
                        f"accept={chooser.element.get_attribute('accept')!r}）")
                    chooser.set_files(str(TEST_COVER))
                    chooser_file_input = chooser.element
                except Exception:
                    log("filechooser 未在 5s 内出现 → 路径 B：检查点击后是否新增可见 file input / 弹层")
                    page.wait_for_timeout(1_500)
                    nodes = file_inputs(page, "点击触发器后")
                    img_inputs = [
                        n for n in nodes
                        if "image" in (n.get_attribute("accept") or "")
                        or any(e in (n.get_attribute("accept") or "") for e in (".jpg", ".png", ".jpeg"))
                    ]
                    if img_inputs:
                        chooser_file_input = img_inputs[0]
                        log(f"PATH_B: 新增 image file input，set_input_files → {TEST_COVER.name}")
                        img_inputs[0].set_input_files(str(TEST_COVER))
                    else:
                        dump_poster_html(page, "点击后封面组件结构（可能弹出面板）")

            if chooser_file_input is not None:
                log("== 封面文件已选中，等待预览/编辑面板渲染 ==")
                page.wait_for_timeout(5_000)
                file_inputs(page, "封面选中后")
                dump_poster_html(page, "封面选中后组件结构", limit=4000)
                stats = page.evaluate(
                    """() => {
                        const root = document.querySelector('.xigua-poster-editor');
                        if (!root) return {exists: false};
                        const imgs = root.querySelectorAll('img');
                        return {
                            exists: true,
                            imgs: imgs.length,
                            firstImgSrc: imgs[0] ? (imgs[0].src || '').slice(0, 120) : '',
                            text: (root.innerText || '').replace(/\\s+/g, ' ').slice(0, 200),
                        };
                    }"""
                )
                log(f"封面区状态: {stats}")
                log("RESULT: COVER_SET_OK（封面已选中并观察预览；未存草稿未发布）")
            else:
                log("RESULT: COVER_NOT_SET（触发器路径未走通，见上文取证）")
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
