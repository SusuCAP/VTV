# L0–L5 口型生产运行时

口型生产使用 `TieredLipSyncRouter` 的可解释决策作为不可变输入，不允许 Worker 自行改变层级。路由与
最终方案一致：L0 不处理，L1 快速嘴部修改，L2 保留原片表演，L3 生成式脸部，L4 全身表演，L5
完整说话镜头重生。近景最大时长偏差为 4%，其他镜头为 8%。

## 强类型请求

`LipSyncRequest` 固定以下 provenance：

- Shot 特征、L0–L5 决策、原因码和路由时长阈值；
- 源视频 SHA-256/时长、唯一采用的 TTS Variant ID 与音频 SHA-256；
- rights release ID/state version、目标语言、市场和商业范围；
- seed 与 1–6 个候选上限。

请求构造时单独要求 `lipsync` 操作授权。只有 `voice_clone` 授权不足以执行口型；L0 也保留授权与
来源证据，通过本地 `lipsync-passthrough@1` 复制源镜头并强制只产生一个确定性候选，不调用 GPU。

## Worker 与远程边界

`LIPSYNC_GENERATE` 必须消费且仅消费一个视频资产和一个已采用 TTS 音频资产。Production Worker
在推理前核对二者 hash；L1–L5 的 Model Release 必须由 Registry 批准并显式声明
`adapter_mode=remote_lipsync`。Bearer token 只从 `VTV_LIPSYNC_TOKEN` 注入，与 TTS 凭据隔离。

远程响应采用严格 JSON，必须返回与请求一致的 1–6 个连续编号候选。Worker 对每个视频执行解码探测、
SHA-256 和时长门禁，并输出模型 release、seed、层级、TTS Variant 与授权版本 provenance。候选仍需
进入 Render Variant/QC/唯一采纳流程，不能因 Worker 成功而自动成为业务结果。

数据库 Job、资产门禁和三次授权复核见
[`EPISODE_LIPSYNC_WORKFLOW.md`](./EPISODE_LIPSYNC_WORKFLOW.md)。
