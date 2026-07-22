# Model Release Registry

`model_releases` 是模型准入的 PostgreSQL 权威状态。每条记录归属 workspace，并以
`model_key + release_name` 唯一标识不可变 release，保存 provider、endpoint、license
record、model card、非敏感配置和可选 fallback release。

许可状态与自动化状态分离：

- license：`REVIEW`、`APPROVED`、`REJECTED`；
- automation：`OBSERVE`、`CANARY`、`ACTIVE`、`DISABLED`。

CANARY 只允许 1–99% 流量，ACTIVE 必须为 100%，OBSERVE/DISABLED 必须为 0%。每个
model key 可同时存在一个 ACTIVE 基线和一个 CANARY；灰度命中由 `job_id + model_key`
稳定散列决定，未命中时回到 ACTIVE。CANARY 必须已有 ACTIVE 基线，提升为 ACTIVE 时会在
同一事务内关闭旧基线。进入 CANARY/ACTIVE 前要求许可已批准、license/model card 非空，
且 endpoint 使用 HTTPS 或 localhost。许可变更前必须先关闭自动流量。所有变更通过 state
version CAS。

迁移 `0006_model_releases.sql` 建立表、准入索引，并把 `stage_runs.model_release_id` 变为
真实外键。控制平面提供创建、查询、许可审批和自动化切换 API；分析 DAG 创建时选择
ACTIVE/CANARY release，把 release 外键与非敏感运行参数注入 Stage。Worker 只从环境读取
bearer token，Registry 和 Stage 参数均不保存密钥。
