# Golden Dataset 与模型发布门禁

`vtv-evaluation` 把方案 17.5、17.6 和 21.4 的模型准入伪代码实现为可执行、不可变的领域
合同。Dataset 固化源资产 hash、标注 release、时长、标签和关键样本；Policy 固化全部批准
阈值。两者使用键排序、标签排序的规范 JSON 生成 SHA-256 指纹，避免环境或字典顺序改变
实验身份。

每个 dataset sample 必须且只能提交一份结果，额外、遗漏或重复结果全部拒绝。报告同时聚合：

- technical access、rollback、reproducibility 与 calibration 四个前置硬门禁；
- 最小样本量、critical failure rate 与 human reject rate；
- 任一关键样本的 critical failure（不允许被总体平均稀释）；
- 每个关键指标的均值、样本量和正态近似置信下界；
- 全部执行成本除以合格输出秒数，以及 nearest-rank P95 延迟。

只有所有门禁同时通过时 `approved=true`。判定器不短路，`failed_gates` 会列出一次评测中的
全部失败原因，便于修复、复测和审批审计。没有合格输出时成本门禁必然失败；指标缺失不会
被当作零分静默处理，而会生成独立的 `METRIC_MISSING` 原因。

当前模块是纯领域层，不直接修改 Model Release 状态。下一增量把报告持久化为不可变
benchmark release，并要求 Registry 在进入 CANARY 前引用一份已批准报告。
