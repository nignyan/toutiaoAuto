"""头条草稿箱适配器单测：用 FakePage 验证流程顺序与 auto_publish 开关语义。"""

from pathlib import Path

import pytest

from app.models.account import Account, PublishAdapterKind, PublishChannel
from app.publish.adapter import (
    ContentFormat,
    ContentPackage,
    PublishAdapter,
    PublishStatus,
)
from app.publish.toutiao_draft import SELECTORS, ToutiaoDraftAdapter


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

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

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

def test_fill_draft_stops_at_save_draft_by_default():
    page = FakePage(logged_in=True)
    result = make_adapter(page).publish(video_package(), make_account())

    assert result.status == PublishStatus.DRAFT_READY
    clicked = [c[1] for c in page.calls if c[0] == "click"]
    assert SELECTORS["save_draft_btn"] in clicked
    assert SELECTORS["publish_btn"] not in clicked


def test_fill_draft_order_goto_upload_title_body_tags_cover():
    page = FakePage(logged_in=True)
    make_adapter(page).publish(video_package(), make_account())

    kinds = [c[0] for c in page.calls if c[0] != "wait_for_selector"]
    assert kinds == [
        "goto", "set_input_files", "fill", "fill",
        "fill", "press", "fill", "press",  # 两个标签
        "set_input_files",  # 封面
        "click",  # 存草稿
    ]
    ops = [c for c in page.calls if c[0] != "wait_for_selector"]
    assert ops[1] == ("set_input_files", SELECTORS["video_upload"], str(Path("pkg/video.mp4")))
    assert ops[2] == ("fill", SELECTORS["title_input"], "突发山火：救援连夜扑救")


def test_auto_publish_clicks_publish_instead_of_draft():
    page = FakePage(logged_in=True)
    result = make_adapter(page).publish(video_package(), make_account(auto_publish=True))

    assert result.status == PublishStatus.PUBLISHED
    clicked = [c[1] for c in page.calls if c[0] == "click"]
    assert SELECTORS["publish_btn"] in clicked
    assert SELECTORS["save_draft_btn"] not in clicked


def test_needs_login_short_circuits():
    page = FakePage(logged_in=False)
    result = make_adapter(page).publish(video_package(), make_account())

    assert result.status == PublishStatus.NEEDS_LOGIN
    assert not [c for c in page.calls if c[0] in ("fill", "set_input_files", "click")]


def test_article_package_uses_article_url_without_video_upload():
    page = FakePage(logged_in=True)
    pkg = ContentPackage(title="图文快讯", body="正文", format=ContentFormat.ARTICLE, tags=["快讯"])
    make_adapter(page).publish(pkg, make_account())

    gotos = [c[1] for c in page.calls if c[0] == "goto"]
    uploads = [c for c in page.calls if c[0] == "set_input_files"]
    assert gotos == [SELECTORS["article_publish_url"]]
    assert uploads == []


def test_adapter_satisfies_protocol():
    assert isinstance(make_adapter(FakePage()), PublishAdapter)


# ---- Account 模型默认值 ----

def test_account_defaults_draft_adapter_and_auto_publish_off():
    acc = make_account()
    assert acc.channel == PublishChannel.TOUTIAO
    assert acc.adapter == PublishAdapterKind.DRAFT
    assert acc.auto_publish is False