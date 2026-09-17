"""头条号草稿箱适配器：Playwright 驱动真实浏览器，把内容包填进投稿草稿箱。

两种模式（D14 拍板走 CDP 路线 A）：
- CDP 模式（推荐）：cdp_endpoint 非空时 connect_over_cdp 连接用户真实 Chrome
  （如 http://localhost:9222）。根因：launch_persistent_context 的 Chromium 自动化
  指纹会触发头条风控，保存接口恒返回 err_no=7050 保存失败；CDP 连真实 Chrome
  实测 err_no=0（探针 v5，.scratch/selector-calibration/）。复用已打开的头条标签页，
  退出时仅关闭本进程新建的标签页并断开连接，不会杀用户浏览器。
- profile 模式（遗留）：每个账号独立浏览器持久化目录（profile_dir），首次扫码登录
  后复用登录态。仅用于无 CDP 环境的兜底。

其他要点：
- 默认只填草稿（auto_publish=False），人工在后台确认后点发布；
- auto_publish=True 时填完直接点发布；
- 页面选择器（SELECTORS）依赖头条号后台 DOM，平台改版后需实测校准。
"""

import json
from pathlib import Path
from typing import Any, Callable

from app.models.account import Account
from app.publish.adapter import ContentFormat, ContentPackage, PublishResult, PublishStatus

# ---- 页面锚点：头条号后台改版时只需改这里 ----
# 2026-09-16 真机校准（D14）：图文链路 5 键已实测；视频链路/tag 仍为占位（MVP 出界）。
# 探测证据存档：.scratch/selector-calibration/（calibration_report*.txt）。
SELECTORS = {
    # 未登录访问 mp.toutiao.com 会 302 到 /auth/page/login；该按钮仅登录页存在（探测命中 1 处）。
    "login_entry": "button:has-text('登录')",
    # D16 真机确认：视频发布页 URL 与占位一致。
    "video_publish_url": "https://mp.toutiao.com/profile_v4/xigua/upload-video",
    # 真机确认：图文发布页 URL 与原占位一致。
    "article_publish_url": "https://mp.toutiao.com/profile_v4/graphic/publish",
    # D16 实测：视频上传 file input（上传前 1 处、上传后 2 处）。
    "video_upload": "input[type=file][accept*='video']",
    # D16 实测：视频上传完成信号（正文出现「上传成功」）。
    "video_upload_done": "text=上传成功",
    # 真机命中：placeholder='请输入文章标题（2～30个字）'。
    "title_input": "textarea[placeholder*='标题']",
    # D16 实测：视频标题框（type 空，placeholder='请输入 0～30 个字符'）。
    "video_title_input": "input[placeholder*='请输入']",
    # 真机确认正文为 ProseMirror 编辑器；.ProseMirror 比 div[contenteditable='true'] 更精确。
    "body_editor": ".ProseMirror",
    # D16 实测：视频封面组件（无独立 file input，内部 file input 待 P1 校准）。
    "video_cover": ".xigua-poster-editor",
    "tag_input": "input[placeholder*='标签']",  # 候选全 MISS 未校准；MVP 无标签来源（tags=[]）
    # 真机消歧：图文页同时存在「定时发布」「预览并发布」，原 button:has-text('发布') 会命中两处。
    "publish_btn": "button:has-text('预览并发布')",  # 图文发布
    # D16 实测：视频页发布按钮（class 含 action-footer-btn subm）。
    "video_publish_btn": "button:has-text('发布')",
    # 已发布内容列表端点（2026-09-17 真机校准：作品管理页自身请求，status=2=已发布；
    # type=0 同时返回文章/微头条，标题字段 contents[].article_attr.title）。
    "published_list_url": (
        "https://mp.toutiao.com/mp/agw/creator_center/list/v2"
        "?status=2&type=0&page_size=20&need_stat=true&wenda_type=1&app_id=1231"
    ),
}

DEFAULT_TIMEOUT_MS = 30_000
# 图文页为自动存草稿：footer 指示「草稿保存中...」持续 30s+ 不翻转（实测），不是可靠的完成
# 信号，故填稿后固定等待给平台落盘时间，草稿是否入库由人工在草稿箱确认（D14 验收口径）。
DRAFT_SETTLE_MS = 5_000
# 头条号后台首页；CDP/profile 模式进入页面后的统一落点（未登录会被 302 到 /auth/**）。
MP_HOME = "https://mp.toutiao.com/"
# CDP 模式下按 URL 片段识别可复用的头条标签页。
_MP_TAB_MARK = "mp.toutiao.com"


class ToutiaoDraftAdapter:
    """头条号「草稿箱」发布适配器。"""

    name = "toutiao_draft"

    def __init__(
        self,
        browser_factory: Callable[[str], Any] | None = None,
        profiles_root: str = ".profiles",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        cdp_endpoint: str | None = None,
        cdp_browser_factory: Callable[[str], Any] | None = None,
    ):
        """browser_factory: 注入浏览器上下文工厂（profile_dir -> page），便于测试替换；
        为空时使用真实 Playwright 持久化上下文。
        cdp_endpoint: 非空时启用 CDP 模式，connect_over_cdp 连接用户真实 Chrome
        （profile 模式自动失效）；cdp_browser_factory: 注入 CDP 浏览器工厂
        （endpoint -> browser），便于测试替换。两种注入互不影响。"""
        self._browser_factory = browser_factory
        self.profiles_root = Path(profiles_root)
        self.timeout_ms = timeout_ms
        self.cdp_endpoint = cdp_endpoint
        self._cdp_browser_factory = cdp_browser_factory

    # ---- 对外主入口 ----
    def publish(self, package: ContentPackage, account: Account) -> PublishResult:
        if self.cdp_endpoint:
            with self._open_cdp_page() as page:
                return self._publish_with_page(page, package, account)
        profile_dir = account.profile_dir or str(self.profiles_root / account.id)
        with self._open_page(profile_dir) as page:
            return self._publish_with_page(page, package, account)

    def _publish_with_page(
        self, page: Any, package: ContentPackage, account: Account
    ) -> PublishResult:
        if not self._is_logged_in(page):
            hint = (
                "请先在调试浏览器窗口中登录头条号后重试"
                if self.cdp_endpoint
                else "请运行登录命令扫码后重试"
            )
            return PublishResult(
                status=PublishStatus.NEEDS_LOGIN,
                message=f"账号「{account.name}」登录态失效，{hint}",
            )
        self._fill_draft(page, package)
        is_video = package.format in (ContentFormat.VIDEO, ContentFormat.SLIDESHOW)
        if account.auto_publish:
            publish_sel = SELECTORS["video_publish_btn"] if is_video else SELECTORS["publish_btn"]
            page.click(publish_sel, timeout=self.timeout_ms)
            return PublishResult(status=PublishStatus.PUBLISHED, message="已自动发布")
        if is_video:
            # 视频无草稿：半自动应在 dispatch 层拦截走 /publish-now；此处防御返回 failed。
            return PublishResult(
                status=PublishStatus.FAILED,
                message="视频链路无草稿，半自动发布请走 /publish-now",
            )
        # 图文：平台自动存草稿，等待落盘后返回，人工在草稿箱确认。
        page.wait_for_timeout(DRAFT_SETTLE_MS)
        return PublishResult(
            status=PublishStatus.DRAFT_READY, message="草稿已自动保存，等待人工发布"
        )

    # ---- 登录态 ----
    def _is_logged_in(self, page: Any) -> bool:
        """登录态检测（D14 真机校准）：未登录访问 mp.toutiao.com 必被 302 到
        /auth/page/login，URL 是最硬信号；登录入口按钮仅作兜底。

        注意：真实 Playwright 等不到选择器时抛 TimeoutError 而非返回 None；
        登录页 JS 渲染较慢，按钮可能晚于短超时出现，故不能只依赖按钮。"""
        try:
            # 给 302 重定向留稳定窗口：等到 auth 登录页 = 未登录
            page.wait_for_url("**/auth/**", timeout=2_000)
            return False
        except Exception:
            pass
        if "auth" in page.url:  # URL 已是登录页（窗口期内完成跳转）
            return False
        try:
            found = page.wait_for_selector(SELECTORS["login_entry"], timeout=3_000)
        except Exception:  # 真实 Playwright 等不到元素会抛超时（替身则以 None 表示）→ 已登录
            return True
        return found is None  # 找到登录入口 = 未登录；None = 入口不存在 = 已登录

    # ---- 填草稿 ----
    def _fill_draft(self, page: Any, package: ContentPackage) -> None:
        is_video = package.format in (ContentFormat.VIDEO, ContentFormat.SLIDESHOW)
        if is_video:
            page.goto(SELECTORS["video_publish_url"])
            page.set_input_files(SELECTORS["video_upload"], str(package.video_path))
            # 等视频上传完成（D16：上传异步，标题框先渲染、完成后正文出现「上传成功」）。
            page.wait_for_selector(SELECTORS["video_upload_done"], timeout=self.timeout_ms)
            title_sel = SELECTORS["video_title_input"]
        else:
            page.goto(SELECTORS["article_publish_url"])
            title_sel = SELECTORS["title_input"]

        page.fill(title_sel, package.title, timeout=self.timeout_ms)

        if package.body and not is_video:  # 视频无正文框（D16 实测）
            page.fill(SELECTORS["body_editor"], package.body, timeout=self.timeout_ms)

        if package.tags and not is_video:  # 视频无标签框（D16 实测）
            for tag in package.tags:
                page.fill(SELECTORS["tag_input"], tag, timeout=self.timeout_ms)
                page.keyboard.press("Enter")

        if package.cover_path:
            if is_video:
                # 视频封面走 .xigua-poster-editor 组件（内部 file input 待 P1 校准）。
                page.click(SELECTORS["video_cover"], timeout=self.timeout_ms)
            else:
                page.set_input_files(SELECTORS["video_upload"], str(package.cover_path))

    # ---- 查询已发布列表 ----
    def list_published_titles(self, account: Account) -> list[str]:
        """查询头条已发布内容标题列表（2026-09-17 真机校准后生效）。

        仅 CDP 模式支持：fetch 同源接口需页面凭据（credentials include）。
        未配置 cdp_endpoint（profile 模式）、登录态失效或响应异常时返回空列表，
        轮询不误确认。
        """
        url = SELECTORS.get("published_list_url", "")
        if not url or not self.cdp_endpoint:
            return []
        with self._open_cdp_page() as page:
            if not self._is_logged_in(page):
                return []
            raw = page.evaluate(
                "u => fetch(u, {credentials: 'include'}).then(r => r.text())", url
            )
            return self._parse_published_titles(raw)

    def _parse_published_titles(self, raw: str) -> list[str]:
        """从已发布列表响应解析标题（2026-09-17 真机校准：article_attr.title）。

        响应结构：{code, message, contents: [{article_attr: {title, status, ...}}], ...}。
        解析失败 / code 非 0 / 结构异常一律返回空，绝不让轮询误确认。
        """
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(data, dict) or data.get("code") != 0:
            return []
        contents = data.get("contents")
        if not isinstance(contents, list):
            return []
        titles: list[str] = []
        for item in contents:
            attr = item.get("article_attr") if isinstance(item, dict) else None
            title = attr.get("title") if isinstance(attr, dict) else None
            if isinstance(title, str) and title.strip():
                titles.append(title.strip())
        return titles

    # ---- 浏览器上下文 ----
    def _open_page(self, profile_dir: str):
        if self._browser_factory is not None:
            return self._browser_factory(profile_dir)
        return self._playwright_page(profile_dir)

    def _playwright_page(self, profile_dir: str):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "未安装 playwright。请先执行：pip install playwright && playwright install chromium"
            ) from e

        class _Ctx:
            def __enter__(self):
                self._pw = sync_playwright().start()
                Path(profile_dir).mkdir(parents=True, exist_ok=True)
                self._browser = self._pw.chromium.launch_persistent_context(
                    profile_dir, headless=False
                )
                page = self._browser.pages[0] if self._browser.pages else self._browser.new_page()
                page.goto(MP_HOME)
                return page

            def __exit__(self, *exc):
                self._browser.close()
                self._pw.stop()

        return _Ctx()

    # ---- CDP 浏览器上下文（D14 路线 A）----
    def _open_cdp_page(self):
        """CDP 模式：连接用户真实 Chrome，返回页面上下文管理器。

        语义（对真实与替身注入一致）：
        - 优先复用已打开的头条标签页，否则新建一个；
        - 退出时只关闭本进程新建的标签页，复用的标签页保持原样；
        - browser.close() 仅断开 CDP 连接，绝不关闭用户浏览器进程。"""
        if self._cdp_browser_factory is not None:
            browser = self._cdp_browser_factory(self.cdp_endpoint)
            return self._cdp_ctx(browser)
        browser, stop = self._connect_cdp()
        return self._cdp_ctx(browser, stop)

    def _connect_cdp(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "未安装 playwright。请先执行：pip install playwright && playwright install chromium"
            ) from e
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.connect_over_cdp(self.cdp_endpoint)
        except Exception:
            pw.stop()
            raise
        return browser, pw.stop

    def _cdp_ctx(self, browser: Any, stop: Callable[[], None] | None = None):
        class _CdpCtx:
            def __init__(self):
                self._page = None
                self._created = False

            def __enter__(self):
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                page = next(
                    (p for p in ctx.pages if _MP_TAB_MARK in p.url), None
                )
                self._created = page is None
                if self._created:
                    page = ctx.new_page()
                self._page = page
                page.goto(MP_HOME)  # 统一落点：未登录将触发 302 到 /auth/**
                return page

            def __exit__(self, *exc):
                if self._created and self._page is not None:
                    try:
                        self._page.close()
                    except Exception:
                        pass  # 页面可能已被用户手动关闭
                browser.close()  # CDP 连接模式：只断连，不杀用户浏览器
                if stop is not None:
                    stop()

        return _CdpCtx()