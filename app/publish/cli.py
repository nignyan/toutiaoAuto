"""头条草稿箱适配器命令行入口。

用法：
    # 首次登录（弹出浏览器，扫码后登录态持久化到 profile 目录）
    python -m app.publish.cli login --account-id <id> [--profile-dir PATH]

    # 把内容包目录填进草稿箱（默认不自动发布）
    python -m app.publish.cli fill --account-id <id> --package-dir PATH [--auto-publish]

内容包目录约定：title.txt / body.md / cover.* / video.* / tags.txt（每行一个标签）
"""

import argparse
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
        if name == "fill":
            p.add_argument("--package-dir", required=True)
            p.add_argument("--auto-publish", action="store_true", help="填完直接发布（默认关闭）")

    args = parser.parse_args()
    account = Account(
        id=args.account_id,
        name=args.account_name or args.account_id,
        profile_dir=args.profile_dir,
        auto_publish=getattr(args, "auto_publish", False),
    )
    adapter = ToutiaoDraftAdapter()

    if args.cmd == "login":
        # 打开持久化上下文让用户扫码，登录态自动写入 profile_dir
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