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

