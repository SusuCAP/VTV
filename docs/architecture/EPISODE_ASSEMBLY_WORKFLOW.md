# 逐集合成 Job 与数据库 DAG

`POST /v1/projects/{project_id}/assembly-jobs` 创建逐集确定性合成 Job。请求规范 JSON SHA-256 是幂等键，
输出尺寸、帧率、编解码和字幕格式只从 Project `output_spec` 注入，客户端不能临时覆盖。

## 权威输入门禁

创建事务验证：

1. source video 属于同一 workspace/project/Episode，包含权威 `duration_seconds`；
2. 每个画面选择是对应 Shot 的唯一 `ADOPTED` LIPSYNC/RENDER Variant，且 Shot 区间不重叠、不越界；
3. 每个对白选择是同集唯一 `ADOPTED` TTS Variant，开始/结束时间从 TTS Request provenance 读取；
4. MUSIC/EFFECTS/BACKGROUND 资产的 `episode_id` 与 `stem_kind` 同请求一致；
5. 字幕连续编号、非重叠并且不超过源集时长；
6. Execution Control 未取消、未触发 hard budget block。

同一事务写入 Job、五个 Stage Run、四条依赖边和 `assembly.requested` Outbox。

## 五阶段 DAG

```text
PICTURE_CONFORM ─┐
SUBTITLE_RENDER ─┼─> ASSEMBLE_EPISODE
AUDIO_MIX ───────┘           │
                              └─> DELIVERY_EVIDENCE
```

前三个 Stage 可并行执行，Master 与 Evidence 初始为 `PENDING`；只有三者均 `COMPLETED` 才推进 Master，
Master 完成后才推进 Evidence。
Picture/Mix 使用显式 Media Asset ID，Scheduler 再按 workspace/project 验证并装载。Master 不在创建时猜测
未来 hash：Scheduler 从三个已提交上游 Stage 的 Media Asset metadata 识别唯一 picture master、audio mix
和 SRT，将真实 SHA-256 动态注入强类型 Episode Assembly Request。VTT 等 sidecar 不会误入 mux 输入；
缺失或重复 picture/mix/SRT 会在派发前失败。

Evidence Scheduler 从同一 Job 的实际完成 Stage、输入/输出 Media Asset、Stage Attempt 成本、Model Release
及批准 Benchmark 动态生成编辑链；Master 实际探测通过后，Worker 输出不可变质量报告与完整镜头清单。

最终成片、SRT/VTT 和中间 picture/audio master 都是不可变 Media Asset，可在后续 Delivery Manifest 中
引用；修改任何采用 Shot、TTS、stem、字幕或 output spec 会产生新的幂等键与 Job。
