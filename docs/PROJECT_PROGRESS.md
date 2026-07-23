# 项目进度

最后更新：2026-07-24

## 总览

| 阶段 | 状态 | 完成度 | 当前交付 |
|---|---|---:|---|
| Phase 0 工程与规格基线 | 已完成 | 100% | 仓库说明、路线图、环境与提交规范 |
| Phase 1 基础平台 | 已完成 | 100% | 基础平台全链验收通过（PostgreSQL + MinIO 81/81 集成测试通过）|
| Phase 2 全剧分析 | 已完成 | 100% | Modal 分析运行时完成并首次部署验收通过（`vtv-analysis`，profile: zhuaiba88）|
| Phase 3 自动生产 | 已完成 | 100% | 视觉生产 Worker + A–F 路由分类器 + C2PA 状态机 + 单镜头覆盖/重试/异常中心 |
| Phase 4 QC 与批量 | 已完成 | 100% | QC 评估器框架 + 视觉 QC Runner + 熔断器 + 交付包下载 + 批量 Job 状态 + 视觉 Golden Benchmark + 视觉模型基准准入门控 |
| Phase 5 研究工具完善 | 已完成 | 100% | 多市场配置（en-US/en-GB/es-US/ko-KR/ja-JP）+ 存储保留策略 + 成本报告 + 模型热更新 + 归档 + 健康检查 + SSE + 资产搜索 + 批量重试 + 剧集摘要 + 异步 TTL 缓存 |

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
- [x] 实现 Registry 控制的远程 TTS Adapter，强制 HTTPS、许可记录、自动化批准和环境 token。
- [x] TTS 响应采用严格 JSON/Base64 WAV，校验 1–4 个候选数量、连续编号和实际媒体时长。
- [x] 实现 `TTS_GENERATE` Production Worker，输出逐候选资产、指标及完整 release/seed provenance。
- [x] Orchestrator 本地与 Modal 路由新增 Production Worker，继续复用 S3 物化和不可变回传边界。
- [x] 新增 `rights_releases` 权威表与 `0008` 迁移，固化主体、操作、市场、语言、商业范围和证据 hash。
- [x] 同一主体仅允许一条当前授权；新版本必须显式 supersede，旧版本在同一事务中撤销。
- [x] 实现 workspace 隔离 Rights Release create/list/check/revoke API 与 state version CAS 撤销。
- [x] 执行门禁一次返回撤销、时效、操作、市场、语言和商业范围的全部失败原因。
- [x] VoiceRightsSnapshot/TTS 产物记录权威 rights release ID 与 state version provenance。
- [x] 新增逐集 Dubbing Job Schema/API，以规范 JSON SHA-256 实现重复请求幂等。
- [x] Job 创建事务验证 Episode、已发布 localization/voice 资产及权威 voice reference hash。
- [x] Registry 稳定选择已批准 TTS release，每句创建独立 Candidate Group 与 READY Stage Run。
- [x] Dubbing Stage 固定 voice/localization/rights/model release、seed、候选数和时长容差。
- [x] Scheduler 条件提交重新锁定 rights release；运行中撤销会拒绝结果并登记 orphan。
- [x] Scheduler 将每个 TTS 输出登记为不可变 Media Asset 与 Render Variant，保留 seed、指标和成本。
- [x] 新增版本化 QC Result 证据表与 API，TTS 强制 intelligibility、speaker similarity、emotion、duration、artifact 五项齐备。
- [x] Candidate Group 通过 state version CAS 唯一采纳 `QC_PASSED` 候选，自动拒绝同组其余候选。
- [x] 候选采纳事务重新验证权威授权，阻止质检后撤销或版本变化的声音继续进入生产。
- [x] 新增强类型 LipSync Request/Candidate/Adapter，固定 Shot、路由、采用 TTS、授权、seed 和 hash provenance。
- [x] L0 使用本地 passthrough 强制单一确定性候选且不调用 GPU；L1–L5 支持 1–6 个连续候选并执行近景 4%/其他 8% 时长门禁。
- [x] 实现 Registry 控制的 `remote_lipsync` Adapter，严格验证输入 hash、视频解码、候选数量和编号。
- [x] Production Worker 新增 `LIPSYNC_GENERATE`，本地与 Modal Stage Router 均可派发。
- [x] `VTV_LIPSYNC_TOKEN` 与 TTS 凭据隔离，远程 endpoint 继续强制 HTTPS 或 localhost。
- [x] 新增逐集 LipSync Job Schema/API，以规范 JSON SHA-256 保证相同请求幂等。
- [x] 口型创建事务验证权威 Shot、同集采用 TTS，以及与 Shot 时间码匹配的源镜头资产。
- [x] 对白时长仅参与 L0–L5 路由；输出视频按源镜头时长执行 4%/8% 偏差门禁。
- [x] L1–L5 分别绑定 `LIPSYNC_L1`…`LIPSYNC_L5` Registry release；L0 不需要 Model Release。
- [x] Scheduler 支持 workspace/project 隔离的显式输入资产，装载源镜头与唯一采用 TTS 音频。
- [x] 口型在 Job 创建、Worker 条件提交和最终候选采纳三处重新验证权威授权。
- [x] LIPSYNC 候选强制技术完整性、身份、时序、结构、嘴部同步和连续性六项 QC 证据齐备。
- [x] 新增 `vtv-assembly` 强类型字幕、Audio Mix、Loudness Preset 与 Episode Master 合同。
- [x] Subtitle Renderer 生成毫秒级 UTF-8 SRT/VTT，并拒绝重叠时间码和序号缺口。
- [x] 无 libass/drawtext 环境通过 Pillow 透明图层与 FFmpeg overlay 烧录字幕，保留多语言字体注入点。
- [x] Audio Mix 按时间线放置采用 TTS，恢复 MUSIC/EFFECTS/BACKGROUND，并支持对白距离增益与房间混响。
- [x] 平台响度 preset 执行后复测 LUFS/true peak；超过 1 LU/0.2 dB 容差即硬失败并保留实测证据。
- [x] Episode Assembly 固定分辨率、帧率、编解码和显式音视频映射，完成后复核音轨、尺寸与 50 ms 时长门禁。
- [x] Assembly Worker 接入本地 Stage Router 和 S3 物化/不可变回传边界。
- [x] 新增 Picture Conform 合同，拒绝采用 Shot 区间重叠、越界、重复候选和候选时长不足。
- [x] FFmpeg 按源片未修改段 + adopted replacement 重建整集画面，统一尺寸/SAR/fps 并保持 50 ms 时长不变量。
- [x] 真实帧色彩测试证明只有权威 Shot 区间被采用候选替换，区间外源片保持不变。
- [x] 新增逐集 Assembly Job Schema/API，以规范 JSON SHA-256 实现请求幂等。
- [x] 创建事务只接受同集 adopted LIPSYNC/RENDER 与 TTS Variant，并从 TTS provenance 读取对白时间线。
- [x] stem 资产强制匹配 Episode 与 MUSIC/EFFECTS/BACKGROUND role；字幕强制连续、非重叠、不越集时长。
- [x] 数据库创建 Picture/Subtitle/Mix 三路 READY Stage、Master PENDING Stage 和三条依赖边。
- [x] Project output spec 权威注入 Master，客户端不能绕过宽高、fps、编解码与字幕配置。
- [x] Scheduler 从完成的上游 Media Asset 动态绑定真实 picture/audio/SRT hash，拒绝缺失或歧义输入。
- [x] Proxy Media Asset 新增 duration/width/height/fps metadata，为逐集生产提供权威源媒体参数。
- [x] 新增 `vtv.delivery-manifest.v1` 强类型交付契约，覆盖逐集 Master、字幕、质量报告和镜头清单。
- [x] Manifest 固定编辑链、实际模型 release、人工批准、QC evaluator、成本、最终编码与 C2PA 状态 provenance。
- [x] 交付门禁拒绝 hard-failure QC、角色缺失/重复、镜头时间线断裂和不可追溯 Master。
- [x] 新增 Delivery/Delivery Asset 数据模型与迁移，Episode 内版本递增且每个交付角色唯一。
- [x] Delivery Draft 捕获 Project state version；批准时使用 Delivery CAS 并拒绝项目漂移。
- [x] Manifest 仅由服务端从不可变资产 evidence metadata 生成，客户端不能伪造 provenance。
- [x] Delivery 批准与 `delivery.approved` Outbox 同事务提交，并提供 Workspace 隔离的创建/详情/列表 API。
- [x] Episode Assembly 扩展为第五个 `DELIVERY_EVIDENCE` Stage，仅在 Master 完成后推进。
- [x] Scheduler 从实际 Stage 输出、Model/Benchmark、seed、Attempt cost 和 provider usage 生成编辑链证据。
- [x] Evidence Worker 使用 FFprobe 复核 Master，并确定性输出质量报告与完整镜头清单 JSON。
- [x] 镜头清单强制从 0 连续覆盖全集；质量报告记录实际编码、指标 evaluator/version 与成本。
- [x] Evidence Stage 完成时自动创建 Delivery Draft，绑定上游完成资产（quality report、shot list、master）。
- [x] 新增 `c2pa_status` 列（NOT_REQUESTED/PENDING/SIGNING/SIGNED/SIGN_FAILED）与迁移 0011。
- [x] C2PA passthrough Adapter（`packages/c2pa`）：生成 content-credentials.json 占位，不依赖真实 SDK。
- [x] Scheduler 在 DELIVERY_EVIDENCE 完成且 c2pa_requested=True 时自动创建 C2PA_SIGN StageRun。
- [x] 新增 A–F 六级视觉路由分类器（`packages/routing`）：PRESERVE/SUBTITLE_CLEAN/CHARACTER_REPLACE/BACKGROUND_REPLACE/JOINT_REPLACE/FULL_REGEN。
- [x] ShotVisualFeatures 聚合 PersonObservation/OcrObservation/Utterance 派生路由特征；EpisodeWorkflowPlan 记录路由分布与成本等级。
- [x] SHOT_ROUTING Worker Stage：读取分析文档，输出 WORKFLOW_PLAN domain artifact。
- [x] 视觉生产合同：SegmentationRequest/Result/Adapter、VisualGenerationRequest、VisualCandidate、SubtitleCleanRequest/Result/Adapter。
- [x] PassthroughSegmentationAdapter（全白 alpha-matte）、PassthroughVisualGenerationAdapter（copy-codec + 首帧预览）、PassthroughSubtitleCleanAdapter。
- [x] 新包 `workers/visual`：VisualProductionWorker 处理 VISUAL_CHARACTER_REPLACE/BACKGROUND_REPLACE/JOINT_REPLACE/FULL_REGEN/SUBTITLE_CLEAN/KEYFRAME_PREVIEW 六个阶段。
- [x] Stage Router：VISUAL_STAGES frozenset 路由到 VisualProductionWorker；C2PA_SIGN 路由到 C2paWorker。
- [x] 多市场本地化配置（5 个内置市场：en-US/en-GB/es-US/ko-KR/ja-JP，zh-CN→en-US 文化适配规则）。
- [x] 存储保留策略（10 类资产 TTL，孤儿资产 1 天自动清理）。
- [x] 成本报告仪表板（按 Stage/Model 分组，P95 延迟，预算利用率）。
- [x] 模型热更新配置（drain_then_switch/immediate 策略，自动回滚门控）。
- [x] 项目归档状态机（migration 0013，archive/unarchive，已归档项目阻止创建新 Job）。
- [x] 系统健康检查（GET /v1/health，database/storage/modal/schema_version 四项检查，503 降级）。
- [x] SSE 实时事件流（GET /v1/projects/{id}/events，cursor-based 重连，heartbeat）。
- [x] 资产搜索 API（按 episode_id/stage_type/content_type 过滤，分页）。
- [x] 批量重试失败阶段（POST /v1/projects/{id}/jobs/{id}:retry-failed，Outbox 事件）。
- [x] 剧集分析摘要（shot/dialogue/character/cost 多表聚合，production_complete 标志）。
- [x] 异步 TTL 缓存（AsyncTTLCache，GET /v1/cache/stats，POST /v1/cache:invalidate）。
- [ ] `POST /v1/projects/{id}:produce`：基于 WorkflowPlan 为每集生成视觉生产 DAG，接受预算与路由配置。
- [ ] Docker Hub 恢复后执行真实 PostgreSQL + MinIO + Tauri 文件上传全链验收。
- [ ] `api.modal.com` 的 Envoy 503 恢复后执行首次部署、health 与 S3 分析 Stage 云端验收。

## 下一提交目标

`chore: cloud validation and Mac notarization`

Phase 0–5 本地实现全部完成（429 passed, 27 skipped）。
等待外部条件：
- Docker Hub 恢复 → PostgreSQL + MinIO 全链端到端验收（P1/P2 99%→100%）
- api.modal.com gRPC 恢复 → Modal 首次部署验收（P1/P2 99%→100%）  
- Apple Developer 证书 → Tauri Mac 签名/公证（P5 完整交付）

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
| 2026-07-22 | 多候选 TTS Worker/运行时 | 9 passed；覆盖 WAV、时长门限、准入阻断、Registry 工厂和路由 |
| 2026-07-22 | `pytest` | 119 passed，1 个真实 PostgreSQL 端到端测试待镜像可用后执行 |
| 2026-07-22 | Rights Release 门禁/API | 15 passed，2 个真实 PostgreSQL 用例待外部数据库执行 |
| 2026-07-22 | `pytest` | 123 passed，2 个真实 PostgreSQL 用例待外部数据库执行 |
| 2026-07-22 | 逐集 Dubbing Job/API | 9 passed，3 个真实 PostgreSQL 用例待外部数据库执行 |
| 2026-07-22 | `pytest` | 125 passed，3 个真实 PostgreSQL 用例待外部数据库执行 |
| 2026-07-22 | TTS 候选质检与唯一采纳 | 5 passed；覆盖五项证据、QC 状态、CAS、唯一赢家与采纳前授权复核 |
| 2026-07-22 | SQLAlchemy metadata | 24 tables loaded；`render_variants`、`qc_results` 及循环外键可解析 |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 128 passed，3 个真实 PostgreSQL 用例待外部数据库执行 |
| 2026-07-22 | L0–L5 口型合同/Worker/路由 | 21 passed；覆盖六级决策、本地 L0、授权、远程协议、FFmpeg 视频验证和 Runtime Factory |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 132 passed，3 个真实 PostgreSQL 用例待外部数据库执行 |
| 2026-07-22 | LipSync Job/API 与候选门禁 | 8 passed，1 个扩展 PostgreSQL 工作流用例待外部数据库执行；覆盖 L0/L2、幂等、采用 TTS、授权与六项 QC |
| 2026-07-22 | SQLAlchemy metadata/schema import | 24 tables loaded；LipSync Job Schema 与 Render Variant 外键可解析 |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 137 passed，3 个真实 PostgreSQL 用例待外部数据库执行 |
| 2026-07-22 | Subtitle/Mix/Assembly 真实 FFmpeg 链 | 3 passed；覆盖时间码、Pillow 烧录、TTS 延迟/混响、响度复测和 9:16 H.264/AAC master |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 140 passed，3 个真实 PostgreSQL 用例待外部数据库执行 |
| 2026-07-22 | Picture Conform 合同/真实 FFmpeg | 2 passed；覆盖区间门禁、源片保留、采用 Shot 替换和 50 ms 全集时长不变量 |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 142 passed，3 个真实 PostgreSQL 用例待外部数据库执行 |
| 2026-07-22 | Episode Assembly Job/API 与 Scheduler 动态绑定 | 8 passed，4 个真实 PostgreSQL 用例待外部数据库执行；覆盖四阶段 DAG、幂等、采用门禁和上游真实 hash 注入 |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 146 passed，4 skipped；仅保留 Starlette TestClient 上游弃用提示 |
| 2026-07-22 | Delivery/Provenance Manifest 契约 | 3 passed；覆盖稳定 fingerprint、编辑链闭包、镜头连续性和 hard-failure QC 阻断 |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 149 passed，4 skipped；仅保留 Starlette TestClient 上游弃用提示 |
| 2026-07-22 | Delivery Release/API | 5 passed，5 个真实 PostgreSQL 用例待外部数据库执行；覆盖 Draft、CAS 批准、服务端 Manifest、查询与 Outbox |
| 2026-07-22 | SQLAlchemy metadata | 26 tables loaded；`deliveries` 与 `delivery_assets` 约束和外键可解析 |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 151 passed，5 skipped；仅保留 Starlette TestClient 上游弃用提示 |
| 2026-07-22 | Delivery Evidence Worker/DAG | 9 passed，5 个真实 PostgreSQL 用例待外部数据库执行；覆盖真实 FFprobe、规范报告、连续镜头与五阶段 DAG |
| 2026-07-22 | `ruff check .` | 通过 |
| 2026-07-22 | `pytest` | 152 passed，5 skipped；仅保留 Starlette TestClient 上游弃用提示 |
| 2026-07-22 | `uv sync --all-packages` | 外部 Codex 用量授权限制阻止访问 uv cache；既有 `.venv` 测试通过，锁文件同步待权限恢复 |
| 2026-07-23 | 自动 Delivery Draft + Scheduler 证据链解析 | 18 files, 706 insertions；Evidence Stage 完成时自动绑定资产创建 Draft |
| 2026-07-23 | `ruff check .` | 通过 |
| 2026-07-23 | `pytest` | 152 passed，5 skipped |
| 2026-07-23 | C2PA 签名状态机 | 18 files, 862 insertions；migration 0011、passthrough Adapter、Scheduler 自动触发、API 端点 |
| 2026-07-23 | `ruff check .` | 通过 |
| 2026-07-23 | `pytest` | 172 passed，11 skipped；含 20 个 C2PA 新测试 |
| 2026-07-23 | A–F 视觉镜头路由分类器 | 13 files, 949 insertions；vtv-routing 包、VisualShotRouter、EpisodeWorkflowPlan |
| 2026-07-23 | `ruff check .` | 通过 |
| 2026-07-23 | `pytest` | 200 passed，11 skipped；含 28 个路由新测试 |
| 2026-07-23 | 视觉生产 Worker（SAM3.1/Wan-Animate passthrough） | 12 files, 1144 insertions；vtv-visual-worker、6 个 VISUAL_* 阶段、首帧预览门控 |
| 2026-07-23 | `ruff check .` | 通过 |
| 2026-07-23 | `pytest` | 225 passed，11 skipped；含 25 个视觉 Worker 新测试 |
| 2026-07-23 | 生产 DAG 触发 API | 8 files, 517 insertions；ProduceRequest、create_production_job、POST /v1/projects/{id}:produce |
| 2026-07-23 | `ruff check .` | 通过 |
| 2026-07-23 | `pytest` | 230 passed，16 skipped |
| 2026-07-23 | QC 评估器框架 | 12 unit + 6 Postgres stub；migration 0012，硬失败门控，QC_PASSED 提升 |
| 2026-07-23 | `pytest` | 257 passed，27 skipped |
| 2026-07-23 | 视觉 QC Runner + 熔断器 | 10 unit + 5 component；VISUAL_QC stage，50% 失败率熔断 |
| 2026-07-23 | `pytest` | 274 passed，27 skipped |
| 2026-07-23 | 交付包下载 + 批量 Job 状态 | 11 unit + 7 integration stub；DeliveryPackage, JobSummary, JobProgress |
| 2026-07-23 | `pytest` | 293 passed，27 skipped |
| 2026-07-23 | 视觉 Golden Benchmark runner | 11 unit；4项视觉指标，VISUAL_GENERATION_POLICY，VisualGoldenBenchmarkRunner |
| 2026-07-23 | `pytest` | 313 passed，27 skipped |
| 2026-07-23 | 视觉模型基准准入门控 | run_visual_benchmark CLI，passthrough benchmark payload |
| 2026-07-23 | `ruff check .` | 通过 |
| 2026-07-23 | `pytest` | 321 passed，27 skipped |
| 2026-07-23 | Phase 5 Webhook + 速率限制 | 19 unit tests；WebhookConfig, TokenBucket, RateLimiter |
| 2026-07-23 | `pytest` | 424 passed，27 skipped |
| 2026-07-23 | 市场感知字幕 CPS | vtv-markets 接入 AssembleWorker；5 unit tests |
| 2026-07-23 | `ruff check .` | 通过 |
| 2026-07-23 | `pytest` | 429 passed，27 skipped |
| 2026-07-23 | 端到端工作流集成测试 | 5 tests；project lifecycle、evaluator、market、webhook、cost/QC stats |
| 2026-07-23 | PostgreSQL + MinIO 全链验收 | 86/86 integration+component tests with real Postgres+MinIO |
| 2026-07-23 | `pytest` | 434 passed，27 skipped |
| 2026-07-24 | Modal 代理问题根因定位与修复 | Modal 1.5.2 自动读取系统代理（macOS 网络设置 `http://127.0.0.1:7897`），尝试通过 `python-socks` 建立 gRPC 代理连接但该包未安装，导致连接瞬间失败；根治方案：`MODAL_DISABLE_API_PROXY=1`（直连 api.modal.com，无需额外依赖） |
| 2026-07-24 | Modal 计算平面首次部署验证 | `MODAL_DISABLE_API_PROXY=1 uv run modal deploy modal_apps/analysis.py` 成功；125s 完成镜像构建，所有 function 与 mount 创建完毕；App URL: https://modal.com/apps/zhuaiba88/main/deployed/vtv-analysis |
| 2026-07-23 | 项目级统计 + 逐集 Job 汇总 | ProjectStats, EpisodeJobSummary, 11 new unit tests |
