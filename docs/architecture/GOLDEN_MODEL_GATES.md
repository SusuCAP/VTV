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

音频候选提供 Unicode NFKC/大小写/标点归一化后的多语言字符准确率，以及对匿名 cluster ID
做最优置换后的说话人时间重叠准确率。两项均输出 `[0,1]` 分数，可直接作为 Policy 的关键
指标；最多八名说话人的精确置换限制会显式报错，避免大场景评测悄悄退化为近似结果。

`run_audio_golden_dataset` 把固定音频 case 运行成可直接提交 benchmark API 的
`BenchmarkReleaseCreate`。执行前逐文件校验 SHA-256 和 ffprobe 时长（容差 50 ms），任何
Dataset 漂移都会终止整批，不能被误算成模型失败。推理异常则只把对应样本标记为 critical
failure 并记录异常类型，整批继续；成功样本采集 transcript/speaker 指标、端到端延迟和按
计算秒计价的成本。这样基础设施错误、数据污染与模型质量失败在审计上保持不同语义。

迁移 `0007_benchmark_releases.sql` 新增不可变 `benchmark_releases` 与逐样本
`benchmark_sample_results`。报告唯一身份由 model release、dataset 指纹、policy 指纹与权重
hash 组成；`model_releases.approved_benchmark_release_id` 只允许引用已落库报告。事务 API 在
进入 CANARY/ACTIVE 前验证引用报告已批准且归属同一 workspace/model release。

控制平面通过 `POST/GET /v1/model-releases/{release_id}/benchmarks` 提交与查询报告。提交事务
锁定 Model Release 并检查 state version，重新执行服务端判定，而不是信任客户端给出的
`approved`。报告及逐样本证据、Outbox 事件原子写入；通过时同事务采用该报告并递增 Model
Release state version，未通过报告仍保留用于审计但不会被采用。自动化切换同时检查状态机中的
引用和数据库中报告的 workspace、model release、approved 四项一致性，不能伪造外键绕过。
