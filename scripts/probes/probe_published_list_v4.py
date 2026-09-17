"""一次性探针 v4：list/v2 标题字段终验（打印已发布内容的实际标题值）。

用法：python scripts/probes/probe_published_list_v4.py [--cdp-endpoint http://localhost:9222]
"""

import argparse
import io
import json
import sys
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

DEFAULT_ENDPOINT = "http://localhost:9222"
LIST_V2 = (
    "https://mp.toutiao.com/mp/agw/creator_center/list/v2"
    "?status=2&type=0&page_size=20&need_stat=true&wenda_type=1&app_id=1231"
)


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp-endpoint", default=DEFAULT_ENDPOINT)
    args = parser.parse_args()
    with urlopen(args.cdp_endpoint + "/json/version", timeout=2) as r:
        json.loads(r.read())

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp_endpoint)
        ctx = browser.contexts[0]
        page = next((p for p in ctx.pages if "mp.toutiao.com" in p.url), None) or ctx.new_page()
        created = "mp.toutiao.com" not in page.url
        try:
            raw = page.evaluate(
                'u => fetch(u, {credentials: "include"}).then(r => r.text())', LIST_V2
            )
        finally:
            if created:
                page.close()
            browser.close()

    data = json.loads(raw)
    print("code:", data.get("code"), "| total_count:", data.get("total_count"),
          "| has_more:", data.get("has_more"))
    for c in data["contents"]:
        a = c["article_attr"]
        print(repr(a.get("title")), "| status:", a.get("status"),
              repr(a.get("status_desc")), "| type:", a.get("type"), repr(a.get("type_desc")))


if __name__ == "__main__":
    main()
