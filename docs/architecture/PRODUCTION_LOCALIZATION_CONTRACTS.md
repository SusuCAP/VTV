# 自动生产本土化契约

`vtv-production` 固化 Phase 3 中不可随模型替换而变化的业务边界：逐句本土化、声音授权、TTS
候选和口型分层路由。模型实现可以通过 Adapter 替换，但时间码、release provenance、授权快照、
候选编号与路由原因码必须保持稳定。

## 台词与配音

- `Utterance` 保留源语言、人物、原文、情绪和精确时间区间；
- `LocalizedUtterance` 显式绑定目标语言、市场和不可变 localization release；
- `VoiceRelease` 绑定参考素材 hash、模型 release 和执行时 rights release 快照；
- `TtsRequest` 在推理前检查人物、语言、市场、商业范围、撤销/有效状态和 `voice_clone` 操作；
- 单句支持 1–4 个候选，并固定 seed、速度、情绪、音频 hash 和实际模型 release。

`ReviewedLocalizationAdapter` 只消费外部已审校翻译映射，不声称自己具备翻译能力。机器翻译
Adapter 接入后仍须输出同一契约，并由目标市场母语复核与 Golden Dataset 决定能否自动采用。

## 口型分层

`TieredLipSyncRouter` 根据嘴部可见性、人脸画面占比、遮挡、全身可见、对白长度和原表演是否
可复用，在 L0–L5 之间作可解释选择：不处理、快速嘴部修改、保留原片、生成式脸部、全身表演、
完整重生。近景目标语音时长偏差限制为 4%，其他镜头为 8%。

路由只选择能力层级，不绕过 Model Release、Golden Benchmark、rights release 或最终 QC 门禁。

## TTS Worker

`vtv-production-worker` 的 `TTS_GENERATE` Stage 只接受 Registry 选择的 `remote_tts` release。endpoint
必须为 HTTPS 或 localhost，license 和 automation approval 缺一不可，bearer token 仅从
`VTV_TTS_TOKEN` 注入。

远程服务返回 1–4 个严格 JSON 候选及 Base64 WAV。Worker 校验候选数量、连续 variant 编号、
实际媒体时长、文件 SHA-256 和镜头路由时长门限，再输出独立 `VariantResult` 与
`TTS_CANDIDATES` Domain Artifact。每个候选保留 seed、速度、情绪、voice/localization/rights/model
release provenance，可供后续 QC 和 selection stage 采用。
