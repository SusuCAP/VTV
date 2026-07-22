# 项目级合成领域模型

`PROJECT_SYNTHESIS` 将跨集分析结果组织为三类版本化资产：

- Localization Bible：目标市场角色名、地点名、词汇表、风格规则及视觉/声音约束。
- Anchor Pack：角色、服装、地点和声线的已选参考资产，并锁定对应 Bible 版本。
- Continuity Snapshot：逐集逐镜头记录人物服装、情绪、道具、地点和时间状态。

所有领域对象不可变，版本从 1 开始，状态为 `DRAFT`、`CONFIRMED` 或 `RELEASED`。
角色与地点 ID 在同一 Bible 内唯一；Anchor Pack 和 Continuity Snapshot 都显式引用
Bible ID 与版本，防止使用已经失效的语义约束。

当前 `DeterministicProjectSynthesizer` 从人物 track、场景和镜头几何构造可重复的候选草稿。
草稿锚点使用 `pending://`，只用于验证合成链路，必须经过资产选择和确认后才能发布。

`vtv-analysis-worker` 已实现 `PROJECT_SYNTHESIS` Stage。Worker 要求两份 JSON 输入并根据
强类型字段识别音频与视觉分析，拒绝重复、缺失或未知分析类型。输出
`project-synthesis.json`，合并所有上游模型 release，并追加项目合成器 release，使草稿
能够追溯到完整分析链。目标语言来自 Stage 参数，源语言默认采用 ASR 识别语言。

项目合成现支持任意数量 Episode：依靠输入资产的 `episode_id` 元数据配对每集音频和视觉
结果，跨集去重 track/scene，并为每集分别创建 Continuity Snapshot。任一 Episode 缺少
音频或视觉结果时整个 Stage 拒绝提交，避免产生部分项目 Bible。
