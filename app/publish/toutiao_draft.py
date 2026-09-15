"""头条号草稿箱适配器：Playwright 驱动真实浏览器，把内容包填进投稿草稿箱。

设计要点：
- 每个账号一个独立的浏览器持久化目录（profile_dir），首次扫码登录后复用登录态；
- 默认只填草稿（auto_publish=False），人工在后台确认后点发布；
- auto_publish=True 时填完直接点发布。

注意：页面选择器（SELECTORS）依赖头条号后台 DOM，平台改版后需实测校准。
"""

from pathlib import Path
from typing import Any, Callable

from app.models.account import Account
from app.publish.adapter import ContentFormat, ContentPackage, PublishResult, PublishStatus

# ---- 页面锚点：头条号后台改版时只需改这里（以下为占位，需实测校准） ----
SELECTORS = {
    "login_entry": "text=登录/注册",  # 出现该元素说明未登录
    "video_publish_url": "https://mp.toutiao.com/profile_v4/xigua/upload-video",
    "article_publish_url": "https://mp.toutiao.com/profile_v4/graphic/publish",
    "video_upload": "input[type=file]",
    "title_input": "textarea[placeholder*='标题']",
    "body_editor": "div[contenteditable='true']",
    "tag_input": "input[placeholder*='标签']",
    "save_draft_btn": "button:has-text('存草稿')",
    "publish_btn": "button:has-text('发布')",
}

DEFAULT_TIMEOUT_MS = 30_000


class ToutiaoDraftAdapter:
    """头条号「草稿箱」发布适配器。"""

    name = "toutiao_draft"

    def __init__(
        self,
        browser_factory: Callable[[str], Any] | None = None,
        profiles_root: str = ".profiles",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ):
        """browser_factory: 注入浏览器上下文工厂（profile_dir -> page），便于测试替换；
        为空时使用真实 Playwright 持久化上下文。"""
        self._browser_factory = browser_factory
        self.profiles_root = Path(profiles_root)
        self.timeout_ms = timeout_ms

    # ---- 对外主入口 ----
    def publish(self, package: ContentPackage, account: Account) -> PublishResult:
        profile_dir = account.profile_dir or str(self.profiles_root / account.id)
        with self._open_page(profile_dir) as page:
            if not self._is_logged_in(page):
                return PublishResult(
                    status=PublishStatus.NEEDS_LOGIN,
                    message=f"账号「{account.name}」登录态失效，请运行登录命令扫码后重试",
                )
            self._fill_draft(page, package)
            if account.auto_publish:
                page.click(SELECTORS["publish_btn"], timeout=self.timeout_ms)
                return PublishResult(status=PublishStatus.PUBLISHED, message="已自动发布")
            page.click(SELECTORS["save_draft_btn"], timeout=self.timeout_ms)
            return PublishResult(
                status=PublishStatus.DRAFT_READY, message="草稿箱已填好，等待人工发布"
            )

    # ---- 登录态 ----
    def _is_logged_in(self, page: Any) -> bool:
        """首页能定位到「登录/注册」入口则说明未登录。"""
        return page.wait_for_selector(SELECTORS["login_entry"], timeout=3_000) is None

    # ---- 填草稿 ----
    def _fill_draft(self, page: Any, package: ContentPackage) -> None:
        if package.format in (ContentFormat.VIDEO, ContentFormat.SLIDESHOW):
            page.goto(SELECTORS["video_publish_url"])
            page.set_input_files(SELECTORS["video_upload"], str(package.video_path))
        else:
            page.goto(SELECTORS["article_publish_url"])

        page.fill(SELECTORS["title_input"], package.title, timeout=self.timeout_ms)

        if package.body:
            page.fill(SELECTORS["body_editor"], package.body, timeout=self.timeout_ms)

        for tag in package.tags:
            page.fill(SELECTORS["tag_input"], tag, timeout=self.timeout_ms)
            page.keyboard.press("Enter")

        if package.cover_path:
            page.set_input_files(SELECTORS["video_upload"], str(package.cover_path))

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
                page.goto("https://mp.toutiao.com/")
                return page

            def __exit__(self, *exc):
                self._browser.close()
                self._pw.stop()

        return _Ctx()