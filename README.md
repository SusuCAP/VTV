# VTV

国产短剧海外本土化自动生产平台（非 ComfyUI）。项目采用 Mac 控制端、FastAPI 控制平面、PostgreSQL 状态存储、S3 兼容对象存储与 Modal CPU/GPU Worker 的分层架构。

> **当前状态：P0–P5 全部完成（2026-07-24）。** Modal 计算平面已验证部署（`vtv-analysis`）。详见 [项目进度](docs/PROJECT_PROGRESS.md) 与 [实施路线图](docs/IMPLEMENTATION_PLAN.md)。

## 目标

- 多集视频一次接入、断点上传与自动排序
- 全剧级人物、场景、台词和文化要素分析
- A–F 镜头路由与可解释决策
- 配音、字幕、口型、混音与逐集合成
- 数据库驱动的幂等调度、断点续跑、成本治理和完整追溯
- 自动 QC、人工审核、模型灰度与安全合规门禁

## 仓库结构

```text
apps/
  control-api/   FastAPI 控制平面（项目、集、任务、资产、审核 API）
  mac-client/    Tauri 2 + React/TypeScript Mac 控制端
  orchestrator/  本地数据库驱动编排器
workers/
  analysis/      全剧分析 Worker（ffprobe、ASR、视觉、合成）
  audio/         音频生产 Worker（TTS、混音、口型）
  media/         媒体预处理 Worker（代理、镜头切分）
  production/    视觉生产 Worker（A–F 路由、SAM/Wan-Animate passthrough）
  assemble/      集合成 Worker（FFmpeg 合轨、字幕）
  visual/        视觉 QC Worker
packages/
  schemas/       共享 Pydantic Schema 与生成的 TypeScript 类型
  db/            SQLAlchemy 模型、DAG、Outbox、lease、状态机
  storage/       S3 兼容对象存储 Adapter（MinIO/R2/S3）
  media/         ffprobe、FFmpeg 超时执行与错误诊断
  analysis/      ASR、VAD、视觉观察适配器协议
  audio/         音频模型适配器协议
  production/    本土化圣经、锚点包、连续性快照合约
  routing/       A–F 镜头路由分类器
  evaluation/    QC 评估器 release 框架与阈值校准
  delivery/      交付清单与包合约
  assembly/      集合成运行时
  markets/       多市场配置（en-US/en-GB/es-US/ko-KR/ja-JP）
  c2pa/          C2PA 内容可信凭证状态机
modal_apps/
  analysis.py    Modal 全剧分析 App（已部署：vtv-analysis）
migrations/      0001–0013 PostgreSQL 迁移（SQLAlchemy Alembic 风格手写 SQL）
scripts/         开发辅助脚本（迁移应用、Seed 等）
tests/
  unit/          单元测试
  integration/   PostgreSQL + MinIO 集成测试（81/81 通过）
  component/     组件级端到端测试
docs/
  architecture/  30+ 份架构决策文档
  design/        Mac 客户端概念稿
  runbooks/      本地开发运行手册
infra/
  postgres/      Docker Compose（本地 PostgreSQL + MinIO）
  ci/            GitHub Actions 工作流
```

## 开发约束

- Python 使用项目 `.venv`，由 `uv` 管理；不使用系统 Python 或全局 pip。
- Node 依赖仅安装在项目内；优先 `cnpm`，不可用时使用 `npm`。
- 大文件不经 API 代理，使用对象存储预签名分片上传。
- 长任务统一返回 `202 + job_id`，状态落 PostgreSQL，产物落对象存储。
- Worker 必须幂等，模型/角色/规则/工作流均使用不可变 release。
- **Modal 连接**：本机开启系统代理时，需设置 `MODAL_DISABLE_API_PROXY=1`（Modal 1.5+ 自动读取系统代理并要求 `python-socks`；设此变量后走直连，无需安装额外依赖）。建议加入 `~/.zshrc`：`export MODAL_DISABLE_API_PROXY=1`。

## 文档依据

实现依据为《国产短剧海外本土化自动生产平台——完整技术设计方案（非 ComfyUI）》v3.2，日期 2026-07-22。
