"""list/v2 交叉核验：确认测试视频已真实发布（一次性）。"""
import sys

sys.path.insert(0, ".")

from app.publish.toutiao_draft import SELECTORS, ToutiaoDraftAdapter  # noqa: E402

a = ToutiaoDraftAdapter(cdp_endpoint="http://localhost:9222")
browser, _ = a._connect_cdp()
try:
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = next((p for p in ctx.pages if "mp.toutiao.com" in p.url), None)
    created = page is None
    if created:
        page = ctx.new_page()
    page.goto("https://mp.toutiao.com/")
    if not a._is_logged_in(page):
        print("NOT_LOGGED_IN")
        raise SystemExit
    raw = page.evaluate(
        "u => fetch(u, {credentials: 'include'}).then(r => r.text())",
        SELECTORS["published_list_url"],
    )
    titles = a._parse_published_titles(raw)
    print(f"published count: {len(titles)}")
    hit = [t for t in titles if "系统联调测试" in t]
    print("match:", hit if hit else "NOT FOUND")
    for t in titles[:8]:
        print(" -", t)
    if created:
        page.close()
finally:
    browser.close()
