"""头条草稿箱适配器命令行入口。

用法：
    # CDP 模式（推荐，D14）：连接用户真实 Chrome（须带 --remote-debugging-port 启动）
    # 环境变量 TOUTIAO_CDP_ENDPOINT 可代替 --cdp-endpoint
    python -m app.publish.cli login --account-id <id> --cdp-endpoint http://localhost:9222
    python -m app.publish.cli fill --account-id <id> --package-dir PATH --cdp-endpoint http://localhost:9222

    # profile 模式（遗留）：弹出独立浏览器，扫码后登录态持久化到 profile 目录
    python -m app.publish.cli login --account-id <id> [--profile-dir PATH]

    # fill 默认不自动发布
内容包目录约定：title.txt / body.md / cover.* / video.* / tags.txt（每行一个标签）
"""

import argparse
import os
from pathlib import Path

from app.models.account import Account
from app.publish.adapter import ContentFormat, ContentPackage
from app.publish.toutiao_draft import ToutiaoDraftAdapter


def load_package(package_dir: str) -> ContentPackage:
    d = Path(package_dir)
    title = (d / "title.txt").read_text(encoding="utf-8").strip()
    body = (d / "body.md").read_text(encoding="utf-8").strip() if (d / "body.md").exists() else ""
    tags = []
    if (d / "tags.txt").exists():
        tags = [t.strip() for t in
                (d / "tags.txt").read_text(encoding="utf-8").splitlines() if t.strip()]
    video = next((p for ext in ("*.mp4", "*.mov") for p in d.glob(ext)), None)
    cover = next((p for ext in ("*.jpg", "*.png", "*.webp") for p in d.glob(ext)), None)
    fmt = ContentFormat.VIDEO if video else ContentFormat.ARTICLE
    return ContentPackage(
        title=title, body=body, format=fmt, video_path=video, cover_path=cover, tags=tags
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.publish.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("login", "fill"):
        p = sub.add_parser(name)
        p.add_argument("--account-id", required=True)
        p.add_argument("--account-name", default="")
        p.add_argument("--profile-dir", default="")
        p.add_argument(
            "--cdp-endpoint", default="",
            help="CDP 调试端点（如 http://localhost:9222），设置后走 CDP 模式；"
                 "留空回读环境变量 TOUTIAO_CDP_ENDPOINT",
        )
        if name == "fill":
            p.add_argument("--package-dir", required=True)
            p.add_argument("--auto-publish", action="store_true", help="填完直接发布（默认关闭）")

    args = parser.parse_args()
    cdp_endpoint = args.cdp_endpoint or os.environ.get("TOUTIAO_CDP_ENDPOINT") or None
    account = Account(
        id=args.account_id,
        name=args.account_name or args.account_id,
        profile_dir=args.profile_dir,
        auto_publish=getattr(args, "auto_publish", False),
    )
    adapter = ToutiaoDraftAdapter(cdp_endpoint=cdp_endpoint)

    if args.cmd == "login":
        if cdp_endpoint:
            # CDP 模式：连到用户真实 Chrome，未登录则在用户窗口里完成登录
            with adapter._open_cdp_page() as page:
                if adapter._is_logged_in(page):
                    print("已检测到登录态，无需重复登录。")
                    return
                input("请在打开的浏览器窗口中登录头条号，完成后按回车…")
                ok = adapter._is_logged_in(page)
            if ok:
                print("登录态已确认。")
            else:
                print("仍未检测到登录态，请重新运行 login。")
                raise SystemExit(2)
            return
        # profile 模式（遗留）：打开持久化上下文让用户扫码，登录态自动写入 profile_dir
        with adapter._open_page(account.profile_dir or str(adapter.profiles_root / account.id)):
            input("请在浏览器中完成登录，完成后按回车关闭…")
        print("登录态已保存。")
        return

    package = load_package(args.package_dir)
    result = adapter.publish(package, account)
    print(f"[{result.status.value}] {result.message}")
    if result.status.value == "needs_login":
        raise SystemExit(2)


if __name__ == "__main__":
    main()