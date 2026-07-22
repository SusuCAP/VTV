# 字幕、音频重混与逐集合成运行时

最终合成是确定性媒体工程路径，不交给生成模型。`vtv-assembly` 固化字幕、音轨、响度和输出编码契约，
`vtv-assemble-worker` 处理 `SUBTITLE_RENDER`、`AUDIO_MIX` 与 `ASSEMBLE_EPISODE` 三类 Stage。

## Picture Conform

`PICTURE_CONFORM` 是最终 mux 前的权威画面时间线。请求固定源集视频 hash/时长，以及按时间排序、互不
重叠的 adopted Shot replacements。Worker 对源片切出未修改区段，把每个采用候选严格裁到 Shot
区间并统一分辨率、SAR 和 fps，再用 FFmpeg concat 重建完整画面。重复候选、区间重叠、越过集时长、
候选短于 Shot 或最终时长漂移超过 50 ms 均硬失败。这样口型/渲染候选确实进入成片，而不是只存在于
Candidate 表中。

## 字幕

Subtitle Document 固定 locale、连续编号和非重叠时间码；非法区间、序号缺口和 NUL 字符在执行前拒绝。
Worker 以毫秒精度确定性输出 UTF-8 SRT/VTT。烧录字幕不假定 FFmpeg 编译了 libass：Worker 使用
Pillow 与可配置字体生成逐 cue 透明图层，再通过 FFmpeg `overlay + enable(t)` 合成。生产镜像应安装
Noto CJK，macOS 优先 Arial Unicode；缺失时回退 DejaVu/default 字体。

## 音频重混

Audio Mix Request 只接受已声明 hash 的不可变资产，并区分 DIALOGUE、MUSIC、EFFECTS、BACKGROUND：

- 采用 TTS 对白按时间线毫秒延迟，可配置距离增益与有限房间混响；
- MUSIC/EFFECTS/BACKGROUND 作为全长 stem，从零点开始并分别设置 gain；
- 所有输入重采样到配置采样率/声道后 `amix`；
- 使用平台 Loudness Preset 执行 integrated LUFS、true peak 和 LRA 归一化；
- 输出后再次用 FFmpeg 测量，LUFS 偏差超过 1 LU 或 true peak 超过 0.2 dB 立即硬失败；
- 输出时长与源集误差不得超过 50 ms。

输出 metadata 同时保存目标和实测响度，避免把 preset 配置伪装成测量证据。

## Episode Master

Episode Assembly Request 固定源视频、混音、字幕 hash、源时长、分辨率、帧率与 h264/h265/av1、
aac/opus 编码。FFmpeg 采用保持比例的 scale+pad、固定 fps、显式视频/音频 map 和 faststart。完成后
重新探测视频、音频流、尺寸、编码和时长；缺少音轨、尺寸漂移或 50 ms 以上时长漂移均不可提交。

五类 Assembly/Evidence Stage 已接入本地 Stage Router，并继续复用 S3 输入物化、逐文件 SHA-256 验证和不可变上传。
数据库门禁与四阶段 DAG 见
[`EPISODE_ASSEMBLY_WORKFLOW.md`](./EPISODE_ASSEMBLY_WORKFLOW.md)。
