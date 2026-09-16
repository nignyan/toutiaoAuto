"""一次性工具 v4e：人工对照实验（D14 续，用后可删）。

背景：自动填稿（短/长正文）保存均被服务端 7050 拒绝。本工具请用户在同一
Playwright 浏览器里【手动】输入标题与正文，继续抓 article/publish 报文：
  - 手动也 7050 → 环境/账号被风控，需换真实日常浏览器再对照；
  - 手动成功（code=0，草稿箱可见）→ 问题出在 fill() 输入方式，改模拟逐字输入。
脚本自动等待：捕获到保存响应且静默 20s 后收尾，最长等 8 分钟。
"""

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.publish.toutiao_draft import SELECTORS

PROFILE = ".profiles/calibrate_probe"
ROOT_URL = "https://mp.toutiao.com/"
PUBLISH_URL = SELECTORS["article_publish_url"]
SAVE_MARK = "article/publish"
DRAFT_LIST_URL = "https://mp.toutiao.com/mp/agw/creator_center/draft_list?type=2&count=20&app_id=1231"
REPORT_PATH = Path(".scratch/selector-calibration/save_manual_test.txt")
MAX_WAIT_S = 480
QUIET_S = 20

lines: list[str] = []
save_hits: list[tuple[float, str, str]] = []  # (t, url, resp_body)


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
                log(">> 登录态已过期，请先扫码登录（最多等 3 分钟）...")
                page.wait_for_url(lambda u: "/auth/" not in u, timeout=180_000)
            except Exception:
                pass

            def on_response(r):
                if SAVE_MARK not in r.url:
                    return
                try:
                    body = r.text()[:2000]
                except Exception as e:
                    body = f"<body unavailable: {type(e).__name__}>"
                save_hits.append((time.time(), r.url, body))
                log(f"  [捕获保存响应 t={time.strftime('%H:%M:%S')}] {body[:200]}")

            page.on("response", on_response)

            page.goto(PUBLISH_URL)
            page.wait_for_selector(SELECTORS["title_input"], timeout=30_000)
            log("== 请在弹出的浏览器窗口中手动操作 ==")
            log("   1) 手动输入标题 + 100 字以上正文（打字或粘贴均可）")
            log("   2) 观察页脚「草稿保存中...」是否变成「草稿已保存」")
            log("   3) 不要点发布；脚本捕获到保存响应并静默 20s 后自动收尾")
            log(f"== 人工操作窗口：最长 {MAX_WAIT_S}s ==")

            t0 = time.time()
            last_count = 0
            while time.time() - t0 < MAX_WAIT_S:
                page.wait_for_timeout(3_000)
                if len(save_hits) > last_count:
                    last_count = len(save_hits)
                    last_t = save_hits[-1][0]
                if save_hits and time.time() - save_hits[-1][0] > QUIET_S:
                    log(">> 保存响应已静默 20s，收尾")
                    break

            log("== 草稿列表直查 ==")
            raw = page.evaluate(
                "u => fetch(u, {credentials: 'include'}).then(r => r.text())", DRAFT_LIST_URL
            )
            log(f"  {raw[:1500]}")
        finally:
            ctx.close()

    log("== 全部保存响应报文 ==")
    if save_hits:
        ok = 0
        for t, url, body in save_hits:
            log(f"  [t={time.strftime('%H:%M:%S', time.localtime(t))}] {url[:140]}")
            log(f"    {body[:1500]}")
            try:
                if json.loads(body).get("err_no") == 0:
                    ok += 1
            except Exception:
                pass
        log(f"== 小结：{len(save_hits)} 次保存请求，其中 err_no=0 成功 {ok} 次 ==")
    else:
        log("  （人工操作期间未捕获到任何保存请求）")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    log(f"报告已写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
