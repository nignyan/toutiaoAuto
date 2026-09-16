"""端到端真机验证辅助：修账号名 → 采集 → 检查事件/素材状态。

只做链路准备，派发单独执行（会弹真机浏览器）。
"""

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    account_id = sys.argv[1]

    # 1. 修正账号名（PowerShell 曾把 UTF-8 写坏）
    acc = call("PATCH", f"/accounts/{account_id}", {"name": "真机校准账号"})
    print("account fixed:", acc["name"], acc["profile_dir"])

    # 2. 采集真实热点信号
    report = call("POST", "/pipeline/collect", {})
    print("sources:", json.dumps(report["sources"], ensure_ascii=False)[:400])
    print("events created:", len(report["created"]), "updated:", len(report["updated"]))

    # 3. 事件与素材状态
    events = call("GET", "/events?limit=20")
    for ev in events[:10]:
        detail = call("GET", f"/events/{ev['id']}")
        assets = detail["assets"]
        usable = [a for a in assets if a["auth_status"] == "cleared"]
        print(
            f"event {ev['id'][:8]} [{ev['status']}] {ev['title'][:24]} "
            f"assets={len(assets)} cleared={len(usable)} "
            f"format={detail['decision_format']}"
        )


if __name__ == "__main__":
    main()
