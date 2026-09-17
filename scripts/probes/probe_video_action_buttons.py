"""取证「存草稿/定时发布/发布」三个动作按钮的祖先链（可点击容器）与精确选择器。

若复用的 mp 标签页仍在编辑阶段直接读取；否则重新上传样例视频进入编辑阶段。
只读，不点击任何动作按钮。
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
    report = page.evaluate(
        """() => {
            const out = [];
            for (const el of document.querySelectorAll('span,div,a')) {
                const own = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => (n.textContent || '').trim())
                    .join('');
                if (!['存草稿', '定时发布', '发布'].includes(own)) continue;
                if (!(el.offsetWidth || el.offsetHeight)) continue;
                const chain = [];
                let cur = el;
                for (let i = 0; i < 4 && cur && cur.tagName !== 'BODY'; i++) {
                    chain.push(`${cur.tagName}.${String(cur.className).slice(0, 70)}`);
                    cur = cur.parentElement;
                }
                out.push({ text: own, chain });
            }
            return out;
        }"""
    )
    for r in report:
        print(f"[{r['text']}]")
        for lvl, c in enumerate(r["chain"]):
            print(f"   {'  ' * lvl}^ {c}")
    if created:
        page.close()
finally:
    browser.close()
