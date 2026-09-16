"""一次性验收种子（运营实机验收 · 数据回流）。

把 4 个 QUALIFIED 视频成品标记为「已发布」（published + published_at），
作为「真实回填→分析→建议确认」流程的前置发布态。发布执行（D13）依赖真实头条，
此处不发真实草稿、仅本地落发布态，模拟运营既往已发布内容，供人工回填表现数据。

- 6810 / 7b6c → 06-12 时段桶（互动率较高）
- 5faa / e998 → 18-24 时段桶（互动率较低）
两者差距 ≥30% 且绝对差 ≥1pp，应触发 1 条 timing 建议（形态/垂类均为单一组不产出）。
"""

import sqlite3

from app.daos import DB

DB_PATH = "data/workflow.db"
ACCOUNT_ID = "8b3ad15c444e47cfa705548fa31fc893"

# (production_id, 已存在队列项 id 或 None, published_at)
TARGETS = [
    ("6810006756de44349c3361c921620bde", "3c4e94b1fc84400d97d1f181ff14b585",
     "2026-09-16T10:00:00+00:00"),
    ("7b6c4090e71249cf907580f01784d08e", None, "2026-09-16T10:30:00+00:00"),
    ("5faa6fc35192409082207c69e185a2d7", None, "2026-09-16T20:00:00+00:00"),
    ("e99875e4130845a99841ccc74c5361ee", None, "2026-09-16T20:30:00+00:00"),
]

RESULT = "[published] 运营确认已发布（验收种子）"


def main() -> None:
    DB(DB_PATH).migrate()  # 幂等：确保 publish_queue.published_at 列存在（D15 补列）
    conn = sqlite3.connect(DB_PATH)
    for pid, item_id, published_at in TARGETS:
        if item_id:
            conn.execute(
                "UPDATE publish_queue SET status='published', published_at=?,"
                " publish_result=? WHERE id=? AND production_id=?",
                (published_at, RESULT, item_id, pid),
            )
        else:
            conn.execute(
                "INSERT INTO publish_queue"
                " (id, account_id, production_id, status, scheduled_for, publish_result,"
                "  published_at, sort_key, created_at)"
                " VALUES (?,?,?,'published','',?,?,0,?)",
                (f"seed-q-{pid[:8]}", ACCOUNT_ID, pid, RESULT, published_at, published_at),
            )
    conn.commit()
    for row in conn.execute(
        "SELECT production_id, status, published_at FROM publish_queue ORDER BY published_at"
    ):
        print(tuple(row))
    conn.close()
    print("seeded ok")


if __name__ == "__main__":
    main()