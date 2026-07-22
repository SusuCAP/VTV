# 视觉分析 Adapter 契约

视觉分析层把人物、场景、OCR 和画面几何拆为四个可独立替换的 Adapter，并由
`VisionAnalysisPipeline` 汇总为按媒体时间轴对齐的结果。该边界服务于后续跨集聚类、
Localization Bible、画面重绘路由和 QC，而不是绑定某个视觉模型。

## 统一坐标与时间

- 所有观察使用媒体起点的秒数，并且不得超出媒体总时长。
- 空间框采用 `[0, 1]` 归一化左上角坐标与宽高，必须完整落在画面内。
- 人物观察保留 observation ID、镜头内 track ID、可选 embedding 引用和人脸可见性。
- OCR 保留文本、script、空间区域与置信度，为字幕/招牌本土化及残留文字 QC 提供输入。
- 几何结果区分主体区域与保护区域，并用受控枚举描述相机运动。

当前确定性 Adapter 只负责合同和无模型链路验证；它不会被标记为生产模型。真实模型
必须暴露 release、通过 Golden Dataset 与许可门禁，embedding 也只以资产引用进入业务结果。

