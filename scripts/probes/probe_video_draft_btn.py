"""D16 事实修正取证：视频发布页「存草稿」按钮选择器探测。

两段式表单：操作按钮仅在上传完成后渲染。本探针上传本地样例视频进入
编辑阶段后只读取证按钮结构，不点存草稿/发布，不留草稿。
"""
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.publish.toutiao_draft import SELECTORS, ToutiaoDraftAdapter  # noqa: E402

VIDEO = Path("data/media/d17c5f242c23449697d02bd344a840d8.mp4")
assert VIDEO.exists(), f"样例视频不存在: {VIDEO}"

adapter = ToutiaoDraftAdapter(cdp_endpoint="http://localhost:9222")
browser, stop = adapter._connect_cdp()
try:
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = next((p for p in ctx.pages if "mp.toutiao.com" in p.url), None)
    created = page is None
    if created:
        page = ctx.new_page()
    page.goto(SELECTORS["video_publish_url"])
    page.wait_for_selector("input[type=file]", timeout=15_000, state="attached")
    page.set_input_files("input[type=file][accept*='video']", str(VIDEO))
    page.wait_for_selector(SELECTORS["video_upload_done"], timeout=30_000)
    page.wait_for_timeout(2_000)
    buttons = page.evaluate(
        """() => {
            const out = [];
            for (const el of document.querySelectorAll('*')) {
                const own = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => (n.textContent || '').trim())
                    .join('');
                if (own.includes('草稿') || own.includes('发布') || own.includes('提交')) {
                    out.push({
                        tag: el.tagName,
                        text: own.slice(0, 20),
                        cls: String(el.className).slice(0, 90),
                        visible: !!(el.offsetWidth || el.offsetHeight),
                    });
                }
            }
            return out;
        }"""
    )
    print("=== editor-stage elements mentioning 草稿/发布/提交 (own text) ===")
    for b in buttons:
        print(f"  <{b['tag']}> [{b['text']}] visible={b['visible']} cls={b['cls']}")
    draft = [b for b in buttons if "草稿" in b["text"] and b["visible"]]
    print("=== draft-save candidates ===", "FOUND" if draft else "NONE")
    for b in draft:
        print(" ", b)
    if created:
        page.close()
finally:
    browser.close()
