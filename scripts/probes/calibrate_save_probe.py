"""诊断探针：真机填稿后监控草稿保存的完整生命周期。

收集证据：
1. 网络层：抓取含 draft/save 关键字的 API 响应（状态码 + URL）
2. 页面层：页脚保存指示文案变化（草稿保存中 / 草稿已保存 / 保存失败）
3. 编辑器层：标题/正文实际内容是否写入

用法：python scripts/calibrate_save_probe.py
"""

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.publish.toutiao_draft import SELECTORS

PROFILE = ".profiles/calibrate_probe"
TITLE = "诊断探针：草稿保存观测（可删除）"
BODY = "这是一条用于诊断草稿自动保存链路的探测正文，仅用于真机校准观测，请忽略。"


def main() -> None:
    api_responses: list[tuple[str, int]] = []

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(PROFILE, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_response(resp):
            url = resp.url
            if any(k in url.lower() for k in ("draft", "save")) and "mp.toutiao.com" in url:
                api_responses.append((url, resp.status))

        page.on("response", on_response)
        page.goto(SELECTORS["article_publish_url"])
        page.fill(SELECTORS["title_input"], TITLE)
        page.fill(SELECTORS["body_editor"], BODY)
        # blur 正文编辑器触发保存路径；AI 助手抽屉遮罩会拦截指针事件，用 JS focus 绕过
        page.eval_on_selector(SELECTORS["title_input"], "el => el.focus()")

        # 编辑器实际内容
        title_len = page.eval_on_selector(
            SELECTORS["title_input"], "el => el.value ? el.value.length : 0"
        )
        body_len = page.eval_on_selector(
            SELECTORS["body_editor"], "el => (el.textContent || '').trim().length"
        )
        print(f"[editor] title_len={title_len} body_len={body_len}")

        # 监控页脚指示 90 秒
        seen: set[str] = set()
        start = time.time()
        while time.time() - start < 90:
            texts = page.eval_on_selector_all(
                "[class*='draft'], [class*='save']", "els => els.map(e => e.textContent.trim())"
            )
            drawer = page.eval_on_selector_all(
                ".ai-assistant-drawer", "els => els.map(e => getComputedStyle(e).display)"
            )
            key = (tuple(texts), tuple(drawer))
            if key not in seen:
                seen.add(key)
                print(f"[t={int(time.time()-start)}s] footer={texts} drawer={drawer}")
            if any("已保存" in t or "保存成功" in t for t in texts):
                print(f"[t={int(time.time()-start)}s] 检测到保存完成信号")
                break
            page.wait_for_timeout(2000)

        print("== API 响应（draft/save 相关）==")
        for url, status in api_responses[-10:]:
            print(f"  [{status}] {url[:120]}")
        if not api_responses:
            print("  （无任何 draft/save 相关请求被触发）")

        ctx.close()
    Path(".scratch/selector-calibration/save_probe_done.txt").write_text("done", encoding="utf-8")


if __name__ == "__main__":
    main()
