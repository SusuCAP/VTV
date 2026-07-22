# Dialogue / Stem 分离

项目分析 DAG 在代理生成后新增 `AUDIO_STEM_SEPARATION`：

```text
INGEST_VALIDATE → PROXY_GENERATE → AUDIO_STEM_SEPARATION → ASR_ALIGN
                                  └→ SHOT_DETECT → VISION_ANALYSIS
```

`vtv-audio` 定义 `DIALOGUE`、`MUSIC`、`EFFECTS`、`BACKGROUND` 四种强类型 stem。结果必须包含
唯一 dialogue candidate，每种类型最多一个，且与源音频时长差不超过 50 ms。缺失 MUSIC 或
EFFECTS 必须保持缺失，禁止用复制源音频的方式伪造语义分离。

独立 `vtv-audio-worker` 执行 StageJob，输出带 `stem_kind` 和 model release metadata 的 WAV
资产以及 `AUDIO_STEMS` Domain Artifact。Scheduler 原样保留 Worker metadata，并追加受控的
attempt/stage/episode 字段；ASR 只接受恰好一个 `DIALOGUE` 资产，输入顺序不参与选择。

## Adapter 与许可边界

- `PassthroughDialogueAdapter` 仅用于无 GPU 合同链路，把标准化音频明确标为 dialogue
  candidate，release 名称包含 passthrough，不代表生产分离质量。
- `DemucsStemAdapter` 惰性加载 Demucs 4.1.0 `htdemucs`。vocals 映射为 DIALOGUE candidate，
  drums/bass/other 求和为 BACKGROUND；它不声称能完成对白/音乐/音效三路语义分离。
- Demucs 代码为 MIT，但权重 hash、训练数据适用性、对白泄漏率和 Golden 指标仍必须进入
  Model Registry 审批；默认 release 为 `unapproved`。

Registry 使用 `AUDIO_STEM_SEPARATION` model key 和 `adapter_mode=demucs` 配置候选。分析 DAG
创建时固化选中 release 外键；Modal 模式把 Stem、ASR、视觉和项目合成统一派发到计算平面。
本地开发模式保持 passthrough，避免下载权重。

## Golden 指标

每个 case 固定 source、dialogue reference、background reference 三个 SHA-256。评测读取
8/16/24/32-bit PCM WAV，统一多声道为 mono，并要求采样率和样本长度一致。准入同时检查：

- dialogue/background 与人工 reference 的波形方向保真；
- dialogue reference 在预测 background 中的归一化相关泄漏；
- 预测 dialogue + background 对 source 的归一化重建误差；
- critical failure、人工退回、P95 和单位合格输出秒成本等通用门禁。

这些轻量指标是自动硬门禁，不替代对白可懂度、音乐泵动、瞬态损伤和目标市场人工听审。
