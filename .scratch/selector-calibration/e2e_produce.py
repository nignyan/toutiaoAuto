"""端到端真机验证第二段：批量生产 → 批量入队 → 展示待派发队列。"""

import json

from e2e_chain import call

report = call("POST", "/pipeline/produce/all", {})
produced = report["produced"]
skipped = report["skipped"]
print(f"produced={len(produced)} skipped={len(skipped)}")
for s in skipped[:5]:
    print("  skip:", s["event_id"][:8], s["reason"])
for p in produced:
    print(f"  production {p['id'][:8]} [{p['quality_status']}] score={p['quality_score']} {p['title'][:24]}")

qualified = [p for p in produced if p["quality_status"] == "qualified"]
if not qualified:
    # 兜底：查留档（可能此前已生产过 QUALIFIED）
    qualified = call("GET", "/productions?status=qualified")

if not qualified:
    raise SystemExit("没有 QUALIFIED 成品，无法入队")

# 取质量分最高的一条入队
best = max(qualified, key=lambda p: p["quality_score"])
item = call("POST", "/pipeline/enqueue", {"production_id": best["id"]})
print("enqueued:", json.dumps(item, ensure_ascii=False)[:300])

queue = call("GET", "/publish-queue")
print("queue size:", len(queue))
for q in queue[:5]:
    print(f"  queue {q['id'][:8]} [{q['status']}] production={q['production_id'][:8]} account={q['account_id'][:8]}")
