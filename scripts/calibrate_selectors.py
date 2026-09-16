"""一次性工具 v3：观察头条图文发布页「自动存草稿」生命周期（D14，用后可删）。

前置：v1 已完成登录（登录态在 .profiles/calibrate_probe）。
流程：进入发布页 → 填标题/正文 → 每 2 秒轮询草稿保存状态指示（共 30 秒）→
记录状态文本与元素 class 的时间线 → 报告写入 scripts/calibration_report_v3.txt。
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

PUBLISH_URL = "https://mp.toutiao.com/profile_v4/graphic/publish"
TITLE_SEL = "textarea[placeholder*='标题']"
BODY_SEL = ".ProseMirror"
REPORT_PATH = Path(".scratch/selector-calibration/calibration_report_v3.txt")
PROBE_PROFILE = ".profiles/calibrate_probe"
WATCH_SECONDS = 30

STATUS_SELECTORS = [
    "text=草稿保存中",
    "text=草稿已保存",
    "text=已保存",
    "[class*='draft']",
]

report_lines: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    report_lines.append(msg)


def snapshot(page, tag: str) -> None:
    """打印当前各状态指示元素的 (标签, 文本, class) 快照。"""
    found_any = False
    for sel in STATUS_SELECTORS:
        try:
            nodes = page.query_selector_all(sel)
        except Exception:
            continue
        for n in nodes:
            try:
                info = n.evaluate(
                    "e => [e.tagName, (e.innerText||'').slice(0, 24), e.className]"
                )
            except Exception:
                info = ("<n/a>", "", "")
            if info[1] or info[2]:
                found_any = True
                log(f"  [{tag}] {sel} -> {info}")
    if not found_any:
        log(f"  [{tag}] （无草稿状态元素可见）")


def main() -> None:
    with sync_playwright() as pw:
        Path(PROBE_PROFILE).mkdir(parents=True, exist_ok=True)
        ctx = pw.chromium.launch_persistent_context(PROBE_PROFILE, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(PUBLISH_URL)
        page.wait_for_selector(TITLE_SEL, timeout=30_000)
        log(f"== 已进入发布页: {page.url} ==")
        log("== 填稿前状态 ==")
        snapshot(page, "t=0s 填稿前")

        page.fill(TITLE_SEL, "校准探测：自动存草稿观察")
        page.fill(BODY_SEL, "探测正文：观察草稿自动保存的状态变化时间线。")

        t = 0
        while t < WATCH_SECONDS:
            page.wait_for_timeout(2_000)
            t += 2
            snapshot(page, f"t={t}s")

        log(f"\n== 观察结束（{WATCH_SECONDS}s，未点击任何按钮）==")
        ctx.close()

    REPORT_PATH.write_text("\n".join(report_lines), encoding="utf-8")
    log(f"报告已写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
