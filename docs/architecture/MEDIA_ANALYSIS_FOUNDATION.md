# 媒体分析基础层

本增量把 Phase 2 的第一段真实媒体处理能力放入独立 `vtv-media` 包，并通过
`vtv-media-worker` 接入既有 Stage Job/Result 契约。它不依赖 ComfyUI，也不把
FFmpeg 进程细节泄漏到控制 API 或编排器。

## 能力边界

- `probe_media`：调用 ffprobe，输出时长、格式、音视频流、分辨率和帧率等结构化元数据。
- `generate_proxy`：生成 H.264/AAC、`faststart` 的低分辨率审核代理文件。
- `extract_audio`：抽取 48 kHz 双声道 PCM WAV，作为后续 VAD、ASR 和混音的稳定输入。
- `detect_shots`：使用 FFmpeg scene score 提取候选切点，经过最短镜头约束后输出连续区间。
- Media Worker：处理 `INGEST_VALIDATE`、`PROXY_GENERATE`、`SHOT_DETECT`，并返回带 SHA-256 的不可变资产引用。

所有外部进程都以参数数组启动，不经过 shell；包含超时、退出码检查和 stderr
诊断。代理与音频先写随机临时文件，成功后原子替换目标，失败不留下半成品。

## 当前部署模式

当前 Worker 是可测试的本地文件执行模式，接受普通路径和 `file://` URI。生产环境接入
S3/MinIO 时，将在 Worker 边界增加输入下载与输出上传，不改变媒体算法接口或
Stage Result 契约。

## 验证

组件测试使用 FFmpeg 即时生成包含两段纯色画面和音轨的短视频，验证：

1. ffprobe 元数据解析；
2. 代理文件缩放与可播放性；
3. PCM 音轨抽取；
4. 镜头边界检测；
5. 三类 Stage Job 的标准结果与输出资产哈希。

