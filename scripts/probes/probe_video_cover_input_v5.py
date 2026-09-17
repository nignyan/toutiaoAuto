"""只读探针 v5：封面「确定」按钮取证与收尾验证（D16 P1）。

v4 结论：直塞隐藏 image input 喂图成功→「完成裁剪」成功（1080x608 触发低分辨率提示），
但点「确定」后弹层未关闭、封面未入库。v5 取证：
1. 用 1920x1080 横版图（满足建议分辨率，排除低分辨率拦截）；
2. 「完成裁剪」后 dump 弹层内全部可见 button（文本/class/disabled/bbox）；
3. 用 get_by_role(exact) 点「确定」，等 6s 复查弹层与封面区；
4. 若仍未关闭，再点一次并 dump console 错误。
全程不存草稿不发布。报告：.scratch/selector-calibration/calibration_report_cover_v5.txt
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
REPORT = Path(".scratch/selector-calibration/calibration_report_cover_v5.txt")

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


def dump_dialog_buttons(page, label: str) -> None:
    info = page.evaluate(
        """() => {
            const dlg = document.querySelector('.m-poster-upgrade');
            if (!dlg) return [];
            return [...dlg.querySelectorAll('button')].map(b => {
                const r = b.getBoundingClientRect();
                return {text: (b.innerText||'').replace(/\\s+/g,' ').trim().slice(0,30),
                        cls: (b.className||'').slice(0,90),
                        disabled: b.disabled || b.getAttribute('aria-disabled') === 'true',
                        visible: r.width > 5 && r.height > 5,
                        bbox: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]};
            });
        }"""
    )
    log(f"-- {label}: 弹层内 button {len(info)} 个 --")
    for b in info:
        log(f"  text={b['text']!r} disabled={b['disabled']} visible={b['visible']} "
            f"bbox={b['bbox']} class={b['cls']!r}")


def dialog_state(page) -> dict:
    return page.evaluate(
        """() => {
            const dlg = document.querySelector('.m-poster-upgrade');
            if (!dlg) return {open: false};
            const r = dlg.getBoundingClientRect();
            return {open: r.width > 10, text: (dlg.innerText || '').replace(/\\s+/g,' ').slice(0, 160)};
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

    console_errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp_endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = next((p for p in ctx.pages if "mp.toutiao.com" in p.url), None) or ctx.new_page()
        created = "mp.toutiao.com" not in page.url
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        try:
            page.goto(VIDEO_URL, wait_until="domcontentloaded")
            page.wait_for_selector("input[type=file]", state="attached", timeout=20_000)
            if "/auth/" in page.url:
                log("RESULT: NOT_LOGGED_IN")
                return
            log(f"== 视频上传页: {page.url} ==")

            # 清理上一次探针可能遗留的封面弹层（取消/关闭，绝不点确定/存草稿）
            if page.query_selector(".m-poster-upgrade"):
                log("检测到残留封面弹层 → 尝试关闭")
                for sel in (".m-poster-upgrade :text('取消')",
                            ".m-poster-upgrade .byte-modal-close",
                            ".m-poster-upgrade [aria-label*='close']",
                            ".m-poster-upgrade :text('关闭')"):
                    el = page.query_selector(sel)
                    if el is not None and el.is_visible():
                        log(f"  关闭按钮 HIT {sel}")
                        el.click()
                        page.wait_for_timeout(1_000)
                        break
                else:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(1_000)
                if page.query_selector(".m-poster-upgrade"):
                    log("RESULT: STALE_DIALOG（残留弹层无法关闭，请手动处理后重跑）")
                    return

            page.set_input_files("input[type=file][accept*='video']", str(TEST_VIDEO))
            page.wait_for_selector("text=上传成功", timeout=120_000)
            log("视频上传完成")
            page.wait_for_timeout(3_000)

            page.click(".xigua-poster-editor .fake-upload-trigger", timeout=10_000)
            page.wait_for_selector(".m-poster-upgrade", state="visible", timeout=10_000)
            page.click(".m-poster-upgrade :text('本地上传')", timeout=10_000)
            page.wait_for_selector(
                ".xigua-upload-poster-trigger input[type=file]", state="attached", timeout=10_000)
            page.set_input_files(
                ".xigua-upload-poster-trigger input[type=file]", str(TEST_COVER))
            # 轮询弹层状态：16:9 图可能跳过「完成裁剪」直接到编辑/确定态
            crop_btn = confirm_btn = None
            for _ in range(10):
                page.wait_for_timeout(3_000)
                crop_btn = page.query_selector(".m-poster-upgrade button:has-text('完成裁剪')")
                confirm_btn = page.query_selector(".m-poster-upgrade button:has-text('确定')")
                log(f"  轮询: crop={crop_btn is not None} confirm={confirm_btn is not None} "
                    f"dialog={dialog_state(page)['text'][:80]!r}")
                if crop_btn or confirm_btn:
                    break
            if crop_btn is not None:
                log("== 点「完成裁剪」 ==")
                crop_btn.click()
                page.wait_for_timeout(2_000)
                confirm_btn = page.query_selector(".m-poster-upgrade button:has-text('确定')")
            log(f"喂图后弹层: {dialog_state(page)}")
            dump_dialog_buttons(page, "点确定前")

            log("== get_by_role 点「确定」 ==")
            page.get_by_role("button", name="确定", exact=True).first.click(timeout=10_000)
            page.wait_for_timeout(6_000)
            ds = dialog_state(page)
            log(f"确定后弹层: {ds}")
            if ds["open"]:
                log("弹层仍开 → 再点一次并复查")
                try:
                    page.get_by_role("button", name="确定", exact=True).first.click(timeout=5_000)
                except Exception as e:
                    log(f"  二次点击失败: {e}")
                page.wait_for_timeout(6_000)
                ds = dialog_state(page)
                log(f"二次确定后弹层: {ds}")

            ps = poster_state(page)
            log(f"封面区最终状态: {ps}")
            if console_errors:
                log("-- console 错误（最近 10 条）--")
                for m in console_errors[-10:]:
                    log(f"  {m[:200]}")
            if not ds["open"] and ps.get("big_imgs", 0) > 0:
                log("RESULT: COVER_FLOW_OK（封面已入库表单；未存草稿未发布，页面留给用户查看）")
            else:
                log("RESULT: COVER_FLOW_PARTIAL（见上文取证）")
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
