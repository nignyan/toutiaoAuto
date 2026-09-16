"""一次性工具 v5：CDP 链路端到端验证（D14 续，用后可删）。

背景：自动化环境被风控（7050 保存失败）；修复路线 = CDP 接管用户真实 Chrome
（--remote-debugging-port=9222 + 专属 user-data-dir .profiles/cdp_chrome）。
本工具连接该实例，自动填稿并验证三关：
  1) article/publish 响应 err_no=0；
  2) draft_list API 出现探测标题；
  3) 全程不关闭用户浏览器（仅断开 CDP 连接）。
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.publish.toutiao_draft import SELECTORS

CDP_ENDPOINT = "http://localhost:9222"
PUBLISH_URL = SELECTORS["article_publish_url"]
DRAFT_LIST_URL = "https://mp.toutiao.com/mp/agw/creator_center/draft_list?type=2&count=20&app_id=1231"
TITLE = "校准探测v5 CDP链路验证"
BODY = (
    "这是 CDP 链路验证的探测正文。此前已确认：Playwright 自启动的自动化浏览器会被"
    "服务端以 7050 拒绝保存，而接管用户真实 Chrome 的 CDP 方式应能通过风控。"
    "本条内容仅用于验证草稿自动保存链路，验证完成后可从草稿箱删除。"
)
SAVE_MARK = "article/publish"
REPORT_PATH = Path(".scratch/selector-calibration/cdp_verify.txt")

lines: list[str] = []
save_hits: list[tuple[str, str]] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    lines.append(msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    created_page = False
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_ENDPOINT)
        ctx = browser.contexts[0]
        page = next(
            (p for p in ctx.pages if "mp.toutiao.com" in p.url), None
        ) or ctx.new_page()
        created_page = page not in ctx.pages or True  # new_page 恒为新建；existing 复用
        created_page = "mp.toutiao.com" not in page.url
        try:
            page.goto(PUBLISH_URL)
            page.wait_for_selector(SELECTORS["title_input"], timeout=30_000)
            log(f"== CDP 已接管发布页: {page.url} ==")

            def on_response(r):
                if SAVE_MARK not in r.url:
                    return
                try:
                    save_hits.append((r.url, r.text()[:2000]))
                except Exception as e:
                    save_hits.append((r.url, f"<body unavailable: {type(e).__name__}>"))

            page.on("response", on_response)
            page.fill(SELECTORS["title_input"], TITLE)
            page.fill(SELECTORS["body_editor"], BODY)
            page.eval_on_selector(SELECTORS["title_input"], "el => el.focus()")
            log("== 已填稿，等待自动保存 15s ==")
            page.wait_for_timeout(15_000)

            log("== 草稿列表直查 ==")
            raw = page.evaluate(
                "u => fetch(u, {credentials: 'include'}).then(r => r.text())", DRAFT_LIST_URL
            )
            log(f"  {raw[:1200]}")
            in_list = TITLE in raw
        finally:
            if created_page:
                page.close()  # 只关我们开的标签页
            browser.close()  # CDP 连接浏览器：close 仅断开连接，不关用户的 Chrome

    log("== 保存 API 响应 ==")
    err_no = None
    if save_hits:
        for url, body in save_hits:
            log(f"  {url[:140]}")
            log(f"  响应体: {body[:2000]}")
        try:
            err_no = json.loads(save_hits[-1][1]).get("err_no")
        except Exception:
            pass
    else:
        log("  （未捕获到 article/publish 响应）")

    log("== 结论 ==")
    if err_no == 0 and in_list:
        log("✔✔ CDP 链路验证通过：保存成功且草稿箱可见 → 可动手改造适配器")
    elif err_no == 0:
        log("△ 保存 API 成功但草稿箱未见标题（查列表口径/延迟）")
    else:
        log(f"✘ CDP 链路仍未通过（err_no={err_no}，in_list={in_list}）")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    log(f"报告已写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
