"""一次性探针：头条「已发布内容列表」端点与字段校准（P1，只读，不点击不发布）。

背景：图文半自动发布需定时轮询已发布列表自动确认（draft_poller）。此前只校准过
草稿列表 draft_list（D14），已发布列表端点/字段未知。本脚本连接 CDP，抓取头条号
「内容管理/已发布」页面的列表 API 与入口，辅助确定 SELECTORS["published_list_url"] 与标题字段。

用法：python scripts/probes/probe_published_list.py [--cdp-endpoint http://localhost:9222]
前置：CDP Chrome 已登录头条号，且账号有至少一条已发布内容。
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

DEFAULT_ENDPOINT = "http://localhost:9222"
HOME = "https://mp.toutiao.com/profile_v4/index"
REPORT = Path(".scratch/selector-calibration/published_list_check.txt")

# 列表 API 候选（草稿列表 D14 已校准 type=2；已发布列表猜测同族端点/type 变体）
LIST_API_GUESSES = [
    "https://mp.toutiao.com/mp/agw/creator_center/draft_list?type=1&count=20&app_id=1231",
    "https://mp.toutiao.com/mp/agw/creator_center/draft_list?type=0&count=20&app_id=1231",
    "https://mp.toutiao.com/mp/agw/creator_center/content_list?count=20&app_id=1231",
    "https://mp.toutiao.com/mp/agw/creator_center/article_list?count=20&app_id=1231",
]

lines: list[str] = []
api_hits: list[str] = []


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
            def on_response(r):
                if any(k in r.url for k in ("list", "content", "manage", "article")):
                    try:
                        body = r.text()[:1500]
                    except Exception:
                        body = "<unavailable>"
                    api_hits.append(f"{r.url}\n  {body}")

            page.on("response", on_response)
            page.goto(HOME, wait_until="domcontentloaded")
            page.wait_for_timeout(5_000)
            log(f"== 首页: {page.url} ==")
            if "/auth/" in page.url:
                log("RESULT: NOT_LOGGED_IN（被重定向到登录页）")
                return

            log("== 首页入口链接（内容/管理/发布/文章/视频/草稿）==")
            links = page.evaluate(
                """() => [...document.querySelectorAll('a')]
                .map(a => ({href: a.getAttribute('href') || '', text: (a.innerText||'').trim()}))
                .filter(x => /内容|管理|发布|文章|视频|草稿/.test(x.text + x.href))
                .slice(0, 40)"""
            )
            for l in links:
                log(f"  {l}")

            log("== 候选列表端点直查 ==")
            for url in LIST_API_GUESSES:
                try:
                    raw = page.evaluate(
                        "u => fetch(u, {credentials: 'include'}).then(r => r.text())", url
                    )
                    log(f"  URL: {url}\n    {raw[:800]}")
                except Exception as e:
                    log(f"  URL: {url} -> {type(e).__name__}")

            log("== 页面加载过程中捕获的列表 API 响应 ==")
            if api_hits:
                for h in api_hits:
                    log(f"  {h}")
            else:
                log("  （未捕获到 list/content/manage/article 相关响应）")
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