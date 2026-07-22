# 资产确认、发布与失效传播

项目级语义资产和生产结果通过 `artifact_releases` 保存版本化权威状态，内容本身仍由
`media_assets` 指向对象存储。每条 release 具有项目、资产类型、递增版本、内容资产、
可选被替代版本以及独立 `state_version`。

状态机为 `DRAFT → CONFIRMED → RELEASED → STALE`：

- 确认必须提供操作者并匹配预期 state version。
- 发布只接受已确认资产，并要求全部直接依赖已经发布。
- Bible、Anchor 或其他上游版本变化时，沿 `artifact_release_dependencies` 对所有下游做
  传递失效；算法使用 visited 集，异常环不会导致死循环。
- 所有状态变化递增 state version，为数据库条件更新和并发冲突检测提供依据。

迁移 `0004_artifact_releases.sql` 建立 release 与依赖表、唯一版本约束、状态检查、禁止
自依赖以及项目/类型/状态索引。

事务 Repository 和控制 API 已覆盖：创建/列举 release、确认、发布、显式失效。每个写操作
校验 workspace/project 边界并写 Outbox。新版本携带 `supersedes_release_id` 时，会在同一
事务内锁定并使旧版本及全部下游 release 进入 `STALE`，避免“新版本已创建、旧产物仍可用”
的竞态窗口。API 使用 `expected_state_version`，版本冲突返回 HTTP 409。
