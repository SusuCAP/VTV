# 项目进度

最后更新：2026-07-22

## 总览

| 阶段 | 状态 | 完成度 | 当前交付 |
|---|---|---:|---|
| Phase 0 工程与规格基线 | 已完成 | 100% | 仓库说明、路线图、环境与提交规范 |
| Phase 1 基础平台 | 进行中 | 15% | 共享 Schema、控制 API 最小闭环、测试基线 |
| Phase 2 全剧分析 | 未开始 | 0% | — |
| Phase 3 自动生产 | 未开始 | 0% | — |
| Phase 4 QC 与批量 | 未开始 | 0% | — |
| Phase 5 研究工具完善 | 未开始 | 0% | — |

## 已完成

- [x] 读取 v3.2 最终技术方案，确认 24 章主体与附录定义的总体范围。
- [x] 确认技术主线：Tauri + React、FastAPI、PostgreSQL、S3 兼容对象存储、Modal。
- [x] 建立与原方案 P0–P5 对齐的实施路线图。
- [x] 建立 Python/Node 隔离规则、媒体与模型文件忽略规则。
- [x] 初始化 Git `main` 分支并配置 GitHub 私有远端。

## 当前进行

- [x] 建立 `uv` workspace 和项目长期 `.venv`。
- [x] 固化项目、预算、输出规格、Stage Job/Result 首批共享 Schema。
- [x] 实现项目创建/查询与异步分析任务提交/查询 API。
- [x] 验证工作区隔离、预算约束和 `202 + job_id + Location` 契约。
- [ ] 用 PostgreSQL Repository 替换开发期内存 Repository。
- [ ] 实现首版数据库迁移、DAG、Outbox、lease 与条件提交。
- [ ] 建立 Node workspace 与 React/Tauri 控制端骨架。

## 下一提交目标

`feat: add shared schemas and control API project flow`

完成后继续 Phase 1 的“PostgreSQL 核心模型 + 数据库驱动状态机”。

## 决策日志

| 日期 | 决策 | 原因 |
|---|---|---|
| 2026-07-22 | 以数据库驱动编排为第一条工程主线 | 它承接幂等、断点续跑、取消、成本和追溯，是后续模型 Worker 的稳定边界。 |
| 2026-07-22 | 模型 Adapter 先实现协议与 Mock，再接真实权重 | 先验证业务流水线，避免模型下载、许可和 GPU 可用性阻塞平台开发。 |
| 2026-07-22 | 不把所有候选模型同时接入首轮 | 遵循方案附录建议，优先四组双路组合并保留稳定回退。 |

## 验证记录

| 日期 | 范围 | 结果 |
|---|---|---|
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 4 passed；存在 FastAPI TestClient 的上游弃用提示 |
