"""只读探针：检测头条号账号是否有视频发布权限（不点击、不上传、不提交）。

前置：已用 CDP 调试端口启动 Chrome 并登录（.profiles/cdp_chrome，port 9222）。
判定口径：
  - 302 到 /auth/**            -> NOT_LOGGED_IN（登录态失效）
  - 出现 input[type=file]      -> HAS_VIDEO_PERMISSION（有上传组件）
  - 被弹回首页 / 无上传组件    -> NO_VIDEO_PERMISSION
  - 其余无法确定              -> UNKNOWN
用法：python scripts/probe_video_permission.py [--cdp-endpoint http://localhost:9222]
"""

import argparse
import json
import sys
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

from app.publish.toutiao_draft import SELECTORS

DEFAULT_ENDPOINT = "http://localhost:9222"


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
        print(f"RESULT: CDP_NOT_RUNNING（{args.cdp_endpoint} 未监听，请先启动调试 Chrome）")
        raise SystemExit(2)

    video_url = SELECTORS["video_publish_url"]
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp_endpoint)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = next((p for p in ctx.pages if "mp.toutiao.com" in p.url), None) or ctx.new_page()
        created = "mp.toutiao.com" not in page.url
        try:
            page.goto(video_url, wait_until="domcontentloaded")
            page.wait_for_timeout(4_000)
            final = page.url
            print(f"FINAL_URL: {final}")

            if "/auth/" in final:
                print("RESULT: NOT_LOGGED_IN（被重定向到登录页）")
                return

            file_inputs = page.query_selector_all("input[type=file]")
            print(f"FILE_INPUT_COUNT: {len(file_inputs)}")
            print(f"TITLE_PRESENT: {page.query_selector(SELECTORS['title_input']) is not None}")

            body_hint = ""
            try:
                body_hint = page.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 200)")
            except Exception:
                body_hint = "<body unavailable>"
            print(f"BODY_HINT: {body_hint!r}")

            if len(file_inputs) >= 1:
                print("RESULT: HAS_VIDEO_PERMISSION（发现视频上传组件）")
            elif "profile_v4/index" in final or "权限" in body_hint or "开通" in body_hint:
                print("RESULT: NO_VIDEO_PERMISSION（未见上传入口）")
            else:
                print("RESULT: UNKNOWN（需人工查看页面）")
        finally:
            if created:
                try:
                    page.close()
                except Exception:
                    pass
            browser.close()  # CDP 连接：仅断连，不关用户浏览器


if __name__ == "__main__":
    main()