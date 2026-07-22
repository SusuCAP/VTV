# 生产模型 Adapter 运行时

Analysis Worker 支持 `deterministic` 与 `remote` 两种运行模式，默认仍为确定性合同模式。
远程模式通过 multipart 直接上传已物化的音频/视频文件和 JSON 请求，不向模型服务发送其
无法解析的本地 file URI。

每个远程音频/视觉入口必须配置：

- HTTPS（或 localhost）endpoint；
- 不可变 model release；
- license record ID；
- `approved_for_automation=true`；
- 可选 bearer token 和超时。

任一门禁缺失时在网络调用前拒绝执行。响应必须通过 AudioAnalysis/VisionAnalysis 强类型
校验，且媒体时长与输入一致。错误信息不包含 bearer token 或远程响应正文。

`VTV_ALLOW_MODEL_FALLBACK` 默认为 false。只有显式开启时，网络/服务或响应错误才切换到
确定性 Adapter；许可或自动化批准失败绝不回退绕过。回退后 Worker 从 Pipeline 读取实际
release，因此 Stage Result 和 Domain Artifact provenance 记录 mock release，而不是失败的
远程 release。

相关环境变量以 `VTV_AUDIO_ANALYSIS_*`、`VTV_VISION_ANALYSIS_*` 为前缀，模式由
`VTV_ANALYSIS_ADAPTER_MODE=remote` 开启。

