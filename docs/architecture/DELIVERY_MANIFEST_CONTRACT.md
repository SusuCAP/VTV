# 交付与 Provenance Manifest 契约

每个 Episode Delivery 使用 `vtv.delivery-manifest.v1` 不可变清单。清单指向 Media Asset，绝不覆盖对象；
`fingerprint` 对除生成时间外的规范 JSON 计算 SHA-256，因此相同输入、采用决策和编码结果具有稳定身份。

## 最小交付闭包

- 源视频、逐集 Master、至少一种 SRT/VTT 字幕；
- 质量报告与连续、无重叠、从 1 编号的镜头清单；
- 每个编辑 Stage 的输入/输出 SHA-256 与参数 SHA-256；
- 实际 Model Release、权重 SHA-256 和可用 seed；
- Artifact/Candidate/Delivery 人工批准证据及 state version；
- evaluator release、metric version、分数和 PASS/REVIEW 结论；
- 分阶段成本、Provider Usage、最终编码和可选 C2PA 状态。

Manifest 创建前执行硬门禁：任何 hard-failure QC、缺失必需交付角色、重复资产角色、镜头时间线
断裂、成本为负或最终 Master hash 不在编辑链输出中都会失败。该契约是下一步数据库 Delivery Release、
报告资产生成和下载 API 的稳定边界。
