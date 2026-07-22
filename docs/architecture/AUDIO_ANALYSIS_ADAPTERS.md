# 音频分析 Adapter 契约

`vtv-analysis` 为 VAD、ASR/词级对齐和说话人分离定义稳定的领域契约。业务层只依赖
这些 Protocol 与 Pydantic 输出，不依赖某个模型 SDK，从而允许本地、Modal 或其他
GPU 执行后端在不改变编排协议的情况下替换。

## 数据不变量

- 所有时间区间使用相对音频起点的秒数，并满足 `0 <= start < end <= duration`。
- 置信度统一限定在 `[0, 1]`。
- ASR 段必须携带语言，词级结果拥有独立时间区间与置信度。
- 说话人使用稳定业务 ID，不把模型内部聚类下标直接当作跨集角色 ID。
- 每个 Adapter 暴露 `model_release`，后续随 Stage Result 写入 provenance。

## 接入顺序

当前确定性 Adapter 仅用于合同测试和无 GPU 流水线验证，不代表生产识别质量。真实实现
将依次接入 VAD、ASR/对齐和 diarization，并使用同一组契约测试、Golden Dataset、模型
许可与 release 门禁进行准入。

