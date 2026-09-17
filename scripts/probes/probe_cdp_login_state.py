"""实机验收前置只读探针：检查 CDP Chrome 连通与头条登录态（不写任何状态）。"""
import sys

sys.path.insert(0, ".")

from app.publish.toutiao_draft import ToutiaoDraftAdapter  # noqa: E402

ENDPOINT = "http://localhost:9222"

adapter = ToutiaoDraftAdapter(cdp_endpoint=ENDPOINT)
browser, stop = adapter._connect_cdp()
try:
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = next((p for p in ctx.pages if "mp.toutiao.com" in p.url), None)
    created = page is None
    if created:
        page = ctx.new_page()
    page.goto("https://mp.toutiao.com/")
    logged_in = adapter._is_logged_in(page)
    print("mp tabs before:", len([p for p in ctx.pages if "mp.toutiao.com" in p.url]))
    print("logged_in:", logged_in)
    if created:
        page.close()
finally:
    browser.close()
    stop()
print("CDP probe done (connection closed, browser untouched)")
