# RUNBOOK — 运行与验收

> 当前处于编码前阶段，以下为规划；实现代码后回填真实命令。最后校核：2026-09-15

## 构建
- 依赖安装：`pip install -e ".[dev]"`（待 `pyproject.toml` 确定）
- 静态检查：`ruff check .`

## 测试
- `pytest`
- 验收口径见 AGENTS.md「基础约束」：每次改动须有对应测试且全部通过。

## 运行
- 服务：`uvicorn app.main:app --reload`（待实现后确认）

## 发布/清理
- 当前无发布流程；清理工作树仅作可回退移动归档，须按授权执行。