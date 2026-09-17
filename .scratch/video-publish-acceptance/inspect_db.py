"""实机验收前的一次性 DB 盘点（只读）。"""
import os
import sqlite3

p = "data/workflow.db"
print("db exists:", os.path.exists(p))
if not os.path.exists(p):
    raise SystemExit(0)

conn = sqlite3.connect(p)
conn.row_factory = sqlite3.Row

print("---schema---")
for t in ("production", "publish_queue", "accounts", "asset"):
    try:
        cols = [r[1] for r in conn.execute(f"pragma table_info({t})")]
        print(t, cols)
    except Exception as e:  # noqa: BLE001
        print(t, "ERR", e)

print("---queue---")
for r in conn.execute(
    "select id, production_id, account_id, status, publish_result from publish_queue"
):
    print(dict(r))

print("---accounts---")
for r in conn.execute(
    "select id, name, vertical, auto_publish, status, daily_quota from accounts"
):
    print(dict(r))

print("---events---")
for r in conn.execute("select id, status, title, created_at from events order by created_at desc limit 15"):
    print(dict(r))

print("---media_assets---")
for r in conn.execute("select id, event_id, type, source_url, auth_status, source_type, clarity, info_density, attribution from media_assets order by ingested_at desc limit 20"):
    print(dict(r))

print("---accounts detail---")
for r in conn.execute("select id, name, vertical, role, status, daily_quota from accounts"):
    print(dict(r))

print("---ready events---")
for r in conn.execute(
    "select id, title, summary, score, status from events where status='ready'"
):
    print(dict(r))

print("---tables---")
tables = [r[0] for r in conn.execute("select name from sqlite_master where type='table'")]
print(tables)

print("---productions detail---")
for r in conn.execute(
    "select id, event_id, vertical, production_type, quality_status, title from production"
):
    print(dict(r))
