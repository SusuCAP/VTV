# 项目进度

最后更新：2026-07-22

## 总览

| 阶段 | 状态 | 完成度 | 当前交付 |
|---|---|---:|---|
| Phase 0 工程与规格基线 | 已完成 | 100% | 仓库说明、路线图、环境与提交规范 |
| Phase 1 基础平台 | 验证中 | 99% | 基础平台功能完成；等待真实 Postgres/MinIO 全链验证 |
| Phase 2 全剧分析 | 验证中 | 99% | Modal 分析运行时完成；等待 API 网络恢复后部署验收 |
| Phase 3 自动生产 | 进行中 | 10% | 本土化、声音授权、TTS 候选与 L0–L5 口型路由契约 |
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
- [x] 扩展 ffprobe 媒体探测以接受纯音频，同时保留视频摄取的严格校验默认值。
- [x] 实现 `ASR_ALIGN` Worker：音频规范化、结构化转录、词级时间戳和说话人区间输出。
- [x] 在结果资产和 Stage Result 中双写 VAD/ASR/diarization 模型 release provenance。
- [x] 固化人物 observation/track、场景、OCR 和画面几何的可替换 Adapter 契约。
- [x] 统一视觉观察时间轴与 `[0,1]` 空间坐标，拒绝媒体越界和画框溢出。
- [x] 保留 embedding 资产引用、人脸可见性、OCR script、主体/保护区域与相机运动字段。
- [x] 实现四类确定性视觉 Adapter 和聚合 Pipeline，支持无模型合同验证。
- [x] 修正分析 DAG，使 `VISION_ANALYSIS` 同时消费代理视频和镜头清单。
- [x] 实现 `VISION_ANALYSIS` Worker，严格校验媒体类型、镜头连续性和时长覆盖。
- [x] 输出人物、场景、OCR、几何结果，并记录四类模型 release provenance。
- [x] 固化 Localization Bible、Anchor Pack、Continuity Snapshot 的不可变版本化契约。
- [x] 强制 Bible 内角色/地点 ID 唯一，并让 Anchor/Continuity 显式锁定 Bible 版本。
- [x] 实现确定性项目合成器，从 track、scene 与镜头几何生成可审核草稿。
- [x] 使用 `pending://` 明确区分候选锚点与已确认生产资产。
- [x] 实现 `PROJECT_SYNTHESIS` Worker，强类型识别音频/视觉分析并拒绝缺失或重复输入。
- [x] 合并音频、视觉模型 release，并追加项目合成器 release 形成完整 provenance。
- [x] 输出版本关联的 Bible、Anchor Pack、Continuity Snapshot 可审核草稿。
- [x] 新增 Artifact Release 与 Release Dependency 数据库模型及 `0004` 迁移。
- [x] 实现 `DRAFT→CONFIRMED→RELEASED` 状态机与 state version CAS 校验。
- [x] 发布门禁要求全部直接依赖已发布，阻止未确认或 stale 上游进入生产。
- [x] 实现沿依赖图传递 stale，支持分叉、汇合及异常依赖环。
- [x] 实现 Artifact Release PostgreSQL 事务 Repository 与 workspace/project 隔离。
- [x] 实现 release 创建/列表、确认、发布、显式失效 FastAPI 路由及强类型 Schema。
- [x] 每次创建、确认、发布和失效均在业务事务内写入 Outbox 事件。
- [x] 创建 superseding 版本时自动失效旧版本及全部下游，消除客户端竞态窗口。
- [x] API 将状态错误、依赖门禁和 CAS 冲突稳定映射为 HTTP 409。
- [x] 项目分析按每个已上传 Episode 展开 ingest/proxy/shots/ASR/vision 五阶段链。
- [x] 单一 `PROJECT_SYNTHESIS` 依赖所有集的 ASR 和视觉结果；加入 Stem 后总阶段数为 `6N+1`。
- [x] 空项目分析返回 409，阻止创建没有源资产且无法执行的 DAG。
- [x] Stage 输出资产透传 episode/stage 元数据，项目合成按集严格配对输入。
- [x] 合成器跨集合并 track/scene，并生成逐集 Continuity Snapshot 与异构 release provenance。
- [x] 编排器按 stage type 路由 Media Worker、Analysis Worker 与剩余 Mock Worker。
- [x] 本地具体 Worker 使用隔离 `--work-root`，输出不可混淆的 file URI。
- [x] Worker 异常转换为标准 `EXECUTION_FAILED`，防止异常穿透导致编排进程退出。
- [x] CLI 默认真实本地路由，同时保留显式 `--worker-mode mock` 合同测试模式。
- [x] 实现 Worker S3/MinIO 输入流式物化、临时文件和原子完成。
- [x] 下载同时校验数据库声明的大小与 SHA-256，失败不保留部分文件。
- [x] Worker 输出上传前复核 Stage Result 大小/哈希，拒绝虚假或损坏输出。
- [x] 输出采用 stage/variant/content hash 不可变 key、checksum metadata 与条件写。
- [x] 编排器读取统一 `VTV_S3_*` 配置，未配置时对 S3 URI 明确失败。
- [x] 新增 `analysis_documents` JSONB 权威投影表、GIN 索引及 `0005` 迁移。
- [x] Worker 返回强类型 Domain Artifact，覆盖 probe、shots、audio、vision 与项目合成资产。
- [x] Scheduler 仅在条件提交成功时写分析文档、Media Asset 和 Outbox，同事务原子完成。
- [x] 项目合成自动创建 Bible→Anchor→Continuity 三类 DRAFT Release 及依赖。
- [x] 重分析预分配下一 Release 版本，并在 Worker JSON 与提交事务两侧校验一致性。
- [x] 新版本自动 supersede 同类型旧版本并传递 stale 旧下游。
- [x] 新增 analysis documents 查询 API，支持 project/episode/type 过滤。
- [x] 实现音频/视觉远程推理 multipart 传输与强类型响应/媒体时长校验。
- [x] 远程执行要求 endpoint、release、license ID 与 automation approval 四项门禁。
- [x] endpoint 强制 HTTPS 或 localhost，远程错误不泄漏 token/响应正文。
- [x] 模型回退默认关闭；仅显式开启且发生远程服务错误时使用确定性 Adapter。
- [x] 回退后 provenance 记录实际 fallback release，许可/批准失败不可绕过。
- [x] 新增 workspace 隔离 Model Release Registry 与 `0006` 迁移。
- [x] 固化 license REVIEW/APPROVED/REJECTED 与 automation OBSERVE/CANARY/ACTIVE/DISABLED。
- [x] CANARY 强制 1–99%、ACTIVE 强制 100%、无流量状态强制 0%。
- [x] 自动流量要求已批准许可、model card 与安全 endpoint，并受 state version CAS 保护。
- [x] `stage_runs.model_release_id` 升级为 Model Release 外键。
- [x] 实现 Model Release 创建/查询、许可审批与自动化切换 API。
- [x] 每个模型键允许一个 ACTIVE 基线与一个 CANARY，按 Job 稳定散列灰度并自动回落基线。
- [x] CANARY 提升为 ACTIVE 时同事务关闭旧基线，所有审批/切换继续使用 state version CAS。
- [x] 分析 DAG 固化选中的 Model Release 外键，并将非敏感运行参数注入 StageJob。
- [x] Analysis Worker 读取 Stage 注入配置构造远程 Adapter，bearer token 始终仅来自环境。
- [x] 新增 Modal `vtv-analysis` App、固定依赖镜像、health 与强类型分析 Stage 函数。
- [x] Modal 函数复用 S3 物化/校验/不可变回传边界，密钥仅允许由 Modal Secret 注入。
- [x] 编排 CLI 新增 `--worker-mode modal`，仅远程派发分析阶段并校验返回 identity。
- [x] Modal 网络/协议异常转换为可重试 StageResult，数据库业务 ID 不依赖平台调用 ID。
- [x] 新增独立 `vtv-evaluation` workspace 包，固化 Golden Dataset、样本与阈值 Policy。
- [x] Dataset/Policy 以规范 JSON 生成不可变 SHA-256 指纹，固定标注和批准阈值版本。
- [x] 发布判定覆盖技术访问、复现、回滚、校准、样本量、硬失败和人工退回门禁。
- [x] 关键指标以置信下界而非均值准入，关键样本单次失败不可被总体平均掩盖。
- [x] 聚合单位合格输出成本与 nearest-rank P95；单次报告返回全部失败原因且不短路。
- [x] 新增不可变 benchmark release/逐样本结果表及 `0007` 迁移，固化评测完整证据。
- [x] Model Release 新增 approved benchmark 外键，为 CANARY/ACTIVE 数据库门禁建立引用边界。
- [x] 实现 benchmark 提交/查询 API，服务端重算报告并原子持久化逐样本证据与 Outbox。
- [x] 通过报告自动采用并递增 Model Release state version；失败报告保留审计但不改变准入状态。
- [x] CANARY/ACTIVE 同时验证报告归属 workspace/model release 且 approved，阻止伪造引用绕过。
- [x] 实现 faster-whisper VAD/Whisper 词级 ASR 与 pyannote community-1 生产 Adapter。
- [x] 模型依赖惰性加载，本地合同测试不下载权重；gated pyannote 权重强制从环境读取 token。
- [x] Registry `local_models` bundle 可注入三个不可变子 release，并继续受 Golden 报告门禁。
- [x] Modal 分析镜像升级为 L4/4 CPU/16 GiB，锁定 faster-whisper 1.2.1 与 pyannote.audio 4.0.7。
- [x] 新增多语言 transcript accuracy 与匿名 speaker cluster 最优映射重叠指标。
- [x] 实现音频 Golden 批处理 runner，直接生成 benchmark API 的强类型提交对象。
- [x] 每个 Golden 源文件执行 SHA-256 与 50 ms 时长漂移门禁，数据污染不计为模型失败。
- [x] 单样本推理失败隔离并记录异常类型，整批继续采集指标、延迟与按计算秒成本。
- [x] 新增 `vtv-audio` 领域包与独立 Audio Worker，固化四类 stem 和 50 ms 时长不变量。
- [x] 分析 DAG 新增 `AUDIO_STEM_SEPARATION`，ASR 改为只消费唯一 DIALOGUE stem。
- [x] 实现 passthrough 合同 Adapter 与惰性 Demucs 4.1.0 候选 Adapter，不伪造 MUSIC/EFFECTS。
- [x] Scheduler 保留 Worker 输出 metadata，使 stem kind/model release 可跨数据库边界传递。
- [x] Registry 新增 Stem 模型选择注入；Modal 模式把 Stem Stage 一并派发到 L4 计算平面。
- [x] Golden Sample 新增有序 reference SHA-256，标注音轨变更会生成新的 Dataset 指纹。
- [x] 实现无额外依赖的 PCM WAV 解码，覆盖 8/16/24/32-bit 与多声道 mono 聚合。
- [x] 实现对白/背景保真、对白泄漏控制和源音频重建准确率四项 Stem Golden 指标。
- [x] Stem runner 生成 benchmark API payload，并区分 reference 污染与单样本模型失败。
- [x] 实现 Qwen3-VL 惰性生产视觉 backend，一次推理生成强类型人物、场景、OCR 与画面几何结果。
- [x] 四类视觉 Adapter 共享 Stage 内缓存，并强制每条观察完整落入已声明镜头区间。
- [x] Registry `qwen3_vl` bundle 注入具体模型 release；未批准权重继续由许可与 Golden 报告门禁阻止流量。
- [x] Modal L4 镜像锁定 transformers 5.14.1、qwen-vl-utils 0.0.14 与 accelerate 1.14.0。
- [x] 新增框 IoU、时间段 IoU、场景标签 F1 与多语言 OCR 字符准确率四项 Golden Shots 指标。
- [x] 实现视觉 Golden Shots runner，校验源视频、规范标注 hash 与时长后生成 benchmark API payload。
- [x] Runner 聚合人物/几何框、场景时间与标签、OCR 五项分数，并隔离单样本推理失败。
- [x] 新增 `vtv-production` 领域包，固化逐句本土化、声音授权、TTS 请求与候选契约。
- [x] TTS 请求在推理前校验人物、语言、市场、商业范围、有效状态和 voice_clone 操作授权。
- [x] 固化每句 1–4 个候选及 voice/localization/model release、seed、速度、情绪和音频 hash provenance。
- [x] 实现 L0–L5 可解释口型路由，近景采用 4% 时长偏差、其他镜头采用 8% 门限。
- [ ] Docker Hub 恢复后执行真实 PostgreSQL + MinIO + Tauri 文件上传全链验收。
- [ ] `api.modal.com` 的 Envoy 503 恢复后执行首次部署、health 与 S3 分析 Stage 云端验收。

## 下一提交目标

`feat: add production dubbing worker`

下一步实现可执行 TTS Adapter、逐句多候选 Audio Worker、时长/音频完整性门禁和 Registry/Modal
路由；同时在 Modal API 网络恢复后补跑云端验收。

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
| 2026-07-22 | ASR_ALIGN Worker 组件测试 | 1 passed；真实 FFmpeg 合成 WAV，校验结构化结果与模型 provenance |
| 2026-07-22 | `pytest` | 32 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | 视觉分析 Adapter 合同测试 | 3 passed；覆盖聚合输出、空间框溢出和媒体时间越界拒绝 |
| 2026-07-22 | `pytest` | 35 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | VISION_ANALYSIS Worker 组件测试 | 1 passed；真实合成视频与连续镜头清单，校验视觉结果及 release |
| 2026-07-22 | `pytest` | 36 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | 项目合成领域测试 | 2 passed；覆盖版本关联草稿与重复角色 ID 拒绝 |
| 2026-07-22 | `pytest` | 38 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | PROJECT_SYNTHESIS Worker 测试 | 1 passed；校验强类型输入、草稿输出与跨阶段 provenance 合并 |
| 2026-07-22 | `pytest` | 39 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Artifact Release 状态机测试 | 3 passed；覆盖 CAS 确认/发布、依赖门禁和循环图传递失效 |
| 2026-07-22 | `pytest` | 42 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Artifact Release API 集成测试 | 3 passed；覆盖发布链、CAS 冲突及 supersede 自动传递失效 |
| 2026-07-22 | `pytest` | 45 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | 多集分析 DAG 与汇聚测试 | 通过；两集当前生成 13 stages、空集拒绝、分析资产按集配对 |
| 2026-07-22 | `pytest` | 47 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Stage Router 测试 | 2 passed；覆盖三路分发、本地输出隔离和异常标准化 |
| 2026-07-22 | `pytest` | 49 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | S3 Worker I/O 与 Router 合同测试 | 8 passed；覆盖传输、清理、幂等条件写、S3 物化/回传及虚假输出拒绝 |
| 2026-07-22 | `pytest` | 54 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Domain Artifact/Release 投影测试 | 通过；覆盖 8 类文档、三类 release 依赖及跨版本 Bible/Anchor 锁定 |
| 2026-07-22 | SQLAlchemy metadata | 18 tables loaded，包含 `analysis_documents` |
| 2026-07-22 | `pytest` | 55 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | 生产模型运行时测试 | 4 passed；覆盖批准门禁、强类型响应、实际回退 release 与缺失配置拒绝 |
| 2026-07-22 | `pytest` | 59 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Model Release 准入状态机 | 4 passed；覆盖许可门禁、canary→active 与非法流量范围 |
| 2026-07-22 | SQLAlchemy metadata | 19 tables loaded，`stage_runs.model_release_id` 具备外键 |
| 2026-07-22 | `pytest` | 63 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Model Release API/灰度选择 | 12 passed；覆盖审批 CAS、ACTIVE+CANARY、稳定分流及 Stage 注入 |
| 2026-07-22 | `pytest` | 67 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Modal Executor/Router 聚焦测试 | 6 passed；覆盖强类型回包、identity 拒绝与三路本地路由 |
| 2026-07-22 | Modal CLI/profile | 1.5.2 安装于项目 `.venv`；`zhuaiba88` profile 已激活 |
| 2026-07-22 | Modal 首次部署 | 阻塞于 `api.modal.com` HTTP 503；官方状态正常，本机代理/直连均复现 |
| 2026-07-22 | `pytest` | 69 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Golden Dataset 发布门禁 | 4 passed；覆盖完整批准、多门禁失败、样本完整性与不可变配置 |
| 2026-07-22 | `pytest` | 73 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | SQLAlchemy metadata | 21 tables loaded；Model Release approved benchmark 外键可解析 |
| 2026-07-22 | Benchmark/Registry 准入闭环 | 12 passed；覆盖服务端重算、采用、失败审计与自动化拒绝 |
| 2026-07-22 | `pytest` | 74 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | 生产音频 Adapter/Golden 指标 | 14 passed；覆盖惰性 bundle、时间边界、token 门禁与说话人映射 |
| 2026-07-22 | `pytest` | 83 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | 音频 Golden runner | 3 passed；覆盖强类型提交、模型失败隔离、源 hash 与时长漂移拒绝 |
| 2026-07-22 | `pytest` | 86 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Stem/DAG/Audio Worker 聚焦测试 | 13 passed；覆盖 stem 不变量、Demucs 映射、真实 FFmpeg Worker 与路由 |
| 2026-07-22 | `pytest` | 90 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Stem Golden 指标/runner | 6 passed；覆盖 PCM、四项指标、批准 payload、失败隔离与 reference 漂移 |
| 2026-07-22 | `pytest` | 96 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | 生产视觉 Adapter/Golden 指标 | 15 passed；覆盖共享单次推理、镜头边界、Registry bundle 与四项指标 |
| 2026-07-22 | `pytest` | 104 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | 视觉 Golden Shots runner | 2 passed；覆盖完整 payload、五项满分和标注 hash 漂移拒绝 |
| 2026-07-22 | `pytest` | 106 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Phase 3 本土化领域契约 | 8 passed；覆盖声音授权阻断、release 绑定与 L0–L5 全路由 |
| 2026-07-22 | `pytest` | 114 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
