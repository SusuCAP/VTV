# 生产视觉 Adapter

`vtv_analysis.production_vision` 为人物、场景、OCR 和画面几何提供统一的生产推理边界。首个可执行
bundle 使用 Qwen3-VL，一次读取视频和已声明的镜头区间，返回强类型 `VisionBackendOutput`；四个
领域 Adapter 共享同一缓存，因此同一个 Stage 不会重复执行四次模型推理。

模型采用惰性加载。本地合同测试不下载权重，只有 Registry 选中 `adapter_mode=qwen3_vl` 的
`VISION_ANALYSIS` Stage 才加载 `transformers` 和 `qwen-vl-utils`。输出必须是严格 JSON，且每条人物、
场景、OCR、几何观察必须完整落在一个已声明镜头内；远程 URI 必须先由 Worker S3 边界物化为本地
不可变文件。

## 发布与许可门禁

默认 release 标记为 `unapproved`，不能直接获得自动流量。每个具体权重必须在 Model Release
Registry 中单独完成许可审查、模型卡、Golden Benchmark 和 CANARY/ACTIVE 准入。Qwen3-VL 只是
首个 bundle；SAM、DINO 和 VGGT 等候选保持在 Adapter 边界外，只有商业用途、权重许可及
Golden Shots 达标后才可替换或组合。

## Golden 指标

`vtv_evaluation.vision_metrics` 提供与模型无关的门禁原语：

- `box_iou`：人物、主体和 OCR 框的归一化空间 IoU；
- `temporal_iou`：镜头内观察区间的时间 IoU；
- `label_f1`：大小写无关的场景标签集合 F1；
- `ocr_text_accuracy`：兼容中英文、全角字符和标点归一化的 OCR 字符准确率。

这些指标均输出 `[0,1]`，可直接写入现有 Benchmark Policy。下一层 Golden Shots runner 负责将
人工标注的不可变 hash、样本失败隔离、延迟和成本汇总为 benchmark API payload。
