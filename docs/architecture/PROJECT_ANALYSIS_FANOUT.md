# 项目分析多集 Fan-out

项目分析不再创建一条没有源媒体的伪项目级 ingest 链。创建任务时，Repository 锁定项目并
读取所有拥有 `source_asset_id` 的 Episode，为每集展开：

`INGEST_VALIDATE → PROXY_GENERATE → {SHOT_DETECT, ASR_ALIGN} → VISION_ANALYSIS`

其中视觉分析同时依赖代理和镜头结果。所有集的 `ASR_ALIGN` 与 `VISION_ANALYSIS` 最终汇聚
到唯一 `PROJECT_SYNTHESIS`。N 集任务总阶段数为 `5N + 1`；没有已上传 Episode 时 API
返回 409，不再产生永远无法执行的任务。

Stage 输出登记为 Media Asset 时写入 `episode_id` 和 `stage_type` 元数据，构造下游 Stage
Job 时继续透传。项目合成 Worker 依此按集配对音频/视觉结果，拒绝任一集缺项或重复输入，
随后跨集合并人物 track、场景和逐集 Continuity Snapshot。不同集使用不同模型 release 时，
provenance 保留完整 release 列表。

