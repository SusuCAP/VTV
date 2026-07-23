<div align="center">

# VTV — 国产短剧海外本土化自动生产平台

**Automated localization pipeline for Chinese short dramas targeting overseas markets**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/SusuCAP/VTV?style=social)](https://github.com/SusuCAP/VTV/stargazers)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-434%20passed-brightgreen)](docs/PROJECT_PROGRESS.md)
[![Modal](https://img.shields.io/badge/Modal-deployed-success)](https://modal.com/apps/zhuaiba88/main/deployed/vtv-analysis)
[![Docs](https://img.shields.io/badge/spec-v3.2-informational)](docs/PROJECT_PROGRESS.md)

[架构](#architecture) · [业务流程](#pipeline) · [功能矩阵](#features) · [快速开始](#quickstart) · [贡献](#contributing) · [许可证](#license)

</div>

---

VTV 将一套多集国产短剧自动改造为面向欧美市场的版本。系统以 Mac 控制端驱动，通过 FastAPI 控制平面和数据库驱动的 DAG 调度器，将每个镜头路由到 Modal 云端 CPU/GPU Worker，最终逐集输出本土化成片、字幕与质量报告。

> 设计依据：《国产短剧海外本土化自动生产平台——完整技术设计方案（非 ComfyUI）》v3.2，2026-07-22。  
> 当前状态：**P0–P5 全部完成**；Modal 计算平面已验证部署（2026-07-24）。详见 [项目进度](docs/PROJECT_PROGRESS.md)。

---

## Architecture

```mermaid
graph TB
    subgraph Mac["🖥️ Mac Control Client (Tauri 2 + React)"]
        UI["Project / Episode / Exception UI"]
        Agent["Rust Sidecar — ffprobe · SHA-256 · Multipart Upload"]
    end

    subgraph API["☁️ Control Plane (FastAPI + PostgreSQL)"]
        REST["REST API  50+ routes  202 + job_id"]
        Sched["DB-driven DAG Scheduler\nFOR UPDATE SKIP LOCKED · lease · CAS"]
        DB[(PostgreSQL\n26 tables · 13 migrations)]
        Outbox["Transactional Outbox\nSSE · Webhook · Alert"]
    end

    subgraph Store["🗄️ Storage Layer"]
        S3["S3 / MinIO\nOriginal · Proxy · Output · Manifest"]
        Volume["Modal Volume v2\nModel Weights (read-only)"]
    end

    subgraph Modal["⚡ Modal Compute Plane"]
        direction TB
        AnalysisApp["vtv-analysis (deployed)\nffprobe · ASR · Vision · Synthesis"]
        AudioWorker["audio-worker\nStem Separation · TTS · Mix"]
        VisualWorker["visual-worker\nSAM3.1 · Wan-Animate passthrough\nRoute C/D/E/F"]
        AssembleWorker["assemble-worker\nSubtitle · FFmpeg · Conform · Delivery"]
        QCWorker["qc-worker\nEvaluator Release · Circuit Breaker"]
    end

    subgraph Packages["📦 Shared Packages"]
        Schemas["vtv-schemas · vtv-db · vtv-storage"]
        Domain["vtv-routing · vtv-evaluation · vtv-markets"]
        Workers["vtv-analysis-worker · vtv-audio-worker\nvtv-production-worker · vtv-assemble-worker"]
    end

    Mac -->|"REST + SSE"| API
    Agent -->|"Presigned multipart PUT"| S3
    API --> DB
    API --> Outbox
    Sched -->|"StageJob dispatch"| Modal
    Modal -->|"StageResult + asset URI"| DB
    Modal <-->|"stream input / write output"| S3
    AnalysisApp --- Volume
    VisualWorker --- Volume
```

---

## Pipeline

```mermaid
flowchart TD
    A([🎬 多集视频上传\nffprobe · SHA-256 · 断点续传]) --> B

    subgraph P2["Phase 2 · 全剧分析"]
        B[INGEST_VALIDATE\nProxy Generate\nShot Detection] --> C
        C[ASR_ALIGN\nVAD · 词级对齐 · 说话人分离] --> D
        D[VISION_ANALYSIS\n人物轨迹 · 场景 · OCR · 几何] --> E
        E[PROJECT_SYNTHESIS\n本土化圣经 · Anchor Pack\nContinuity Snapshot]
    end

    E --> F{人工资产确认\nCharacter · Look · Voice · Location}

    subgraph P3["Phase 3 · 自动生产（镜头级 DAG）"]
        F --> G[Shot Router A–F\n可解释决策 + 原因码]
        G -->|A 保留| H1[PRESERVE\nFFmpeg passthrough]
        G -->|B 字幕清洁| H2[SUBTITLE_CLEAN]
        G -->|C 人物替换| H3[CHARACTER_REPLACE\nSAM3.1→Wan-Animate passthrough]
        G -->|D 背景替换| H4[BACKGROUND_REPLACE\nVACE passthrough]
        G -->|E 联合替换| H5[JOINT_REPLACE]
        G -->|F 完整重生| H6[FULL_REGEN\nLTX-2.3 / Wan2.2 passthrough]
        H3 & H4 & H5 & H6 --> I[TTS_GENERATE\nVoxCPM2 / Fish S2 Pro passthrough]
        I --> J[LIPSYNC_GENERATE\nLatentSync / InfiniteTalk passthrough]
    end

    subgraph P4["Phase 4 · QC 与合成"]
        J --> K[VISUAL_QC\nEvaluator Release · 硬失败门禁 · 熔断]
        K -->|QC_PASSED| L[AUDIO_STEM_SEPARATION\n背景音 · 对白 · 效果音]
        L --> M[SUBTITLE_RENDER\nPillow · CPS 市场约束]
        M --> N[AUDIO_MIX]
        N --> O[PICTURE_CONFORM\nShot 替换 · 50ms 时长校验]
        O --> P[ASSEMBLE_EPISODE\nFFmpeg H.264/AAC · 9:16]
        P --> Q[DELIVERY_EVIDENCE\nProvenance Manifest · C2PA]
    end

    Q --> R([📦 交付包\n成片 · 字幕 · 质量报告 · 镜头清单])

    style P2 fill:#e8f4fd,stroke:#2980b9
    style P3 fill:#eafaf1,stroke:#27ae60
    style P4 fill:#fef9e7,stroke:#f39c12
```

---

## Features

### 已实现（P0–P5 完成）

| 模块 | 功能 | 状态 | 备注 |
|---|---|:---:|---|
| **基础设施** | PostgreSQL 26 表 · 13 迁移 · DAG/Outbox/lease/CAS | ✅ | 完整状态机 |
| | S3/MinIO multipart 上传 · SHA-256 校验 · 断点续传 | ✅ | |
| | FastAPI 控制 API · 50+ 路由 · 202+job_id 异步模式 | ✅ | |
| | 数据库驱动编排器 · `FOR UPDATE SKIP LOCKED` | ✅ | |
| | Tauri 2 + React Mac 控制端 | ✅ | 含离线演示模式 |
| | Transactional Outbox · SSE 事件流 · Webhook · Alert | ✅ | |
| **媒体分析** | ffprobe 媒体探测 · H.264/AAC 校验 | ✅ | |
| | 代理生成 · 场景检测 · 镜头切分 | ✅ | FFmpeg 实现 |
| | ASR/VAD/词级对齐/说话人分离流水线 | ✅ | passthrough adapter |
| | 人物轨迹/场景/OCR/几何视觉分析流水线 | ✅ | passthrough adapter |
| | 本土化圣经 / Anchor Pack / Continuity Snapshot | ✅ | DRAFT release |
| **生产流水线** | A–F 可解释镜头路由分类器 | ✅ | 完整决策树 |
| | 视觉生产 Worker (C/D/E/F) | ✅ | passthrough stub |
| | TTS 生成 · Lipsync 生成 | ✅ | passthrough stub |
| | 音频茎分离 (Demucs) | ✅ | 真实 GPU 调用 |
| | 字幕渲染 · Pillow · 市场 CPS 约束 | ✅ | |
| | 音频混音 · 画面校正 · 集合成 (FFmpeg) | ✅ | |
| | 交付证据 · Provenance Manifest | ✅ | |
| | C2PA 内容凭证状态机 | ✅ | |
| **质量控制** | QC 评估器 release 框架 · 硬失败门禁 | ✅ | |
| | 视觉 QC Runner · 熔断器 (50% 失败率) | ✅ | |
| | 模型 Release 注册表 · 生命周期状态机 | ✅ | OBSERVATION→APPROVED |
| | Benchmark Release · Golden 评分门禁 | ✅ | |
| | 模型自动化 CANARY/ACTIVE 灰度 | ✅ | CAS 保护 |
| | 候选组 (Candidate Group) · 采用唯一约束 | ✅ | |
| **权利与合规** | Rights Release 执行门禁 | ✅ | |
| | Artifact Release 依赖图 · 版本失效传播 | ✅ | |
| | 数据保留策略 · 生命周期规则 | ✅ | |
| **运营工具** | 5 市场配置 (en-US/en-GB/es-US/ko-KR/ja-JP) | ✅ | 含文化规则 |
| | 成本报告 · 预算硬上限 | ✅ | |
| | 健康检查 · 系统指标 · 缓存统计 | ✅ | |
| | 项目归档/恢复 · 异常中心 · 批量重试 | ✅ | |
| | 模型热更新配置 | ✅ | |
| **Modal 部署** | vtv-analysis App 部署验证 | ✅ | 2026-07-24 |

### 待实现（后续阶段）

| 功能 | 说明 |
|---|---|
| 真实 GPU 模型推理 | SAM3.1 / MatAnyone2 / Wan-Animate / MoCha / LTX-2.3 / VoxCPM2 等全部为 passthrough；需按 v3.2 §9 模型准入流程逐一引入 |
| 独立 Modal Apps | 计划需 ingest / audio / render / qc / assemble 各一个 App；当前仅 analysis.py |
| configs/ 目录 | 环境、模型、质量档位和市场配置的 YAML 文件层 |
| Golden Dataset 测试套 | tests/golden/ 目录及固定镜头集基准 |
| 可观测性集成 | OpenTelemetry / Datadog / Sentry 接入 |
| 认证/授权系统 | workspace 访问令牌与 API 鉴权中间件 |
| Mac 签名/公证 | Apple Developer 证书（DMG 分发） |
| VLM 项目理解 | Gemini 3.1 Pro / Qwen3-VL 跨集剧情/实体抽取 |
| 连续性图谱 (Continuity Graph) | VGGT-Ω + CoTracker3 几何重建 |

---

## Quickstart

### 依赖

- Python 3.11+ · [uv](https://docs.astral.sh/uv/)
- Docker（本地 PostgreSQL + MinIO）
- Node 18+ · npm
- Rust（Tauri 2 客户端构建）

### 本地启动

```bash
# 1. 克隆并安装依赖
git clone https://github.com/SusuCAP/VTV.git && cd VTV
uv sync --all-packages

# 2. 启动本地数据库和对象存储
docker compose -f infra/postgres/docker-compose.yml up -d

# 3. 应用迁移
uv run python scripts/apply_migrations.py \
  postgresql+asyncpg://vtv:vtv@127.0.0.1:5432/vtv

# 4. 启动控制 API
VTV_DATABASE_URL=postgresql+asyncpg://vtv:vtv@127.0.0.1:5432/vtv \
  uv run uvicorn vtv_control_api.app:app --host 127.0.0.1 --port 8000

# 5. 启动本地编排器（另一个终端）
uv run vtv-orchestrator postgresql+asyncpg://vtv:vtv@127.0.0.1:5432/vtv

# 6. 启动 Mac 客户端前端
npm run dev:mac
```

### 运行测试

```bash
# 单元 + 组件测试（无需 Docker）
uv run pytest tests/unit tests/component -q

# 集成测试（需要 PostgreSQL + MinIO）
VTV_DATABASE_URL=postgresql+asyncpg://vtv:vtv@127.0.0.1:5432/vtv \
VTV_S3_ENDPOINT=http://127.0.0.1:9000 \
  uv run pytest tests/integration -q
```

### Modal 部署

```bash
# 重要：macOS 系统代理会导致 gRPC 瞬间失败，需禁用 Modal 代理检测
export MODAL_DISABLE_API_PROXY=1   # 建议写入 ~/.zshrc

# 设置 token（仅首次）
uv run modal token set --token-id <id> --token-secret <secret> --profile=<profile>
uv run modal profile activate <profile>

# 部署分析 App
uv run modal deploy modal_apps/analysis.py
```

---

## Repository Structure

```text
apps/
  control-api/     FastAPI 控制平面（50+ REST 路由，202+job_id 异步）
  mac-client/      Tauri 2 + React/TypeScript Mac 控制端
  orchestrator/    数据库驱动 DAG 编排器

workers/
  analysis/        全剧分析（ffprobe · ASR · 视觉 · 项目合成）
  audio/           音频生产（Demucs 茎分离）
  media/           媒体预处理（代理 · 镜头切分）
  production/      视觉生产（TTS · Lipsync passthrough）
  assemble/        集合成（字幕 · 混音 · FFmpeg 合轨）
  visual/          视觉生产（A–F 路由 · SAM/Wan passthrough）

packages/
  schemas/         共享 Pydantic Schema + TypeScript 类型
  db/              SQLAlchemy 模型 · DAG · Outbox · lease · 状态机
  storage/         S3/MinIO/R2 Adapter（multipart · SHA-256）
  media/           ffprobe · FFmpeg 超时执行
  analysis/        ASR/VAD/视觉 Adapter 协议
  audio/           音频模型 Adapter 协议
  production/      本土化圣经 · Anchor Pack · Continuity Snapshot
  routing/         A–F 镜头路由分类器（完整决策树）
  evaluation/      QC 评估器 release · Golden 门禁
  delivery/        交付清单 · Provenance Manifest
  assembly/        集合成运行时
  markets/         5 市场配置（含 zh-CN→en-US 文化规则）
  c2pa/            C2PA Content Credentials 状态机

modal_apps/
  analysis.py      全剧分析 Modal App（已部署：vtv-analysis）

migrations/        0001–0013 PostgreSQL 手写 SQL 迁移（26 表）
scripts/           开发辅助（迁移应用等）
tests/             unit · integration(86/86) · component
docs/
  architecture/    30+ 份架构决策文档
  design/          Mac 客户端概念稿
  runbooks/        本地开发 · Modal 部署运行手册
infra/             Docker Compose（postgres + minio）· GitHub Actions CI
```

---

## Contributing

欢迎 Issue 和 Pull Request。提交前请确保：

```bash
uv run ruff check .          # 静态检查
uv run ruff format --check . # 格式检查
uv run pytest tests/unit -q  # 单元测试
```

模型接入请遵循 v3.2 §21.5 前沿模型引入流程：Research → Sandbox → Benchmark → Repro Gate → Candidate → Approved。

---

## Documentation

- [项目进度](docs/PROJECT_PROGRESS.md) — 阶段完成度与逐步验收记录
- [实施路线图](docs/IMPLEMENTATION_PLAN.md) — P0–P5 各阶段退出条件
- [本地开发运行手册](docs/runbooks/LOCAL_DEVELOPMENT.md) — 启动顺序与 Modal 代理问题说明
- [架构决策](docs/architecture/) — 30+ 份 ADR

---

## License

[MIT](LICENSE) © 2026 VTV Contributors

本项目为**非商业研究用途**。模型许可、源媒体权利、演员肖像/声音授权及目标市场合规风险由使用者自行判断。详见 [v3.2 §18 安全、隐私、版权与合规](docs/PROJECT_PROGRESS.md)。
