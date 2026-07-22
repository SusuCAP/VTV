# 逐集口型候选工作流

`POST /v1/projects/{project_id}/lipsync-jobs` 接收一组 Shot 生产请求。每个请求必须显式引用权威 Shot、
与 Shot 时长匹配的源镜头视频资产，以及已经通过 QC 和数据库 CAS 唯一采用的 TTS Render Variant。
请求规范 JSON 的 SHA-256 是 Job 幂等键。

## 创建门禁与路由

控制平面在事务中执行：

1. 锁定 Project/Execution Control，验证 Episode 与 Shot 归属；
2. 验证源资产属于项目、metadata 绑定该 Shot、为视频且 `duration_seconds` 与 Shot 时间码在 50 ms/2% 内一致；
3. 验证 TTS Variant 为其 Candidate Group 的唯一 `ADOPTED` 结果，输出为音频且属于同一 Episode；
4. 从 TTS Stage provenance 解析 rights release，并实时检查 `lipsync + market + language + commercial`；
5. 使用 `TieredLipSyncRouter` 固化 L0–L5、原因码和 4%/8% 时长阈值；
6. L0 创建 CPU passthrough Stage；L1–L5 分别从 `LIPSYNC_L1`…`LIPSYNC_L5` 选择 ACTIVE/CANARY
   且 `adapter_mode=remote_lipsync` 的 Model Release；
7. 每个 Shot 创建独立 `LIPSYNC` Candidate Group 与 READY `LIPSYNC_GENERATE` Stage Run；
8. Stage 参数显式固定源视频/采用音频 asset ID、hash、路由、rights state version、model release 和 seed。

对白时长只参与路由；输出视频时长必须匹配源镜头时长。这样半句对白位于较长 Shot 时不会被错误裁成对白长度。

## 执行与采用

Scheduler 只从同一 workspace/project 装载显式输入资产。Worker 回传时再次锁定授权；推理期间撤销会使
结果进入 `RIGHTS_BLOCKED` 和 orphan 登记。成功输出写入 Render Variant 后，LIPSYNC 候选必须完整
提交 technical integrity、identity consistency、temporal stability、structure integrity、lipsync
alignment 和 continuity 六项版本化 QC 证据。最终采用事务再次检查授权，并用 Candidate Group
state version CAS 保证唯一赢家。
