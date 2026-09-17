"""一次性探针 v3：直查 list/v2 完整结构 + 管理页长等待交叉验证。

用法：python scripts/probes/probe_published_list_v3.py [--cdp-endpoint http://localhost:9222]
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

DEFAULT_ENDPOINT = "http://localhost:9222"
MANAGE_ALL = "https://mp.toutiao.com/profile_v4/manage/content/all"
LIST_V2 = (
    "https://mp.toutiao.com/mp/agw/creator_center/list/v2"
    "?status=2&type=0&page_size=20&need_stat=true&wenda_type=1&app_id=1231"
)
REPORT = Path(".scratch/selector-calibration/published_list_v3_check.txt")

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
                u = r.url
                if "agw" in u and ("list" in u or "content" in u):
                    try:
                        body = r.text()
                    except Exception:
                        body = "<unavailable>"
                    api_hits.append(f"{u}\n  {body}")

            page.on("response", on_response)
            page.goto(MANAGE_ALL, wait_until="domcontentloaded")

            log("== 直查 list/v2（page_size=20）==")
            raw = page.evaluate(
                "u => fetch(u, {credentials: 'include'}).then(r => r.text())", LIST_V2
            )
            data = json.loads(raw)
            log(f"  顶层键: {sorted(data.keys())}")
            log(f"  message: {data.get('message')}")
            contents = data.get("contents") or []
            log(f"  contents 数量: {len(contents)}")
            log(f"  has_more 类字段: {[k for k in data if 'more' in k.lower()]} = "
                f"{ {k: data[k] for k in data if 'more' in k.lower()} }")
            if contents:
                first = contents[0]
                log(f"  item[0] 全部键: {sorted(first.keys())}")
                for k, v in first.items():
                    if isinstance(v, (str, int, float, bool)) or v is None:
                        log(f"    {k} = {str(v)[:100]!r}")
                for sub_key, sub in first.items():
                    if isinstance(sub, dict):
                        log(f"    {sub_key} 子键: {sorted(sub.keys())}")

            log("== 管理页自然加载捕获（等 25s）==")
            page.wait_for_timeout(25_000)
            seen = set()
            for h in api_hits:
                url = h.partition("\n  ")[0]
                if url in seen:
                    continue
                seen.add(url)
                log(f"  {url}\n    {h.partition(chr(10) + '  ')[2][:600]}")
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
