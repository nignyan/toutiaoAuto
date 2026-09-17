"""只读探针：视频上传完成后表单终态二次探测（阶段 2 续，不上传、不点击、不发布）。

复用已上传视频的标签页（不 goto 不 set_input_files），等待上传完成（body 无「上传中」），
再 dump 完整结构（input/textarea/contenteditable/button/a 链接）+ 候选选择器探测。
报告写入 .scratch/selector-calibration/calibration_report_video_ready.txt。
用法：python scripts/probe_video_form_ready.py [--cdp-endpoint http://localhost:9222]
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

DEFAULT_ENDPOINT = "http://localhost:9222"
REPORT = Path(".scratch/selector-calibration/calibration_report_video_ready.txt")

CANDIDATES = {
    "title（标题框）": [
        "input[placeholder*='请输入']",
        "input[placeholder*='标题']",
        "[class*='xigua-input']",
    ],
    "desc（简介/描述/正文）": [
        "input[placeholder*='简介']",
        "input[placeholder*='描述']",
        "input[placeholder*='正文']",
        "input[placeholder*='补充']",
        "textarea",
        "div[contenteditable='true']",
        "[class*='intro']",
        "[class*='desc']",
        "[class*='summary']",
    ],
    "cover（封面/海报）": [
        "[class*='poster']",
        "[class*='xigua-poster']",
        "[class*='cover']",
        "input[type=file][accept*='image']",
    ],
    "video_input（视频上传 file）": [
        "input[type=file][accept*='video']",
        "input[type=file]",
    ],
    "tag（标签/话题）": [
        "input[placeholder*='标签']",
        "input[placeholder*='话题']",
        "[class*='tag'] input",
        "[class*='topic'] input",
    ],
    "save_draft（存草稿）": [
        "button:has-text('存草稿')",
        "button:has-text('草稿')",
        "button:has-text('保存')",
        "a:has-text('存草稿')",
        "a:has-text('草稿')",
        "text=存草稿",
        "[class*='draft']",
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
        "href": attrs(el, "href")[:80],
        "class": cls[:90],
        "text": text[:70],
    }


def body_text(page) -> str:
    try:
        return page.evaluate(
            "() => (document.body ? document.body.innerText : '').replace(/\\s+/g,' ').slice(0,160)"
        )
    except Exception:
        return "<n/a>"


def snapshot(page) -> None:
    groups = [
        ("input", "input"),
        ("textarea", "textarea"),
        ("contenteditable", '[contenteditable="true"]'),
        ("button", "button"),
        ("a[链接含草稿/保存/发布]", "a"),
    ]
    for label, sel in groups:
        nodes = page.query_selector_all(sel)
        shown = 0
        log(f"-- {label}（{len(nodes)} 处）--")
        for i, n in enumerate(nodes):
            info = _el_info(n)
            t = info["text"]
            href = info["href"]
            # a 链接只打印与草稿/保存/发布/设置相关的，避免刷屏
            if sel == "a" and not any(k in (t + href) for k in ("草稿", "保存", "发布", "设置", "视频", "退出")):
                continue
            shown += 1
            log(
                f"  [{i}] tag={info['tag']} type={info['type']!r} placeholder={info['placeholder']!r} "
                f"accept={info['accept']!r} href={info['href']!r} class={info['class']!r} text={info['text']!r}"
            )
        if sel == "a" and shown == 0:
            log("  （无可草稿/保存/发布相关链接）")


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
                    f"class={first['class']!r} text={first['text']!r}）"
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

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp_endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = next((p for p in ctx.pages if "mp.toutiao.com" in p.url), None) or ctx.new_page()
        created = "mp.toutiao.com" not in page.url
        try:
            log(f"== 当前标签页 URL: {page.url} ==")
            if "/auth/" in page.url:
                log("RESULT: NOT_LOGGED_IN（被重定向到登录页）")
                return

            # 等待上传完成：body 无「上传中」，或含上传完成/转码/处理中信号
            log("== 等待上传完成 ==")
            t = 0
            done = False
            while t < 120:
                page.wait_for_timeout(3_000)
                t += 3
                bt = body_text(page)
                log(f"  [t={t}s] {bt!r}")
                uploading = "上传中" in bt
                if not uploading and "已上传" in bt:
                    done = True
                    break
                if not uploading and ("转码" in bt or "处理" in bt or "审核" in bt):
                    done = True
                    break
                if uploading and "100%" in bt:
                    done = True
                    break
                if not uploading and "发布" in bt:
                    done = True
                    break
            log(f"== 上传完成判定: {done} ==")
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