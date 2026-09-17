"""一次性工具 v4：草稿保存全量网络取证 + 草稿箱直查（D14 续，用后可删）。

不靠 DOM 文案猜测，用两层硬证据回答「探测草稿到底存没存进去」：
  1. 网络层：录制发布页全部 JSON API 的请求/响应报文，找保存 API 与成功响应格式；
  2. 结果层：发现并访问草稿/内容管理入口，在列表 API 响应与页面文本中搜探测标题。

前置：优先复用 .profiles/calibrate_probe 登录态；过期时请在弹出的浏览器窗口扫码（等 120 秒）。
产物：
  - .scratch/selector-calibration/calibration_report_v4.txt（结论报告）
  - .scratch/selector-calibration/v4.har（全量网络归档，可用 DevTools 打开复盘）
"""

import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Response, sync_playwright

from app.publish.toutiao_draft import SELECTORS

PROFILE = ".profiles/calibrate_probe"
ROOT_URL = "https://mp.toutiao.com/"
PUBLISH_URL = SELECTORS["article_publish_url"]
TITLE = f"校准探测v4 {datetime.now():%H%M%S}"
BODY = "探测正文：全量网络取证校准，观察草稿自动保存的真实 API 行为，可删除。"
REPORT_PATH = Path(".scratch/selector-calibration/calibration_report_v4.txt")
HAR_PATH = ".scratch/selector-calibration/v4.har"

MONITOR_SECONDS = 60
LOGIN_WAIT_MS = 120_000

lines: list[str] = []
title_hits: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    lines.append(msg)


def write_report(har_note: str) -> None:
    log("== 结论 ==")
    if title_hits:
        log(f"✔ 草稿已入库：在 {len(title_hits)} 处证据中找到探测标题：")
        for h in title_hits[:8]:
            log(f"  {h[:180]}")
    else:
        log("✘ 本次抓到的 API 响应与页面文本中均未发现探测标题")
        log("  （不排除草稿更晚落库或列表接口未被访问到；请复盘 HAR）")
    log(f"HAR 归档：{har_note}")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    Path(".scratch/selector-calibration/v4_done.txt").write_text("done", encoding="utf-8")
    log(f"报告已写入 {REPORT_PATH}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    responses: list[Response] = []  # 事件回调只收集，主循环统一取 body（避免 sync 模式再入）
    req_posts: list[tuple[str, str | None]] = []

    def on_response(r: Response) -> None:
        responses.append(r)

    def on_request(r) -> None:
        u = r.url.lower()
        if "mp.toutiao.com" in u and ("draft" in u or "save" in u):
            req_posts.append((r.url, r.post_data))

    with sync_playwright() as pw:
        Path(PROFILE).mkdir(parents=True, exist_ok=True)
        Path(REPORT_PATH.parent).mkdir(parents=True, exist_ok=True)
        try:
            ctx = pw.chromium.launch_persistent_context(
                PROFILE, headless=False, record_har_path=HAR_PATH
            )
            har_note = HAR_PATH
        except TypeError:
            ctx = pw.chromium.launch_persistent_context(PROFILE, headless=False)
            har_note = "（本机 Playwright 版本不支持 persistent HAR，未归档）"

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_response)
        page.on("request", on_request)

        # ---- 登录态：URL 是最硬信号，过期则等用户扫码 ----
        log(f"== 探测标题：{TITLE} ==")
        page.goto(ROOT_URL)
        try:
            page.wait_for_url("**/auth/**", timeout=5_000)
            log(">> 登录态已过期，请在弹出的浏览器窗口扫码登录（等待 120 秒）...")
            page.wait_for_url(lambda u: "/auth/" not in u, timeout=LOGIN_WAIT_MS)
            log(">> 登录成功")
        except Exception:
            log(">> 登录态有效（未跳转登录页）")

        idx = 0

        def drain(tag: str) -> None:
            nonlocal idx
            for r in responses[idx:]:
                idx += 1
                url = r.url
                if "mp.toutiao.com" not in url:
                    continue
                try:
                    ct = r.headers.get("content-type", "")
                except Exception:
                    ct = ""
                if "json" not in ct and "/api/" not in url:
                    continue
                body = None
                if "json" in ct:
                    try:
                        body = r.text()[:4000]
                    except Exception as e:
                        body = f"<body unavailable: {type(e).__name__}>"
                log(f"  [api][{tag}] [{r.status}] {url[:140]}")
                if body and ("draft" in url.lower() or "save" in url.lower()):
                    log(f"    body: {body[:3000]}")
                if body and "校准探测v4" in body:
                    title_hits.append(f"{url} [{r.status}] {body[:600]}")

        # ---- 发布页填稿 + 60s 网络监听 ----
        page.goto(PUBLISH_URL)
        try:
            page.wait_for_selector(SELECTORS["title_input"], timeout=30_000)
            log(f"== 已进入发布页: {page.url} ==")
        except Exception:
            log(f"!! 未能进入发布页（当前 URL: {page.url}）")
            drain("enter-fail")
            ctx.close()
            write_report(har_note)
            return

        page.fill(SELECTORS["title_input"], TITLE)
        page.fill(SELECTORS["body_editor"], BODY)
        # blur 正文编辑器触发保存路径；AI 助手抽屉遮罩会拦指针，用 JS focus 绕过（v2 经验）
        page.eval_on_selector(SELECTORS["title_input"], "el => el.focus()")
        log(f"== 已填稿，监听网络 {MONITOR_SECONDS}s ==")

        last_footer = ""
        t0 = time.time()
        while time.time() - t0 < MONITOR_SECONDS:
            page.wait_for_timeout(4_000)
            drain("monitor")
            try:
                footer = page.eval_on_selector_all(
                    "[class*='draft'], [class*='save']",
                    "els => els.map(e => e.textContent.trim()).filter(t => t)",
                )
                key = " | ".join(dict.fromkeys(footer))[:200]
                if key and key != last_footer:
                    last_footer = key
                    log(f"  [footer t={int(time.time() - t0)}s] {key}")
            except Exception:
                pass

        # ---- 发现并访问草稿/内容管理入口（结构化发现，非猜测 URL）----
        try:
            links = page.eval_on_selector_all(
                "a[href]",
                """els => els
                    .map(e => [(e.getAttribute('href') || ''), (e.innerText || '').trim()])
                    .filter(([h, t]) =>
                        h.includes('manage') || h.includes('content') ||
                        t.includes('草稿') || t.includes('内容管理'))
                    .map(([h, t]) => h + ' | ' + t)
                    .filter((v, i, arr) => arr.indexOf(v) === i)""",
            )
        except Exception:
            links = []
        log("== 候选管理入口 ==")
        if links:
            for entry in links[:12]:
                log(f"  {entry[:160]}")
        else:
            log("  （导航中未发现 manage/content/草稿 链接）")

        visited = 0
        for entry in links:
            if visited >= 4:
                break
            href = entry.split(" | ")[0]
            if not (href.startswith("http") or href.startswith("/")):
                continue
            url = href if href.startswith("http") else ROOT_URL.rstrip("/") + href
            if "mp.toutiao.com" not in url:
                continue
            visited += 1
            log(f"== 访问管理页({visited}): {url[:140]} ==")
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(6_000)
                drain(f"manage-{visited}")
                if TITLE in page.content():
                    title_hits.append(f"页面文本命中: {page.url}")
                    log("  >>> 页面文本中出现探测标题")
            except Exception as e:
                log(f"  访问失败: {type(e).__name__}: {e}")

        # ---- draft/save 请求报文 ----
        drain("final")
        log("== URL 含 draft/save 的请求（含请求体）==")
        if req_posts:
            for u, pd in req_posts[:10]:
                log(f"  {u[:140]}")
                if pd:
                    log(f"    body: {str(pd)[:1500]}")
        else:
            log("  （未捕获到 URL 含 draft/save 的请求）")

        ctx.close()

    write_report(har_note)


if __name__ == "__main__":
    main()
