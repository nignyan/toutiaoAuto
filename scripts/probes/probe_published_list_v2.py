"""一次性探针 v2：进「作品管理/已发布」页抓页面真实调用的列表 API + 标题字段。

v1 结论：/mp/agw/creator_center/list/v2?status=2&... 返回 contents 数组（首页组件调用）。
本脚本导航到 /profile_v4/manage/content/all，捕获页面自己发出的 list/v2 请求（拿到
运营页的真实参数），并对响应体提取每条 content 的标题候选字段。

用法：python scripts/probes/probe_published_list_v2.py [--cdp-endpoint http://localhost:9222]
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

DEFAULT_ENDPOINT = "http://localhost:9222"
MANAGE_ALL = "https://mp.toutiao.com/profile_v4/manage/content/all"
REPORT = Path(".scratch/selector-calibration/published_list_v2_check.txt")

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
                if "agw" in u and ("list" in u or "content" in u or "manage" in u):
                    try:
                        body = r.text()
                    except Exception:
                        body = "<unavailable>"
                    api_hits.append(f"{u}\n  {body}")

            page.on("response", on_response)
            page.goto(MANAGE_ALL, wait_until="domcontentloaded")
            page.wait_for_timeout(8_000)
            log(f"== 页面: {page.url} ==")
            if "/auth/" in page.url:
                log("RESULT: NOT_LOGGED_IN（被重定向到登录页）")
                return

            log("== agw 列表 API 响应 ==")
            for h in api_hits:
                # 只打印 body 前 2000 字符避免刷屏
                head, _, body = h.partition("\n  ")
                log(f"  {head}\n    {body[:2000]}")

            log("== 解析 list/v2 响应结构 ==")
            for h in api_hits:
                if "creator_center/list/v2" not in h:
                    continue
                body = h.partition("\n  ")[2]
                try:
                    data = json.loads(body)
                except Exception as e:
                    log(f"  非 JSON 响应: {e}")
                    continue
                log(f"  顶层键: {sorted(data.keys())}")
                contents = data.get("contents") or (data.get("data") or {}).get("contents") or []
                log(f"  contents 数量: {len(contents)}")
                for i, c in enumerate(contents[:5]):
                    log(f"  -- item[{i}] 键 --")
                    log(f"     {sorted(c.keys())}")
                    # 标题候选字段采样
                    for k in ("title", "display_title", "article_title", "name", "abstract"):
                        if k in c:
                            log(f"     {k} = {str(c[k])[:80]!r}")
                    # article_attr / media 子结构中的标题候选
                    for sub_key in ("article_attr", "media", "video", "cell_info"):
                        sub = c.get(sub_key)
                        if isinstance(sub, dict):
                            cand = {
                                k: str(v)[:60]
                                for k, v in sub.items()
                                if "title" in k.lower() or k in ("name",)
                            }
                            if cand:
                                log(f"     {sub_key}.title候选 = {cand}")
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
