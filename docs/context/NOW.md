# NOW — 当前开发状态

> 最后更新：2026-09-15

## 当前阶段
- 产品设计与开发规范已就绪，MVP **代码骨架**已搭建完毕。
- 已完成：FastAPI 健康检查、领域模型、SQLite DAO 骨架、内容形态决策模块、交互 Demo（demo/）、头条草稿箱发布适配器。
- 下一步：热点采集、事件聚类与素材入库（见 `MAP.md`）；头条选择器需实测校准（见 RISKS）。

## 活动里程碑
- [x] 产品设计定稿（2026-09-15）
- [x] AGENTS.md 个性化开发规范合并
- [x] PROJECT_INDEX.md 与 docs/context/ 分层结构
- [x] MVP 代码骨架（FastAPI + SQLite + 形态决策）
- [x] 交互 Demo（demo/，模拟数据 + 真实交互，8 视图）
- [x] 头条草稿箱适配器（app/publish/，auto_publish 默认关闭）
- [ ] 热点采集 → 事件聚类 → 素材入库
- [ ] 头条后台选择器实测校准

## 主要阻塞
- 无。

## 最近闭环摘要
- 初始化 Git 仓库并提交产品设计文档。
- 合并个性化开发规范至 AGENTS.md。
- 交互 Demo 重做并迁移至 demo/，提交 02ff63e。
- 新增 app/publish/ 草稿箱适配器 + CLI + 10 项单测（pytest 22/22 通过）。
- 同步 PROJECT_INDEX.md / MAP.md 至代码现状，修复索引落后于实现的文档漂移。