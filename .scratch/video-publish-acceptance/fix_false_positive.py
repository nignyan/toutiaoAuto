"""勘误：D19 假阳性队列项改回 failed（一次性修正脚本）。"""
import sqlite3

c = sqlite3.connect("data/workflow.db")
c.execute(
    "update publish_queue set status='failed', publish_result=?, published_at=''"
    " where id='c449a0e9b5ae48dcbbff0105d532baf1'",
    ("[failed] 勘误：D19 验收假阳性——误点定时发布按钮，视频未发布（list/v2 核验无此标题）",),
)
c.commit()
for r in c.execute(
    "select id, status, publish_result, published_at from publish_queue"
    " where id='c449a0e9b5ae48dcbbff0105d532baf1'"
):
    print(r)
