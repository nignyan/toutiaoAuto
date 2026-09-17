"""只读探针：视频上传后表单选择器校准（阶段 2 续，上传测试视频，只探测不发布）。

流程：连 CDP → 进视频上传页 → set_input_files 上传测试视频 → 轮询等待
「标题/描述/封面/发布按钮」表单渲染 → 导出结构清单 + 候选选择器 HIT/MISS。
报告写入 .scratch/selector-calibration/calibration_report_video_uploaded.txt。
用法：python scripts/probe_video_upload_form.py [--cdp-endpoint http://localhost:9222]
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

DEFAULT_ENDPOINT = "http://localhost:9222"
VIDEO_URL = "https://mp.toutiao.com/profile_v4/xigua/upload-video"
TEST_VIDEO = Path(".scratch/selector-calibration/test_video.mp4").resolve()
REPORT = Path(".scratch/selector-calibration/calibration_report_video_uploaded.txt")

CANDIDATES = {
    "title（标题框）": [
        "input[placeholder*='标题']",
        "textarea[placeholder*='标题']",
        "input[placeholder*='请输入']",
        "input[type=text]",
        "[class*='title'] input",
        "[class*='title'] textarea",
    ],
    "desc（描述/正文）": [
        "textarea[placeholder*='描述']",
        "textarea[placeholder*='简介']",
        "textarea[placeholder*='补充']",
        "textarea[placeholder*='正文']",
        "div[contenteditable='true']",
        ".ProseMirror",
        "[class*='editor']",
        "textarea",
    ],
    "cover_input（封面上传 file）": [
        "input[type=file][accept*='image']",
        "input[type=file][accept*='jpg']",
        "input[type=file][accept*='png']",
    ],
    "video_input（视频上传 file）": [
        "input[type=file][accept*='video']",
        "input[type=file]",
    ],
    "tag（标签/话题）": [
        "input[placeholder*='标签']",
        "input[placeholder*='话题']",
        "input[placeholder*='添加']",
    ],
    "save_draft（存草稿）": [
        "button:has-text('存草稿')",
        "text=存草稿",
        "button:has-text('草稿')",
        "button:has-text('保存')",
    ],
    "publish（发布/投稿）": [
        "button:has-text('发布')",
        "button:has-text('投稿')",
        "button:has-text('上传')",
    ],
}

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


def _el_info(el) -> dict:
    def attrs(e, name):
        v = e.get_attribute(name)
        return (v or "").replace("\n", " ").strip()

    tag = el.evaluate("e => e.tagName.toLowerCase()")
    cls = el.evaluate("e => (e.className && typeof e.className === 'string') ? e.className : ''")
    text = el.evaluate("e => (e.innerText || e.textContent || '').replace(/\\s+/g,' ')")
    return {
        "tag": tag,
        "type": attrs(el, "type"),
        "placeholder": attrs(el, "placeholder"),
        "id": attrs(el, "id"),
        "name": attrs(el, "name"),
        "accept": attrs(el, "accept"),
        "class": cls[:90],
        "text": text[:60],
    }


def snapshot(page) -> None:
    groups = [
        ("input", "input"),
        ("textarea", "textarea"),
        ("contenteditable", '[contenteditable="true"]'),
        ("button", "button"),
    ]
    for label, sel in groups:
        nodes = page.query_selector_all(sel)
        log(f"-- {label}（{len(nodes)} 处）--")
        for i, n in enumerate(nodes):
            info = _el_info(n)
            log(
                f"  [{i}] tag={info['tag']} type={info['type']!r} placeholder={info['placeholder']!r} "
                f"accept={info['accept']!r} id={info['id']!r} name={info['name']!r} class={info['class']!r} text={info['text']!r}"
            )


def form_stats(page) -> dict:
    return page.evaluate(
        """() => ({
            textareas: document.querySelectorAll('textarea').length,
            text_inputs: document.querySelectorAll('input[type=text]').length,
            file_inputs: document.querySelectorAll('input[type=file]').length,
            buttons: document.querySelectorAll('button').length,
            contenteditable: document.querySelectorAll('[contenteditable="true"]').length,
            body: (document.body ? document.body.innerText : '').replace(/\\s+/g,' ').slice(0,120)
        })"""
    )


def wait_form(page, max_s=150) -> bool:
    log("== 上传后轮询表单渲染 ==")
    t = 0
    while t < max_s:
        page.wait_for_timeout(3_000)
        t += 3
        s = form_stats(page)
        log(
            f"  [t={t}s] textarea={s['textareas']} text_input={s['text_inputs']} "
            f"file={s['file_inputs']} button={s['buttons']} contenteditable={s['contenteditable']} "
            f"body={s['body']!r}"
        )
        if s["textareas"] > 0 or s["text_inputs"] > 0 or s["buttons"] > 0 or s["contenteditable"] > 0:
            return True
    return False


def probe_candidates(page) -> None:
    log("")
    log("== 候选选择器 HIT/MISS 探测 ==")
    for purpose, sels in CANDIDATES.items():
        log(f"-- {purpose} --")
        for sel in sels:
            try:
                nodes = page.query_selector_all(sel)
            except Exception as e:
                log(f"  ERR  {sel} -> {type(e).__name__}")
                continue
            mark = "HIT " if nodes else "MISS"
            detail = ""
            if nodes:
                first = _el_info(nodes[0])
                detail = (
                    f"（命中 {len(nodes)} 处；首元素 tag={first['tag']} placeholder={first['placeholder']!r} "
                    f"accept={first['accept']!r} class={first['class']!r}）"
                )
            log(f"  {mark} {sel} {detail}")


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

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp_endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = next((p for p in ctx.pages if "mp.toutiao.com" in p.url), None) or ctx.new_page()
        created = "mp.toutiao.com" not in page.url
        try:
            page.goto(VIDEO_URL, wait_until="domcontentloaded")
            page.wait_for_selector("input[type=file]", state="attached", timeout=20_000)
            page.wait_for_timeout(2_000)
            log(f"== 视频上传页: {page.url} ==")
            if "/auth/" in page.url:
                log("RESULT: NOT_LOGGED_IN（被重定向到登录页）")
                return

            up_sel = "input[type=file][accept*='video']"
            log(f"== 上传测试视频: {TEST_VIDEO.name} ({TEST_VIDEO.stat().st_size} bytes) ==")
            page.set_input_files(up_sel, str(TEST_VIDEO))

            rendered = wait_form(page)
            log("")
            log(f"== 表单渲染={'是' if rendered else '否（超时）'} ==")
            snapshot(page)
            probe_candidates(page)
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