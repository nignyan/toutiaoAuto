"""只读探针：视频发布页选择器校准（阶段 2，只探不点/不上传/不提交）。

连接 CDP（local 已登录的调试 Chrome），导航到视频上传页，输出：
  ① 页面关键元素结构清单（input/textarea/contenteditable/button）
  ② 预设候选选择器逐项 HIT/MISS 探测（含命中元素的 tag/placeholder/class/text）
报告写入 .scratch/selector-calibration/calibration_report_video.txt。
用法：python scripts/probe_video_selectors.py [--cdp-endpoint http://localhost:9222]
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

DEFAULT_ENDPOINT = "http://localhost:9222"
VIDEO_URL = "https://mp.toutiao.com/profile_v4/xigua/upload-video"
REPORT = Path(".scratch/selector-calibration/calibration_report_video.txt")

# 候选选择器：{用途: [候选...]}，逐项探测命中数
CANDIDATES = {
    "title（标题框）": [
        "input[placeholder*='标题']",
        "textarea[placeholder*='标题']",
        "input[placeholder*='请输入']",
        "[class*='title'] input",
        "[class*='title'] textarea",
        "[class*='title']",
    ],
    "desc（描述/正文）": [
        "textarea[placeholder*='描述']",
        "textarea[placeholder*='简介']",
        "textarea[placeholder*='补充']",
        "textarea[placeholder*='正文']",
        "div[contenteditable='true']",
        ".ProseMirror",
        "[class*='editor']",
    ],
    "video_input（视频上传 file）": [
        "input[type=file][accept*='video']",
        "input[type=file]",
    ],
    "cover_input（封面上传 file）": [
        "input[type=file][accept*='image']",
        "input[type=file][accept*='jpg']",
        "input[type=file][accept*='png']",
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
    import re

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


def snapshot_structure(page) -> None:
    log("== ① 页面关键元素结构清单 ==")
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


def probe_candidates(page) -> None:
    log("")
    log("== ② 候选选择器 HIT/MISS 探测 ==")
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
                first = _el_info(nodes[0]) if nodes else {}
                detail = (
                    f"（命中 {len(nodes)} 处；首元素 tag={first.get('tag')} "
                    f"placeholder={first.get('placeholder')!r} accept={first.get('accept')!r} "
                    f"class={first.get('class')!r}）"
                )
            log(f"  {mark} {sel} {detail}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp-endpoint", default=DEFAULT_ENDPOINT)
    args = parser.parse_args()

    if not _cdp_alive(args.cdp_endpoint):
        log(f"RESULT: CDP_NOT_RUNNING（{args.cdp_endpoint} 未监听，请先启动调试 Chrome）")
        raise SystemExit(2)

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp_endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = next((p for p in ctx.pages if "mp.toutiao.com" in p.url), None) or ctx.new_page()
        created = "mp.toutiao.com" not in page.url
        try:
            page.goto(VIDEO_URL, wait_until="domcontentloaded")
            # 等上传页核心元素出现（上传拖拽区/文件输入），再等 DOM 稳定
            try:
                page.wait_for_selector("input[type=file]", timeout=20_000)
            except Exception:
                pass
            page.wait_for_timeout(5_000)
            log(f"== 视频上传页: {page.url} ==")
            if "/auth/" in page.url:
                log("RESULT: NOT_LOGGED_IN（被重定向到登录页）")
                return
            snapshot_structure(page)
            probe_candidates(page)
        finally:
            if created:
                try:
                    page.close()
                except Exception:
                    pass
            browser.close()  # CDP：仅断连，不关用户浏览器

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    log(f"\n报告已写入 {REPORT}")


if __name__ == "__main__":
    main()