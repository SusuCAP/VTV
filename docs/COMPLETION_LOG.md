# VTV 完成进度日志

> 每完成一项工作追加记录。计划详见 [REMAINING_WORK.md](REMAINING_WORK.md)。

---

## 格式

```
### [日期] 任务ID — 标题
- 提交：`git-hash`
- 改动：简述
- 验收：通过/失败 + 关键指标
```

---

<!-- 新记录追加到此处以下 -->

### 2026-07-24 v3.2 全量补完 — API端点 / DB迁移 / VGGT / IndexTTS2
- 提交：`8dc1a57`
- API 端点（Ch 7）：
  - `POST /v1/projects/{id}/episodes:register` — 多集文件元数据注册
  - `POST /v1/projects/{id}/assets:generate` — 触发资产生成任务
  - `POST /v1/projects/{id}/assets:approve` — 锁定资产版本
  - `GET /v1/projects/{id}/deliverables` — deliveries 路径别名
  - `AssetGenerateRequest` / `AssetApproveRequest` schema
  - `register_episodes` / `approve_assets` Protocol stubs + Memory 实现
- DB 迁移（Ch 13）：
  - `0018_workflow_plans.sql`：`workflow_plans`（镜头路由+DAG）+ `review_tasks`（人工审核队列）
  - `0019_localization_releases.sql`：`localization_releases`（全剧本土化规则版本）
  - `0020_provenance.sql`：`provenance_manifests` + `benchmark_runs` + `provider_usage`
  - `0021_model_profiles.sql`：`model_capability_profiles` + `model_access_profiles`
- 模型适配器（Ch 9）：
  - `vggt_adapter.py`：VGGTOmegaAdapter — 相机位姿/深度图/场景重建
  - `indextts2_adapter.py`：IndexTTS2Adapter — 精确时长TTS，≤4% 偏差
  - 工厂接入：`adapter_mode=indextts2` dispatch
- 验收：449 tests pass；ruff clean；已推送 main

### 2026-07-24 P12-B — DINOv3 视觉检索 + Gemini/Qwen3-VL-235B VLM 项目理解
- 提交：`00ea921`
- 改动：
  - `dino_adapter.py`：DINOv3Adapter（embed_image / similarity / retrieve / consistency_score）
  - `gemini_vlm_adapter.py`：GeminiVLMAdapter，双后端（Gemini 3.1 Pro / Qwen3-VL-235B vLLM），输出 character_relationships / cultural_exposures / entities / plot_events
  - `__init__.py`：导出两个新适配器
- 验收：449 tests pass；ruff clean
- 文档勾选：P12-B ✅

### 2026-07-24 P12 — 大模型适配器 + Staging + 签名 + 引入流程
- 提交：`d24735f`
- 改动：
  - `mocha_adapter.py` / `hunyuan_custom_adapter.py` / `vace_adapter.py` / `ltx23_adapter.py`：4 个大模型视觉适配器（lazy import，VisualGenerationAdapter 协议）
  - `cotracker3_adapter.py`：CoTracker3 点轨迹工具（独立 track() 方法）
  - `factory.py`：mocha/hunyuan_custom/vace/ltx23 dispatcher 接入
  - `configs/environments/staging-modal.yaml`：Staging 环境全量真实模型配置
  - `.github/workflows/ci.yml`：新增 staging-check job
  - `docs/MODEL_ONBOARDING.md`：6 步模型引入流程（含数值验收标准）
  - `docs/model-cards/TEMPLATE.md`：模型卡片模板
  - `docs/runbooks/MAC_SIGNING.md`：Mac 签名/公证运行手册
  - `apps/mac-client/src-tauri/tauri.conf.json`：bundle.macOS 签名字段
- 验收：449 tests pass；ruff clean；vite build ✓
- 文档勾选：P12-A ✅  P12-C ✅  P12-D ✅  P12-E ✅  P12-F ✅

### 2026-07-24 P11-D — Vision Golden Dataset 测试 + 计划勾选
- 提交：`f26bcc8`
- 改动：`tests/golden/test_vision_golden.py`：VisionAnalysisPipeline 回归测试，Qwen 适配器，person_count ±1 容差，无素材时自动跳过
- 验收：449 tests pass；ruff clean；vite build ✓
- 文档勾选：P11-D ✅  P10–P11 全部完成

### 2026-07-24 P11-C — Mac 客户端 4 个缺失页面
- 提交：`8fd44eb`
- 改动：
  - `App.tsx`：加入页面路由（React state）；新增 `NewProjectPage`（新建项目表单）、`AssetConfirmationPage`（资产确认列表）、`ProductionMonitorPage`（任务进度 + pause/resume/cancel 按钮）、`DeliveryPage`（交付列表 + 批准 + 下载）
  - `api.ts`：加入 `createProject`、`pauseProject`、`resumeProject`、`cancelProject`、`listDeliveries`、`approveDelivery`、`getDeliveryPackage` 等 8 个新 API 方法
  - Sidebar 按钮接入页面路由，加"新建项目"快捷按钮
- 验收：`tsc -b && vite build ✓`（220 kB JS）；449 Python tests pass
- 文档勾选：P11-C ✅

### 2026-07-24 P11-A/B — VoxCPM2 + Fish Audio TTS + MatAnyone2 分割适配器
- 提交：`54666b2`
- 改动：
  - `voxcpm2_adapter.py`：HTTP 接口，30语言，`VTV_VOXCPM2_ENDPOINT/API_KEY`
  - `fish_audio_adapter.py`：Fish Audio S2 Pro API，80+语言，`VTV_FISH_AUDIO_API_KEY`
  - `matanyone2_adapter.py`：软抠像（头发/半透明），`VTV_MATANYONE2_MODEL_ID`
  - 工厂接入：`adapter_mode=voxcpm2/fish_audio` + `segmentation_adapter_mode=matanyone2`
- P10-D 确认：Rights Release 门禁已在 `_rights_commit_failure()` 实现，无需额外改动
- 验收：449 tests pass；ruff clean
- 文档勾选：P10-D ✅  P11-A ✅  P11-B ✅

### 2026-07-24 P10-C — 缺失数据库迁移（characters / locations / continuity / governance）
- 提交：`5e86b27`
- 改动：新增 4 个迁移文件（0014–0017）共 7 张表
  - `characters` + `character_releases` + `look_states`
  - `locations` + `location_releases`
  - `anchor_assets` + `continuity_snapshots`
  - `audit_logs` + `cost_events` + `runtime_profiles`（含5条 GPU profile seed）
- 验收：ruff clean；SQL 语法校验通过；449 tests pass
- 文档勾选：`docs/REMAINING_WORK.md` P10-C ✅

### 2026-07-24 P10-B — Modal 并发控制
- 提交：`657ea4c`
- 改动：5 个 Modal App 均加入 `max_containers` / `scaledown_window=300` / `buffer_containers`
  - analysis/audio/production：max_containers=4, buffer=1（L4/L40S GPU）
  - visual：max_containers=8, buffer=1（视觉生成最重池）
  - assemble：max_containers=8, buffer=0（CPU-only，无需保温）
- 验收：ruff clean；449 tests pass；`modal deploy` 后 Dashboard 可见并发上限
- 文档勾选：`docs/REMAINING_WORK.md` P10-B ✅
- 提交：`23092ce`
- 改动：
  - `repository.py`：Protocol stubs + `SqlAlchemyProjectRepository` 实现 `pause_project` / `resume_project` / `cancel_project`；更新 `ExecutionControl.paused` / `cancel_requested` / `control_version`；写 Outbox 事件
  - `app.py`：新增 `POST /v1/projects/{id}:pause` / `:resume` / `:cancel` 端点
  - `config.py`：`ModelRuntimeSettings` 去掉 `env_file=".env"` 隔离测试环境
  - 新建 `docs/REMAINING_WORK.md` 和 `docs/COMPLETION_LOG.md`
- 验收：449 unit+component tests pass；ruff clean；Scheduler 已通过 `CLAIM_READY_STAGE` 和 `COMMIT_OUTPUT_READY` 查询检查 `execution_controls` 状态
- 文档勾选：`docs/REMAINING_WORK.md` P10-A ✅
