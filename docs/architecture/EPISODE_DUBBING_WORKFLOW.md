# 逐集配音候选工作流

`POST /v1/projects/{project_id}/dubbing-jobs` 把 Phase 3 配音从孤立 Worker 升级为数据库驱动的正式
Job。请求包含目标 Episode、已发布本土化 release 和逐句本土化结果；每句显式引用已发布
`VOICE_RELEASE` 与权威 rights release。

## 创建事务门禁

控制平面在同一事务中：

1. 锁定 Project 和 Execution Control，拒绝取消或 hard-budget block；
2. 验证 Episode 属于项目且存在源资产；
3. 验证 localization artifact 已 `RELEASED`；
4. 验证每个 voice artifact 已 `RELEASED`，并从其权威 Media Asset 读取参考音频 SHA-256；
5. 锁定 rights release，按 `voice_clone + market + language + commercial scope + time` 实时检查；
6. 通过 Model Registry 稳定选择 ACTIVE/CANARY `TTS` release，并要求 `remote_tts` runtime；
7. 每个 utterance 创建独立 Candidate Group 和 READY `TTS_GENERATE` Stage Run；
8. 写入 `dubbing.requested` Outbox，并将项目推进为 `PRODUCING`。

请求的规范 JSON SHA-256 作为幂等键；完全相同的重试返回原 Job，不重复创建候选。每条 Stage
固定 model release、rights release/state version、voice/localization release、seed、候选数和时长
容差。

## 撤销竞态

Job 创建时通过授权不代表结果可永久提交。Scheduler 在 `COMMIT_OUTPUT_READY` 同一事务中重新锁定
rights release，并核对 state version、撤销状态、有效期、操作、市场、语言和商业范围。若推理期间
授权发生变化，Stage 变为 `EXECUTION_FAILED/RIGHTS_BLOCKED`，已生成对象登记到 orphan queue，
不会成为 Media Asset 或分析文档。

## 候选提交与采用

TTS Worker 成功回传后，Scheduler 为每个候选登记独立 Media Asset 和 Render Variant，不自动选中任何
结果。候选必须提交完整的五项 TTS 质检证据，只有 `QC_PASSED` 候选可通过 state version CAS 被唯一
采用；采纳事务还会再次执行授权门禁。详细不变量见
[`CANDIDATE_SELECTION.md`](./CANDIDATE_SELECTION.md)。
