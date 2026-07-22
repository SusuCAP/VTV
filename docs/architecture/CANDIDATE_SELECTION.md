# 候选持久化与唯一采纳

Production Worker 返回的多候选结果不会直接成为业务采用结果。Scheduler 在提交事务中先登记不可变
Media Asset，再为每个候选写入 `render_variants`；候选通过 `candidate_group_id` 归入同一个业务决策组，
并保留 Stage Run、候选序号、seed、原始指标和成本 provenance。

## 质检证据

`POST /v1/candidate-variants/{variant_id}/qc` 只接受 `GENERATED` 候选，并为每项指标保存：

- metric name 与 metric version；
- evaluator release；
- score、verdict、hard failure 与结构化详情。

TTS 候选必须一次提交完整的 intelligibility、speaker similarity、emotion fidelity、duration fit 和
audio artifact control 五项证据。任一硬失败或 FAIL 进入 `QC_FAILED`，任一 REVIEW 进入 `REVIEW`，
只有全部通过才进入 `QC_PASSED`。指标证据不可覆盖，重评应生成新的候选或后续显式评测版本。

## 唯一采纳事务

`POST /v1/candidate-groups/{group_id}/adopt` 使用 Candidate Group `state_version` 做 CAS，并要求目标候选
已 `QC_PASSED`。同一数据库事务内完成：

1. 重新检查 voice rights 的 state version、撤销状态、时效、操作、市场、语言与商业范围；
2. 将目标候选标记为 `ADOPTED`，其余候选标记为 `REJECTED`；
3. 将 Candidate Group 标记为 `ADOPTED` 并写入唯一 adopted variant 外键；
4. 将对应 Stage Run 推进为 `ADOPTED`，写入 Outbox 审计事件。

数据库约束、行锁和 CAS 共同保证每组最多一个最终采用结果。授权在质检后撤销时，采纳仍会被阻止。

