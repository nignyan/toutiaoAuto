"""一次性工具 v4d：长正文对照实验（D14 续，用后可删）。

背景：v4c 抓到保存响应 {"err_no":7050,"message":"保存失败"}——自动保存每次都被
服务端拒绝；此前所有探测正文均 ≤30 字，怀疑「内容过短」触发保存校验。
本工具用 300+ 字正常长度的正文重跑保存链路作对照：
  - 若保存成功（code=0 且 draft_list 出现探测标题）→ 根因是内容过短；
  - 若仍 7050 → 转向风控/账号维度排查（需人工对照真实浏览器手动保存）。
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
TITLE = "城市早晨的噪声地图：通勤高峰如何影响街道生活节奏"
LONG_BODY = (
    "清晨六点半，城市的主干道开始苏醒。第一班公交车碾过路口的减速带，沿街的早餐铺"
    "陆续拉开卷帘门，蒸汽混着油烟在天色微亮时升起。对住在主干道两侧的居民来说，"
    "噪声的起伏几乎是一张可以读出时间的地图：七点前是零星的引擎声，七点到九点之间"
    "汇成持续的轰鸣，九点后迅速退潮，只留下环卫车与配送三轮车的零碎节拍。"
    "我们连续两周在三个典型街区做了定点观察，记录每小时的声压变化，并同步记录人流、"
    "车流与沿街商铺的开门时间。数据显示，通勤高峰对街道生活节奏的影响远不止音量本身："
    "临街店铺会把进货安排在九点半之后，中小学门口的托管班则把最热闹的时段提前到六点五十。"
    "噪声在这里不只是扰民问题，它更像城市运行的一份底稿，标注着不同人群如何共享同一条街道。"
    "理解这份节奏，或许能让城市更新在隔音改造之外，多考虑一分对生活时序的安排。"
)
SAVE_MARK = "article/publish"
DRAFT_LIST_URL = "https://mp.toutiao.com/mp/agw/creator_center/draft_list?type=2&count=20&app_id=1231"
REPORT_PATH = Path(".scratch/selector-calibration/save_long_body_test.txt")

lines: list[str] = []
save_hits: list[tuple[str, str]] = []  # (url, resp_body)


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

            def on_response(r):
                if SAVE_MARK not in r.url:
                    return
                try:
                    save_hits.append((r.url, r.text()[:2000]))
                except Exception as e:
                    save_hits.append((r.url, f"<body unavailable: {type(e).__name__}>"))

            page.on("response", on_response)

            page.goto(PUBLISH_URL)
            page.wait_for_selector(SELECTORS["title_input"], timeout=30_000)
            log(f"== 已进入发布页（正文 {len(LONG_BODY)} 字）==")
            page.fill(SELECTORS["title_input"], TITLE)
            page.fill(SELECTORS["body_editor"], LONG_BODY)
            page.eval_on_selector(SELECTORS["title_input"], "el => el.focus()")

            last_footer = ""
            t0 = time.time()
            while time.time() - t0 < 25:
                page.wait_for_timeout(3_000)
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

            log("== 草稿列表直查 ==")
            raw = page.evaluate(
                "u => fetch(u, {credentials: 'include'}).then(r => r.text())", DRAFT_LIST_URL
            )
            log(f"  {raw[:800]}")
            found = TITLE in raw
        finally:
            ctx.close()

    log("== 保存 API 响应 ==")
    if save_hits:
        for url, body in save_hits:
            log(f"  {url[:140]}")
            log(f"  响应体: {body[:2000]}")
        try:
            err_no = json.loads(save_hits[-1][1]).get("err_no")
        except Exception:
            err_no = "?"
    else:
        err_no = "none"
        log("  （未捕获到 article/publish 响应）")

    log("== 结论 ==")
    if found and err_no == 0:
        log("✔ 长正文保存成功且草稿箱可见 → 此前失败根因为内容过短")
    elif err_no == 0:
        log("△ 保存 API 返回成功，但草稿箱未见探测标题（需查列表口径/落库延迟）")
    elif err_no == 7050:
        log("✘ 长正文仍 7050 保存失败 → 排除内容过短，转向风控/环境/账号维度")
    else:
        log(f"? err_no={err_no}，请人工核对报告")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    log(f"报告已写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
