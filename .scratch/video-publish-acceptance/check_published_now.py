"""核验 D19 验收视频是否真实发布（list/v2 已发布列表直查，只读）。"""
import sys

sys.path.insert(0, ".")

from app.publish.toutiao_draft import ToutiaoDraftAdapter  # noqa: E402

adapter = ToutiaoDraftAdapter(cdp_endpoint="http://localhost:9222")
browser, stop = adapter._connect_cdp()
try:
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = next((p for p in ctx.pages if "mp.toutiao.com" in p.url), None)
    created = page is None
    if created:
        page = ctx.new_page()
    page.goto("https://mp.toutiao.com/")
    if not adapter._is_logged_in(page):
        print("NOT_LOGGED_IN")
    else:
        raw = page.evaluate(
            "u => fetch(u, {credentials: 'include'}).then(r => r.text())",
            adapter.SELECTORS["published_list_url"] if hasattr(adapter, "SELECTORS") else __import__(
                "app.publish.toutiao_draft", fromlist=["SELECTORS"]
            ).SELECTORS["published_list_url"],
        )
        titles = adapter._parse_published_titles(raw)
        print(f"published count: {len(titles)}")
        for t in titles:
            print(" -", t)
    if created:
        page.close()
finally:
    browser.close()
