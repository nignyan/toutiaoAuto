"""一次性工具 v4c：抓保存 API 的请求体 + 响应体（D14 续，用后可删）。

背景：v4b 证实草稿箱为空（draft_list=[]），自动存草稿从未真正落库；
v4 已定位保存 API 为 POST mp/agw/article/publish（填稿后 ~4s 触发）。
本工具专门抓该请求的 POST body 与响应 JSON，定位保存失败原因；
并补查 draft_list 的 type 参数变体，排除「存进去了但列表过滤条件不对」。
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.publish.toutiao_draft import SELECTORS

PROFILE = ".profiles/calibrate_probe"
ROOT_URL = "https://mp.toutiao.com/"
PUBLISH_URL = SELECTORS["article_publish_url"]
TITLE = "校准探测v4c 保存报文抓取"
BODY = "探测正文：抓取草稿自动保存的请求与响应报文，可删除。"
SAVE_MARK = "article/publish"
REPORT_PATH = Path(".scratch/selector-calibration/save_api_capture.txt")
DRAFT_LIST_VARIANTS = [
    "https://mp.toutiao.com/mp/agw/creator_center/draft_list?type=2&count=20&app_id=1231",
    "https://mp.toutiao.com/mp/agw/creator_center/draft_list?type=1&count=20&app_id=1231",
    "https://mp.toutiao.com/mp/agw/creator_center/draft_list?type=0&count=20&app_id=1231",
    "https://mp.toutiao.com/mp/agw/creator_center/draft_list?count=20&app_id=1231",
]

lines: list[str] = []
save_hits: list[tuple[str, str | None, str]] = []  # (url, post_data, resp_body)
post_bodies: list[tuple[str, str | None]] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    lines.append(msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with sync_playwright() as pw:
        Path(PROFILE).mkdir(parents=True, exist_ok=True)
        ctx = pw.chromium.launch_persistent_context(PROFILE, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(ROOT_URL)
            try:
                page.wait_for_url("**/auth/**", timeout=5_000)
                log(">> 登录态已过期，请扫码（60 秒）...")
                page.wait_for_url(lambda u: "/auth/" not in u, timeout=60_000)
            except Exception:
                pass

            def on_response(r):
                if SAVE_MARK not in r.url:
                    return
                try:
                    body = r.text()[:4000]
                except Exception as e:
                    body = f"<body unavailable: {type(e).__name__}>"
                save_hits.append((r.url, r.request.post_data, body))

            def on_request(r):
                if "mp.toutiao.com" not in r.url or r.method != "POST":
                    return
                pd = r.post_data
                if pd:
                    post_bodies.append((r.url, pd))

            page.on("response", on_response)
            page.on("request", on_request)

            page.goto(PUBLISH_URL)
            page.wait_for_selector(SELECTORS["title_input"], timeout=30_000)
            log(f"== 已进入发布页: {page.url} ==")
            page.fill(SELECTORS["title_input"], TITLE)
            page.fill(SELECTORS["body_editor"], BODY)
            page.eval_on_selector(SELECTORS["title_input"], "el => el.focus()")
            log("== 已填稿，等待保存触发 15s ==")
            page.wait_for_timeout(15_000)

            log("== POST 请求清单（本轮，含请求体前 1200 字符）==")
            for u, pd in post_bodies[:20]:
                log(f"  POST {u[:140]}")
                log(f"    body: {str(pd)[:1200]}")

            log("== 草稿列表 API 变体直查 ==")
            for url in DRAFT_LIST_VARIANTS:
                try:
                    raw = page.evaluate(
                        "u => fetch(u, {credentials: 'include'}).then(r => r.text())", url
                    )
                    mark = "<<< 命中探测标题" if TITLE in raw else ""
                    log(f"  {url}")
                    log(f"    {raw[:600]} {mark}")
                except Exception as e:
                    log(f"  {url}")
                    log(f"    fetch 失败: {type(e).__name__}: {e}")
        finally:
            ctx.close()

    log("== 保存 API 报文 ==")
    if save_hits:
        for url, pd, body in save_hits:
            log(f"  {url[:140]}")
            log(f"  请求体: {str(pd)[:3000]}")
            log(f"  响应体: {body[:3000]}")
    else:
        log("  （15s 内未捕获到 article/publish 请求）")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    log(f"报告已写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
