# 项目进度

最后更新：2026-07-22

## 总览

| 阶段 | 状态 | 完成度 | 当前交付 |
|---|---|---:|---|
| Phase 0 工程与规格基线 | 已完成 | 100% | 仓库说明、路线图、环境与提交规范 |
| Phase 1 基础平台 | 验证中 | 99% | 基础平台功能完成；等待真实 Postgres/MinIO 全链验证 |
| Phase 2 全剧分析 | 进行中 | 18% | 媒体处理与 VAD/ASR/对齐/说话人 Adapter 契约 |
| Phase 3 自动生产 | 未开始 | 0% | — |
| Phase 4 QC 与批量 | 未开始 | 0% | — |
| Phase 5 研究工具完善 | 未开始 | 0% | — |

## 已完成

- [x] 读取 v3.2 最终技术方案，确认 24 章主体与附录定义的总体范围。
- [x] 确认技术主线：Tauri + React、FastAPI、PostgreSQL、S3 兼容对象存储、Modal。
- [x] 建立与原方案 P0–P5 对齐的实施路线图。
- [x] 建立 Python/Node 隔离规则、媒体与模型文件忽略规则。
- [x] 初始化 Git `main` 分支并配置 GitHub 私有远端。

## 当前进行

- [x] 建立 `uv` workspace 和项目长期 `.venv`。
- [x] 固化项目、预算、输出规格、Stage Job/Result 首批共享 Schema。
- [x] 实现项目创建/查询与异步分析任务提交/查询 API。
- [x] 验证工作区隔离、预算约束和 `202 + job_id + Location` 契约。
- [x] 实现首版 PostgreSQL 迁移及 13 个 SQLAlchemy 核心表模型。
- [x] 实现 DAG 依赖、Outbox、execution control、lease、tombstone 与 orphan 结构。
- [x] 固化 `FOR UPDATE SKIP LOCKED` 领取和 lease/state/control version 条件提交 SQL。
- [x] 固化 Stage Run 合法状态迁移并覆盖成功、失败、取消、失效路径测试。
- [x] 实现对象存储 Adapter 协议与无媒体代理的 multipart API。
- [x] 实现 32–128 MiB 分片、恢复查询、顺序/大小/SHA-256 完成校验。
- [x] 建立 npm workspace、React/Vite 控制端和 Tauri 2 macOS 壳。
- [x] 实现项目头、生产阶段轨、指标、剧集列表、异常队列及审核详情。
- [x] 验证开始分析、异常切换和标记处理交互；完成概念稿对照检查。
- [x] 实现异步 Repository 接口；配置 `VTV_DATABASE_URL` 时使用 PostgreSQL。
- [x] 项目创建事务写入 workspace、project、execution control 和 Outbox。
- [x] 分析请求事务写入 Job、六阶段 DAG、六条依赖边和 Outbox。
- [x] 实现调度领取、attempt lease、条件提交、失败记录、orphan 与下游解锁。
- [x] 建立 PostgreSQL/MinIO Compose 环境、迁移工具和 GitHub Actions CI。
- [x] 接入真实 S3/MinIO multipart Adapter、短期预签名 URL 和分片 SHA-256。
- [x] 将 upload session 持久化到 PostgreSQL，支持服务重启后的完成/查询。
- [x] 上传完成事务创建 Episode、Media Asset、ingest Job/Stage 和 Outbox。
- [x] 数据库提交失败时登记已完成对象为 orphan，等待生命周期清理。
- [x] 完成 ingest→proxy→shots→mock localize/render→QC→assemble→manifest DAG。
- [x] 调度器构造标准 StageJob、读取上游资产并登记 Worker 输出 Media Asset。
- [x] 提供 `vtv-orchestrator` 命令，一次运行队列直到空闲并设定阶段安全上限。
- [x] 新增项目、剧集和任务列表 API，并配置 Vite/Tauri CORS 边界。
- [x] Mac 客户端读取真实项目/剧集/Job，真实提交分析任务并显示 Job ID。
- [x] API 不可用时明确标记“离线演示”；空工作区明确标记“尚无项目”。
- [x] 实现 Tauri 本地媒体 Agent：文件选择、ffprobe 与 4 MiB 缓冲流式 SHA-256。
- [x] 实现逐分片 SHA-256/ETag checkpoint、会话复用、URL 重发和断点恢复。
- [x] Rust Agent 直接上传预签名 URL，完成后创建 Episode/Media Asset/ingest DAG。
- [x] 建立独立 `vtv-media` 包，封装 ffprobe、FFmpeg 超时执行与错误诊断。
- [x] 实现 H.264/AAC 审核代理、48 kHz PCM 音轨抽取和原子文件提交。
- [x] 实现场景分数镜头切分与最短镜头约束，输出连续镜头区间。
- [x] 实现 Media Worker 的 ingest 校验、代理生成和镜头检测 Stage 契约。
- [x] 使用即时合成的双场景音视频完成真实 FFmpeg 组件测试。
- [x] 固化 VAD、ASR/词级对齐、说话人分离 Protocol 与版本标识边界。
- [x] 固化音频分析时间区间、语言、置信度和音频时长范围不变量。
- [x] 实现确定性参考 Adapter 与统一 Audio Analysis Pipeline，支持无 GPU 合同测试。
- [ ] Docker Hub 恢复后执行真实 PostgreSQL + MinIO + Tauri 文件上传全链验收。

## 下一提交目标

`feat: add audio analysis stage worker`

下一步把音频抽取和 Audio Analysis Pipeline 接入标准 Stage Job/Result，持久化结构化转录资产与模型 release provenance。

## 决策日志

| 日期 | 决策 | 原因 |
|---|---|---|
| 2026-07-22 | 以数据库驱动编排为第一条工程主线 | 它承接幂等、断点续跑、取消、成本和追溯，是后续模型 Worker 的稳定边界。 |
| 2026-07-22 | 模型 Adapter 先实现协议与 Mock，再接真实权重 | 先验证业务流水线，避免模型下载、许可和 GPU 可用性阻塞平台开发。 |
| 2026-07-22 | 不把所有候选模型同时接入首轮 | 遵循方案附录建议，优先四组双路组合并保留稳定回退。 |

## 验证记录

| 日期 | 范围 | 结果 |
|---|---|---|
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 4 passed；存在 FastAPI TestClient 的上游弃用提示 |
| 2026-07-22 | SQLAlchemy metadata import | 13 tables loaded |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 15 passed；同一上游弃用提示 |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 17 passed；同一上游弃用提示 |
| 2026-07-22 | `npm run lint:mac` | 通过 |
| 2026-07-22 | `npm run build:mac` | 通过，Vite production bundle 已生成 |
| 2026-07-22 | `cargo check --offline` | 通过，Tauri 壳可编译 |
| 2026-07-22 | Playwright Chrome 1600×1000 | 主屏渲染及 3 条核心交互通过 |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 21 passed，1 个 PostgreSQL 测试因本机 Docker daemon 未启动而跳过 |
| 2026-07-22 | `npm run lint:mac && npm run build:mac` | 通过 |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 23 passed，1 个 PostgreSQL 测试因 Docker Hub 镜像拉取无响应而跳过 |
| 2026-07-22 | S3 Adapter 合约测试 | 预签名、multipart complete、逐分片 SHA-256 与 head 校验通过 |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 24 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | `npm run lint:mac && npm run build:mac` | 通过 |
| 2026-07-22 | FastAPI + Playwright 1600×1000 | 项目/剧集/Job 查询、CORS 预检和分析 202 提交联调通过 |
| 2026-07-22 | Rust SHA-256 单测 | 通过；与 `shasum -a 256` 测试向量交叉验证 |
| 2026-07-22 | `cargo check --offline && cargo test --offline` | 通过 |
| 2026-07-22 | Tauri debug application build | 通过，生成 `target/debug/vtv-mac-client` |
| 2026-07-22 | multipart resume API | 相同 SHA 会话复用、逐 part checkpoint 与完成清单匹配测试通过 |
| 2026-07-22 | `ruff check .` | 通过；媒体包、Worker 与组件测试均满足静态检查 |
| 2026-07-22 | FFmpeg 合成媒体组件测试 | 4 passed；覆盖探测、代理、音轨、镜头切分和 3 类 Stage 执行 |
| 2026-07-22 | `pytest` | 28 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | 音频分析 Adapter 合同测试 | 3 passed；覆盖确定性流水线、反向区间和越界区间拒绝 |
| 2026-07-22 | `pytest` | 31 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
