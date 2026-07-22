# VTV 实施路线图

本文把 v3.2 技术方案转化为可提交、可验证的工程增量。每个增量完成后更新 `docs/PROJECT_PROGRESS.md`、运行相应测试、创建 Git 提交并同步远端。

## Phase 0：工程与规格基线

- 初始化 Git、远端与主分支
- 建立单仓库目录、环境约束、开发命令和 CI 基线
- 固化架构决策、里程碑、验收矩阵和进度记录

退出条件：新开发者能够理解范围、工具链和分阶段交付边界。

## Phase 1：基础平台（P1）

- 共享 Pydantic Schema 与生成的 TypeScript 类型
- FastAPI 控制 API：工作区、项目、集、上传、任务、审核
- PostgreSQL 核心实体、DAG、Outbox、lease、CAS 提交和迁移
- S3 兼容对象存储适配器与 multipart 协议
- 数据库驱动编排器和 Mock Worker
- React/Tauri Mac 控制端基础页面

退出条件：不含高级本土化模型时，可从多集登记跑通到 mock 合成的端到端流程。

## Phase 2：全剧分析（P2）

- ffprobe/镜头切分、代理文件和音轨提取
- ASR、VAD、词级对齐、说话人分离适配器
- 人物/场景/OCR/几何分析适配器
- Localization Bible、Anchor Pack、Continuity Snapshot
- 资产确认、release 锁定和依赖失效传播

退出条件：跨集角色、造型、场景、台词和几何状态可审核并锁定。

## Phase 3：自动生产（P3）

- A–F 可解释镜头路由与人工覆盖
- 人物、背景、联合编辑和完整重生 Adapter
- TTS、多层口型、音频恢复与混音
- 异构候选、preview-first、预算门控和成本台账

退出条件：单集可自动生成，失败项进入异常中心且支持单镜头返修。

## Phase 4：QC 与批量（P4）

- 技术、身份、时序、OCR、口型、音频和连续性 QC
- evaluator release、阈值校准和硬失败门禁
- Golden Dataset、模型准入、灰度、熔断与回滚
- 20+ 集批处理、交付包和 provenance manifest

退出条件：达到方案第 22 章 MVP 验收矩阵。

## Phase 5：研究工具完善（P5）

- Mac 签名/公证和发布
- 模型缓存、热更新、更多市场与语言
- C2PA 可选凭证、归档/删除/保留策略自动化
- 性能、成本和质量的持续优化

## 横切约束

- 状态权威在 PostgreSQL；对象权威在对象存储。
- Modal 调用 ID 不是业务任务 ID；HTTP 请求不等待长任务。
- 所有输出采用不可变 key；所有提交受 lease、state version、control version 和 deletion tombstone 条件保护。
- 自动执行必须通过模型访问、源媒体权利、人物/声线同意及项目策略门禁。
- 前沿模型先进入观察/候选状态，通过可复现、Golden Shots、稳定性和回滚测试后才可自动采用。
