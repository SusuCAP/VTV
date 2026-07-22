# Model Release Registry

`model_releases` 是模型准入的 PostgreSQL 权威状态。每条记录归属 workspace，并以
`model_key + release_name` 唯一标识不可变 release，保存 provider、endpoint、license
record、model card、非敏感配置和可选 fallback release。

许可状态与自动化状态分离：

- license：`REVIEW`、`APPROVED`、`REJECTED`；
- automation：`OBSERVE`、`CANARY`、`ACTIVE`、`DISABLED`。

CANARY 只允许 1–99% 流量，ACTIVE 必须为 100%，OBSERVE/DISABLED 必须为 0%。进入
CANARY/ACTIVE 前要求许可已批准、license/model card 非空，且 endpoint 使用 HTTPS 或
localhost。许可变更前必须先关闭自动流量。所有变更通过 state version CAS。

迁移 `0006_model_releases.sql` 建立表、准入索引，并把 `stage_runs.model_release_id` 变为
真实外键。下一增量将提供 Registry API，并在分析 DAG 创建时选择 ACTIVE/CANARY release。

