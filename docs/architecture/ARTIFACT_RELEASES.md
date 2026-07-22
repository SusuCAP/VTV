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
自依赖以及项目/类型/状态索引。下一步会将状态机封装为事务 Repository 和控制 API。

