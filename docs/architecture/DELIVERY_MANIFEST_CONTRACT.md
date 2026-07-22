# 交付与 Provenance Manifest 契约

每个 Episode Delivery 使用 `vtv.delivery-manifest.v1` 不可变清单。清单指向 Media Asset，绝不覆盖对象；
`fingerprint` 对除生成时间外的规范 JSON 计算 SHA-256，因此相同输入、采用决策和编码结果具有稳定身份。

## 最小交付闭包

- 源视频、逐集 Master、至少一种 SRT/VTT 字幕；
- 质量报告与连续、无重叠、从 1 编号的镜头清单；
- 每个编辑 Stage 的输入/输出 SHA-256 与参数 SHA-256；
- 实际 Model Release、权重 SHA-256 和可用 seed；
- Artifact/Candidate/Delivery 人工批准证据及 state version；
- evaluator release、metric version、分数和 PASS/REVIEW 结论；
- 分阶段成本、Provider Usage、最终编码和可选 C2PA 状态。

Manifest 创建前执行硬门禁：任何 hard-failure QC、缺失必需交付角色、重复资产角色、镜头时间线
断裂、成本为负或最终 Master hash 不在编辑链输出中都会失败。该契约是下一步数据库 Delivery Release、
报告资产生成和下载 API 的稳定边界。

## Delivery Release 生命周期

`POST /v1/projects/{project_id}/deliveries` 只接受 Episode、不可变 Media Asset ID、预期 Project
state version 与 C2PA 请求，不接受客户端 Manifest。数据库创建 `DRAFT` Delivery 和带唯一 role 的
`delivery_assets` 关联，并捕获当时的 Project state version。

`POST /v1/deliveries/{delivery_id}/approve` 使用 Delivery state version CAS。事务重新锁定 Project，
如果项目在草稿后发生变化则拒绝批准；随后从 source/master/report/shot-list 资产的服务端 metadata
组装、验证并持久化 Manifest 和 fingerprint，将状态推进到 `APPROVED`，同时写入
`delivery.approved` Outbox。Manifest、审批人和审批时间受到数据库 check constraint 约束，不可能出现
“已批准但无来源清单”的半状态。

`GET /v1/deliveries/{delivery_id}` 与项目级列表接口按 Workspace 隔离返回草稿或已批准版本。Episode
版本号单调递增，旧版本不覆盖；后续 C2PA 或撤销流程沿用同一不可变版本边界。

## Evidence 资产生成

`DELIVERY_EVIDENCE` 是 Episode Assembly 的第五个 Stage，依赖已完成 Master。Scheduler 从实际 Stage
Run、依赖资产、显式输入、Model Release/批准 Benchmark、Render Variant seed、Stage Attempt cost 与
provider usage 构建 request；VTT 等未参与 Master mux 的 sidecar 不会被误记为编码输入。

Worker 使用 FFprobe 再次验证 Master 的时长、视频流和音轨，确定性输出 `quality-report.json` 与
`shot-list.json`。报告包含 evaluator/metric version、编辑链、模型、成本和最终实测编码；镜头清单必须
从 0 连续覆盖完整 Episode，并记录 route、adopted Variant、输出 Asset 与 QC 结论。这两个 JSON 及其
metadata 使用同一强类型内容，随后可直接进入 Delivery Draft，不需要客户端补写证据。
