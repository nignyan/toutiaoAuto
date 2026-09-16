"""探测指定 profile 的头条登录态（只读检查，不填稿不点击）。

用法：python scripts/probe_login_state.py [--profile-dir .profiles/calibrate_probe]

判定口径与适配器一致：302 到 /auth/** = 未登录；否则兜底看登录入口按钮。
"""

import argparse

from playwright.sync_api import sync_playwright

BASE_URL = "https://mp.toutiao.com/"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-dir", default=".profiles/calibrate_probe")
    args = parser.parse_args()

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(args.profile_dir, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(BASE_URL)
        try:
            page.wait_for_url("**/auth/**", timeout=3_000)
            print(f"RESULT: NOT_LOGGED_IN (302 -> {page.url})")
        except Exception:
            if "auth" in page.url:
                print(f"RESULT: NOT_LOGGED_IN (url={page.url})")
            else:
                print(f"RESULT: LOGGED_IN (url={page.url})")
        ctx.close()


if __name__ == "__main__":
    main()
