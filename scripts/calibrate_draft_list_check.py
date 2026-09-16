"""一次性工具 v4b：草稿箱 API 直查（D14 续，用后可删）。

背景：v4 已确认两个关键 API——
  保存：POST mp/agw/article/publish?source=mp&type=article（填稿后 ~4s 触发，[200]）
  列表：GET  mp/agw/creator_center/draft_list?type=2&count=20&app_id=1231
但 v4 的响应体过滤条件漏掉了这两个 URL，且 ctx.close() 写 HAR 挂死。
本工具在页面上下文里直接 fetch 草稿列表 API，拿地面真相：探测草稿在不在列表里。
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE = ".profiles/calibrate_probe"
ROOT_URL = "https://mp.toutiao.com/"
DRAFT_LIST_URL = "https://mp.toutiao.com/mp/agw/creator_center/draft_list?type=2&count=50&app_id=1231"
NEEDLES = ["校准探测v4", "校准探测", "诊断探针"]
REPORT_PATH = Path(".scratch/selector-calibration/draft_list_check.txt")

lines: list[str] = []


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
            log("== 页面上下文 fetch 草稿列表 API ==")
            raw = page.evaluate(
                "url => fetch(url, {credentials: 'include'}).then(r => r.text())",
                DRAFT_LIST_URL,
            )
        finally:
            ctx.close()

    head = raw[:500]
    log(f"响应前 500 字符: {head}")
    if not head.lstrip().startswith("{"):
        log("!! 响应不是 JSON（可能被重定向/鉴权拦截），原始响应前 2000 字符：")
        log(raw[:2000])
        REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
        return

    try:
        data = json.loads(raw)
        err_no = data.get("err_no")
        err_tips = data.get("err_tips")
        log(f"err_no={err_no} err_tips={err_tips}")
    except Exception as e:
        log(f"JSON 解析失败: {e}")

    log(f"== 子串检索（{NEEDLES}）==")
    total = 0
    for needle in NEEDLES:
        n = raw.count(needle)
        total += n
        log(f"  '{needle}' 出现 {n} 次")
    if total:
        log(">>> 草稿已入库：列表 API 响应中包含探测标题（地面真相）")
        for needle in NEEDLES:
            i = raw.find(needle)
            if i >= 0:
                log(f"  片段: ...{raw[max(0, i - 200):i + 300]}...")
                break
    else:
        log("<<< 草稿列表 API 响应中未发现任何探测标题")

    log("== 列表全文（前 6000 字符）==")
    log(raw[:6000])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    log(f"报告已写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
