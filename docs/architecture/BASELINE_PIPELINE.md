# Phase 1 基线交付流水线

Phase 1 使用确定性 Mock Worker 验证控制面、数据库、调度、产物登记和交付状态，不将模型下载或 GPU 可用性作为平台闭环的前置条件。

## Episode DAG

`INGEST_VALIDATE → PROXY_GENERATE → SHOT_DETECT → MOCK_LOCALIZE → MOCK_RENDER → QC_TECHNICAL → ASSEMBLE_EPISODE → DELIVERY_MANIFEST`

每个 Stage Run 都具有独立 idempotency key、runtime profile、state version、control version 和 attempt lease。调度器通过 `FOR UPDATE SKIP LOCKED` 领取 READY 阶段，Worker 返回 `StageResult` 后执行条件提交。

## 产物规则

- Worker 只能写入不可变输出前缀。
- 每个成功输出登记为 `media_assets`，关联来源 Stage Run、SHA-256、类型和大小。
- 条件提交失败的输出登记为 orphan，不得成为后续输入。
- 下游阶段只读取已完成依赖的登记资产。
- 最后一个阶段完成时 Job 状态变为 `SUCCEEDED`。

本地命令：

```bash
.venv/bin/vtv-orchestrator postgresql+asyncpg://vtv:vtv@127.0.0.1:5432/vtv
```

真实模型 Worker 后续只需遵循同一 `StageJob → StageResult` 契约，即可替换 Mock 实现。
