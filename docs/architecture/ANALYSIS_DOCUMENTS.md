# 分析文档投影

Worker 的不可变 JSON 文件仍是完整结果资产，同时通过 `DomainArtifact` 返回经过 Schema 校验
的数据库投影。Scheduler 只有在 lease/state/control version 条件提交成功后，才在同一事务中：

- 登记输出 Media Asset；
- 写入 `analysis_documents` JSONB 文档；
- 写入 `analysis_document.created` Outbox；
- 对项目合成结果创建 DRAFT Artifact Release 和依赖。

当前文档类型包括媒体探测、镜头清单、音频分析、视觉分析、项目合成、Localization Bible、
Anchor Pack 和 Continuity Snapshot Set。表按项目/类型建立 B-tree 索引，payload 建立 GIN
索引；控制 API 支持按 project、episode 和 document type 查询。

项目合成会生成三个 DRAFT Release：Bible → Anchor Pack → Continuity Snapshot Set。创建
分析任务时 Repository 在项目锁内计算下一版本并传给 Worker；Bible/Anchor JSON 写入相同
版本，Scheduler 创建 Release 时再次锁定并比较。并发导致版本变化时整个条件提交回滚，不会
产生版本错配。新 Release 会 supersede 同类型旧版本，并传递标记旧下游为 STALE。

