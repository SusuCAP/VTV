# VTV

国产短剧海外本土化自动生产平台（非 ComfyUI）。项目采用 Mac 控制端、FastAPI 控制平面、PostgreSQL 状态存储、S3 兼容对象存储与 Modal CPU/GPU Worker 的分层架构。

> 当前状态：按 v3.2 最终技术方案分阶段建设中。详见 [项目进度](docs/PROJECT_PROGRESS.md) 与 [实施路线图](docs/IMPLEMENTATION_PLAN.md)。

## 目标

- 多集视频一次接入、断点上传与自动排序
- 全剧级人物、场景、台词和文化要素分析
- A–F 镜头路由与可解释决策
- 配音、字幕、口型、混音与逐集合成
- 数据库驱动的幂等调度、断点续跑、成本治理和完整追溯
- 自动 QC、人工审核、模型灰度与安全合规门禁

## 规划中的仓库结构

```text
apps/          Mac 控制端、控制 API、编排器
workers/       接入、分析、音频、渲染、QC、合成 Worker
packages/      Schema、数据库、存储、媒体、模型适配器等共享包
modal_apps/    Modal 部署入口
migrations/    PostgreSQL 迁移
configs/       环境、模型、质量档位和市场配置
tests/         单元、集成、端到端和 Golden Dataset 测试
docs/          架构、运行手册、模型卡和项目进度
```

## 开发约束

- Python 使用项目 `.venv`，由 `uv` 管理；不使用系统 Python 或全局 pip。
- Node 依赖仅安装在项目内；优先 `cnpm`，不可用时使用 `npm`。
- 大文件不经 API 代理，使用对象存储预签名分片上传。
- 长任务统一返回 `202 + job_id`，状态落 PostgreSQL，产物落对象存储。
- Worker 必须幂等，模型/角色/规则/工作流均使用不可变 release。

## 文档依据

实现依据为《国产短剧海外本土化自动生产平台——完整技术设计方案（非 ComfyUI）》v3.2，日期 2026-07-22。
