"""头条草稿箱适配器单测：用 FakePage 验证流程顺序与 auto_publish 开关语义。"""

import json
from pathlib import Path

import pytest

from app.models.account import Account, PublishAdapterKind, PublishChannel
from app.publish.adapter import (
    ContentFormat,
    ContentPackage,
    PublishAdapter,
    PublishStatus,
)
from app.publish.toutiao_draft import DRAFT_SETTLE_MS, SELECTORS, ToutiaoDraftAdapter


class FakeKeyboard:
    def __init__(self, calls: list):
        self.calls = calls

    def press(self, key: str) -> None:
        self.calls.append(("press", key))


class FakePage:
    """记录所有交互调用的页面替身。"""

    def __init__(self, logged_in: bool = True):
        self.calls: list = []
        self.logged_in = logged_in
        self.keyboard = FakeKeyboard(self.calls)
        # 未登录时真实后台会 302 到独立登录页（D14 校准）
        self.url = "" if logged_in else "https://mp.toutiao.com/auth/page/login"

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

    def wait_for_url(self, url_pattern: str, timeout: int = 0):
        self.calls.append(("wait_for_url", url_pattern))
        if "auth" in self.url:
            return
        raise TimeoutError(f"wait_for_url timeout {timeout}ms")

    def wait_for_selector(self, selector: str, timeout: int = 0):
        self.calls.append(("wait_for_selector", selector))
        if selector == SELECTORS["login_entry"]:
            return None if self.logged_in else object()
        return object()

    def set_input_files(self, selector: str, path: str) -> None:
        self.calls.append(("set_input_files", selector, path))

    def fill(self, selector: str, text: str, timeout: int = 0) -> None:
        self.calls.append(("fill", selector, text))

    def click(self, selector: str, timeout: int = 0) -> None:
        self.calls.append(("click", selector))

    def wait_for_timeout(self, timeout: int) -> None:
        self.calls.append(("wait_for_timeout", timeout))


class RealTimeoutPage(FakePage):
    """模拟真实 Playwright 行为：等不到选择器时抛 TimeoutError，而非返回 None。"""

    def wait_for_selector(self, selector: str, timeout: int = 0):
        self.calls.append(("wait_for_selector", selector))
        if selector == SELECTORS["login_entry"] and self.logged_in:
            raise TimeoutError(f"Timeout {timeout}ms exceeded")
        return object()


class FakeCtx:
    def __init__(self, page: FakePage):
        self.page = page

    def __enter__(self):
        return self.page

    def __exit__(self, *exc):
        return False


def make_adapter(page: FakePage) -> ToutiaoDraftAdapter:
    return ToutiaoDraftAdapter(browser_factory=lambda profile_dir: FakeCtx(page))


def make_account(**kw) -> Account:
    kw.setdefault("id", "acc_test")
    kw.setdefault("name", "测试号")
    return Account(**kw)


def video_package() -> ContentPackage:
    return ContentPackage(
        title="突发山火：救援连夜扑救",
        body="正文内容",
        format=ContentFormat.VIDEO,
        video_path="pkg/video.mp4",
        cover_path="pkg/cover.jpg",
        tags=["突发", "现场"],
    )


# ---- ContentPackage 校验 ----

def test_package_video_requires_video_file():
    with pytest.raises(ValueError, match="视频文件"):
        ContentPackage(title="t", format=ContentFormat.VIDEO)


def test_package_article_requires_body():
    with pytest.raises(ValueError, match="正文"):
        ContentPackage(title="t", format=ContentFormat.ARTICLE)


def test_package_title_required():
    with pytest.raises(ValueError, match="标题"):
        ContentPackage(title="  ", format=ContentFormat.ARTICLE, body="b")


# ---- 适配器行为 ----

def test_video_semi_auto_saves_draft_without_clicking_publish():
    """D20 勘误：视频编辑页有「存草稿」按钮，半自动走草稿箱与图文同口径。"""
    page = FakePage(logged_in=True)
    result = make_adapter(page).publish(video_package(), make_account())

    assert result.status == PublishStatus.DRAFT_READY
    assert "草稿" in result.message
    clicked = [c[1] for c in page.calls if c[0] == "click"]
    assert SELECTORS["video_draft_btn"] in clicked
    assert SELECTORS["video_publish_btn"] not in clicked


def test_video_fill_draft_order_upload_title_cover():
    page = FakePage(logged_in=True)
    make_adapter(page).publish(video_package(), make_account())

    kinds = [
        c[0]
        for c in page.calls
        if c[0] not in ("wait_for_selector", "wait_for_url", "wait_for_timeout")
    ]
    assert kinds == ["goto", "set_input_files", "fill", "click", "click"]
    ops = [c for c in page.calls]
    assert ("goto", SELECTORS["video_publish_url"]) in ops
    assert ("set_input_files", SELECTORS["video_upload"], str(Path("pkg/video.mp4"))) in ops
    assert ("fill", SELECTORS["video_title_input"], "突发山火：救援连夜扑救") in ops
    assert ("click", SELECTORS["video_cover"]) in ops
    assert ("click", SELECTORS["video_draft_btn"]) in ops  # 半自动末步存草稿（D20）


def test_video_auto_publish_clicks_video_publish():
    page = FakePage(logged_in=True)
    result = make_adapter(page).publish(video_package(), make_account(auto_publish=True))

    assert result.status == PublishStatus.PUBLISHED
    clicked = [c[1] for c in page.calls if c[0] == "click"]
    assert SELECTORS["video_publish_btn"] in clicked
    assert SELECTORS["publish_btn"] not in clicked


def test_needs_login_short_circuits():
    page = FakePage(logged_in=False)
    result = make_adapter(page).publish(video_package(), make_account())

    assert result.status == PublishStatus.NEEDS_LOGIN
    assert not [c for c in page.calls if c[0] in ("fill", "set_input_files", "click")]


def test_logged_in_detected_via_timeout_when_entry_absent():
    """真实 Playwright 等不到登录入口会抛超时而非返回 None——应视为已登录。"""
    page = RealTimeoutPage(logged_in=True)
    pkg = ContentPackage(title="图文快讯", body="正文", format=ContentFormat.ARTICLE)
    result = make_adapter(page).publish(pkg, make_account())

    assert result.status == PublishStatus.DRAFT_READY


def test_not_logged_in_detected_when_entry_present():
    """兜底路径：URL 未含 auth 但登录入口存在（如登录页变体）也应判未登录。"""
    page = RealTimeoutPage(logged_in=False)
    page.url = "https://mp.toutiao.com/some-other-page"
    result = make_adapter(page).publish(video_package(), make_account())

    assert result.status == PublishStatus.NEEDS_LOGIN


def test_needs_login_via_auth_redirect_url():
    """D14 校准：未登录 302 到 /auth/page/login，按 URL 判定，不依赖按钮渲染速度。"""
    page = FakePage(logged_in=False)
    result = make_adapter(page).publish(video_package(), make_account())

    assert result.status == PublishStatus.NEEDS_LOGIN
    assert ("wait_for_url", "**/auth/**") in page.calls
    assert not [c for c in page.calls if c[0] in ("fill", "set_input_files", "click")]


def test_article_package_uses_article_url_without_video_upload():
    page = FakePage(logged_in=True)
    pkg = ContentPackage(title="图文快讯", body="正文", format=ContentFormat.ARTICLE, tags=["快讯"])
    make_adapter(page).publish(pkg, make_account())

    gotos = [c[1] for c in page.calls if c[0] == "goto"]
    uploads = [c for c in page.calls if c[0] == "set_input_files"]
    assert gotos == [SELECTORS["article_publish_url"]]
    assert uploads == []


def test_article_auto_saves_without_clicking():
    """图文页平台自动存草稿（D14 真机校准）：不点击任何按钮，等待落盘即返回。"""
    page = FakePage(logged_in=True)
    pkg = ContentPackage(title="图文快讯", body="正文", format=ContentFormat.ARTICLE)
    result = make_adapter(page).publish(pkg, make_account())

    assert result.status == PublishStatus.DRAFT_READY
    assert result.message == "草稿已自动保存，等待人工发布"
    assert [c for c in page.calls if c[0] == "click"] == []
    assert ("wait_for_timeout", DRAFT_SETTLE_MS) in page.calls


def test_adapter_satisfies_protocol():
    assert isinstance(make_adapter(FakePage()), PublishAdapter)


# ---- Account 模型默认值 ----

def test_account_defaults_draft_adapter_and_auto_publish_off():
    acc = make_account()
    assert acc.channel == PublishChannel.TOUTIAO
    assert acc.adapter == PublishAdapterKind.DRAFT
    assert acc.auto_publish is False


# ---- CDP 模式（D14 路线 A）----

class FakeCdpPage(FakePage):
    """CDP 页面替身：显式指定 URL，并记录 close()（新建页才会被关闭）。

    evaluate_result：page.evaluate 的预设返回值（None 时 evaluate 抛错，
    模拟未注入抓取结果的场景）。"""

    def __init__(
        self,
        url: str = "https://mp.toutiao.com/",
        logged_in: bool = True,
        evaluate_result: str | None = None,
    ):
        super().__init__(logged_in=logged_in)
        self.url = url
        self.closed = False
        self.evaluate_result = evaluate_result

    def close(self) -> None:
        self.calls.append(("close",))
        self.closed = True

    def evaluate(self, expression: str, arg=None):
        self.calls.append(("evaluate", expression, arg))
        if self.evaluate_result is None:
            raise RuntimeError("evaluate_result 未注入")
        return self.evaluate_result


class FakeCdpContext:
    def __init__(self, pages: list):
        self.pages = pages

    def new_page(self) -> FakeCdpPage:
        page = FakeCdpPage(url="about:blank")
        self.pages.append(page)
        return page


class FakeCdpBrowser:
    """connect_over_cdp 替身：单个默认上下文；close 只计数（断连语义）。"""

    def __init__(self, pages: list):
        self.contexts = [FakeCdpContext(pages)]
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def article_package() -> ContentPackage:
    return ContentPackage(title="图文快讯", body="正文内容", format=ContentFormat.ARTICLE)


def make_cdp_adapter(
    browser: FakeCdpBrowser, endpoint: str = "http://localhost:9222"
) -> tuple[ToutiaoDraftAdapter, list[str]]:
    seen: list[str] = []

    def factory(ep: str) -> FakeCdpBrowser:
        seen.append(ep)
        return browser

    return ToutiaoDraftAdapter(cdp_endpoint=endpoint, cdp_browser_factory=factory), seen


def test_cdp_mode_reuses_existing_toutiao_tab():
    """CDP 模式：复用已打开的头条标签页填稿；退出仅断连，不关闭复用标签页。"""
    page = FakeCdpPage(url="https://mp.toutiao.com/profile_v4/graphic/publish")
    browser = FakeCdpBrowser([page])
    adapter, seen = make_cdp_adapter(browser)

    result = adapter.publish(article_package(), make_account())

    assert seen == ["http://localhost:9222"]  # endpoint 透传给工厂
    assert result.status == PublishStatus.DRAFT_READY
    assert result.message == "草稿已自动保存，等待人工发布"
    assert ("fill", SELECTORS["title_input"], "图文快讯") in page.calls
    assert page.closed is False
    assert browser.close_calls == 1


def test_cdp_mode_creates_and_closes_tab_when_toutiao_absent():
    """CDP 模式：无头条标签页时新建；退出只关新建页，用户浏览器保持运行。"""
    browser = FakeCdpBrowser([])
    adapter, _ = make_cdp_adapter(browser)

    result = adapter.publish(article_package(), make_account())

    assert result.status == PublishStatus.DRAFT_READY
    assert len(browser.contexts[0].pages) == 1
    created = browser.contexts[0].pages[0]
    assert ("goto", SELECTORS["article_publish_url"]) in created.calls
    assert ("fill", SELECTORS["title_input"], "图文快讯") in created.calls
    assert created.closed is True
    assert browser.close_calls == 1


def test_cdp_mode_needs_login_short_circuits_and_keeps_tab():
    """CDP 模式：未登录（auth 页）短路返回 NEEDS_LOGIN，不执行填稿、不关复用页。"""
    page = FakeCdpPage(url="https://mp.toutiao.com/auth/page/login", logged_in=False)
    browser = FakeCdpBrowser([page])
    adapter, _ = make_cdp_adapter(browser)

    result = adapter.publish(article_package(), make_account())

    assert result.status == PublishStatus.NEEDS_LOGIN
    assert "调试浏览器" in result.message
    assert not [c for c in page.calls if c[0] in ("fill", "set_input_files", "click")]
    assert page.closed is False
    assert browser.close_calls == 1


def test_cdp_factory_ignored_without_endpoint():
    """cdp_endpoint 为空时走 profile 模式注入（browser_factory），CDP 工厂不生效。"""
    called: list[str] = []
    adapter = ToutiaoDraftAdapter(
        browser_factory=lambda profile_dir: FakeCtx(FakePage(logged_in=True)),
        cdp_browser_factory=lambda ep: called.append(ep),
    )

    result = adapter.publish(article_package(), make_account())

    assert result.status == PublishStatus.DRAFT_READY
    assert called == []


# ---- 已发布列表查询（2026-09-17 真机校准）----

# 真机响应结构采样（.scratch/selector-calibration/published_list*_check.txt）：
# {code: 0, contents: [{article_attr: {title, status, ...}}], total_count, has_more}
def published_list_payload() -> str:
    return json.dumps(
        {
            "code": 0,
            "message": "success",
            "contents": [
                {"article_attr": {"title": " 图文快讯 ", "status": 2}},
                {"article_attr": {"title": "微头条观察", "status": 2}},
                {"article_attr": {"title": "", "status": 2}},  # 空标题跳过
                {"article_attr": {"status": 2}},  # 缺标题跳过
                {"article_attr": None},  # 结构异常跳过
                {},  # 无 article_attr 跳过
            ],
            "total_count": 6,
            "has_more": False,
        },
        ensure_ascii=False,
    )


def make_list_adapter(evaluate_result: str | None) -> tuple[ToutiaoDraftAdapter, FakeCdpPage]:
    page = FakeCdpPage(
        url="https://mp.toutiao.com/profile_v4/index", evaluate_result=evaluate_result
    )
    browser = FakeCdpBrowser([page])
    adapter = ToutiaoDraftAdapter(
        cdp_endpoint="http://localhost:9222", cdp_browser_factory=lambda ep: browser
    )
    return adapter, page


def test_list_published_titles_fetches_calibrated_endpoint():
    adapter, page = make_list_adapter(published_list_payload())

    titles = adapter.list_published_titles(make_account())

    assert titles == ["图文快讯", "微头条观察"]  # 归一化（strip）后返回
    evals = [c for c in page.calls if c[0] == "evaluate"]
    assert len(evals) == 1
    assert evals[0][2] == SELECTORS["published_list_url"]  # fetch 真机校准端点
    assert "credentials: 'include'" in evals[0][1]  # 同源带凭据
    assert page.closed is False  # 复用标签页不关闭
    assert ("goto", "https://mp.toutiao.com/") in page.calls  # 统一落点用于登录态检测


def test_list_published_titles_without_cdp_returns_empty():
    """profile 模式（无 cdp_endpoint）不支持列表查询：短路返回空，不连浏览器。"""
    called: list[str] = []
    adapter = ToutiaoDraftAdapter(cdp_browser_factory=lambda ep: called.append(ep))

    assert adapter.list_published_titles(make_account()) == []
    assert called == []


def test_list_published_titles_not_logged_in_returns_empty():
    adapter, page = make_list_adapter(published_list_payload())
    page.logged_in = False
    page.url = "https://mp.toutiao.com/auth/page/login"

    assert adapter.list_published_titles(make_account()) == []
    assert not [c for c in page.calls if c[0] == "evaluate"]  # 未登录不发起 fetch


def test_parse_published_titles_rejects_abnormal_responses():
    adapter = make_list_adapter(None)[0]

    assert adapter._parse_published_titles("not json") == []  # 非 JSON
    assert adapter._parse_published_titles('{"code": 7, "message": "err"}') == []  # code 非 0
    assert adapter._parse_published_titles('{"code": 0}') == []  # 缺 contents
    assert adapter._parse_published_titles('{"code": 0, "contents": "x"}') == []  # contents 非数组
    assert adapter._parse_published_titles("[1, 2]") == []  # 顶层非对象
    assert adapter._parse_published_titles(None) == []  # 非字符串入参