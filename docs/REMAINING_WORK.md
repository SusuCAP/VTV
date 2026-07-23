# VTV 剩余工作计划

> 基于 v3.2 文档全量对比审计（2026-07-24）生成。  
> 进度记录见 [COMPLETION_LOG.md](COMPLETION_LOG.md)。

---

## P10：生产控制补完（高优先级，可立即实施）

### P10-A：项目暂停 / 恢复 / 取消端点
**文档依据**：§7.2、§7.4  
**影响**：无此功能无法安全中止失控的生产任务

- [ ] migration `0014_execution_controls.sql`：新建 `execution_controls` 表
  - 字段：`project_id`（UNIQUE）、`state`（ACTIVE/PAUSED/CANCEL_REQUESTED/CANCELLED）、`control_version`、`pause_reason`、`cancelled_at`
- [ ] scheduler.py：在 `claim_one` 路径检查 `execution_controls.state`；PAUSED/CANCEL_REQUESTED 时跳过领取
- [ ] scheduler.py：`commit_result` 时检查 `control_version`，取消后只登记 orphan，不得提交为 ADOPTED
- [ ] API 端点：`POST /v1/projects/{id}:pause`、`:resume`、`:cancel`
- [ ] Schema：`PauseRequest`、`CancelRequest`、`ControlStateRead`
- [ ] 单元测试：覆盖 PAUSED 跳过领取、CANCEL_REQUESTED 阻止提交、恢复重新派发

验收：暂停项目后 orchestrator 停止分发，恢复后继续，取消后 Worker 提交被拒绝。

---

### P10-B：Modal 并发控制
**文档依据**：§8.2  
**影响**：无并发上限时单项目可能吃尽 Modal GPU 配额，成本失控

为每个 Modal App 添加：
- [ ] `max_containers`（analysis=4, audio=4, visual=8, production=4, assemble=8）
- [ ] `scaledown_window=300`（5分钟无任务后缩容）
- [ ] `buffer_containers=1`（保持1个热备）

文件：`modal_apps/analysis.py`、`audio.py`、`visual.py`、`production.py`、`assemble.py`

验收：`uv run modal deploy` 成功，Modal Dashboard 显示并发上限。

---

### P10-C：缺失数据库表
**文档依据**：§13  
**影响**：Continuity 图谱无法持久化，删除安全性缺失

- [ ] migration `0015_characters.sql`：`characters`、`character_releases`、`look_states`
- [ ] migration `0016_locations.sql`：`locations`、`location_releases`
- [ ] migration `0017_continuity.sql`：`continuity_snapshots`、`anchor_assets`
- [ ] migration `0018_governance.sql`：`deletion_tombstones`、`audit_logs`、`cost_events`、`runtime_profiles`

验收：`apply_migrations.py` 无报错，`psql` 可查到所有新表。

---

### P10-D：Rights Release 在 Scheduler 强制门禁
**文档依据**：§18.3，`execution_allowed` 逻辑  
**影响**：当前仅有 API 端点，生产阶段未实际检查授权

- [ ] `scheduler.py` 的 `build_job` 中：对 VISUAL_*/TTS_GENERATE/LIPSYNC_GENERATE 类型 Stage，查询关联的 `rights_release`，`valid_at_execution=False` 或 `revoked_at IS NOT NULL` 时拒绝领取，写入 `RIGHTS_BLOCKED` 错误
- [ ] 单元测试：授权有效时正常领取；已撤销时拒绝

---

## P11：质量提升（中优先级）

### P11-A：TTS 多候选赛马（VoxCPM2 + Fish Audio S2 Pro）
**文档依据**：§12 TTS 治理，§9.2 候选矩阵  

- [ ] `packages/production/src/vtv_production/voxcpm2_adapter.py`：实现 `TtsAdapter` 协议，通过 `VTV_VOXCPM2_ENDPOINT` 调用 VoxCPM2 API
- [ ] `packages/production/src/vtv_production/fish_audio_adapter.py`：实现 `TtsAdapter` 协议，通过 Fish Audio API
- [ ] `workers/production/src/vtv_production_worker/factory.py`：在 TTS dispatch 路径中支持 `adapter_mode=voxcpm2` 和 `adapter_mode=fish_audio`
- [ ] `configs/models/tts.yaml`：补充 VoxCPM2 和 Fish Audio 配置

---

### P11-B：MatAnyone2 软抠像适配器
**文档依据**：§9.2，§10  
与 SAM3.1 配合处理头发/半透明/运动模糊边缘

- [ ] `packages/production/src/vtv_production/matanyone2_adapter.py`：实现 `SegmentationAdapter` 协议
- [ ] `workers/visual/src/vtv_visual_worker/factory.py`：在 `segmentation_adapter_mode=matanyone2` 时注入
- [ ] `configs/models/visual.yaml`：补充 MatAnyone2 配置

---

### P11-C：Mac 客户端缺失页面
**文档依据**：§6.2，8 个完整页面  
当前缺失 4 个页面：

- [ ] **新建项目页**：目录选择、集自动排序、目标市场选择、质量档位、预算上限
- [ ] **资产确认页**：原角色 vs. 海外角色对照；服装/场景/声音版本锁定
- [ ] **生产监控页**：按阶段/集/镜头查看队列深度、GPU 运行数、预计剩余成本
- [ ] **交付页**：成片/字幕/报告/清单下载与 SHA-256 校验

文件：`apps/mac-client/src/pages/`（新建 pages 目录）

---

### P11-D：Golden Dataset 真实夹具
**文档依据**：§17，§22，30-50 个固定镜头  

- [ ] 下载/准备 5 个代表性测试视频（近景/双人/遮挡/动作/文字）
- [ ] 运行 `pytest tests/golden/ --update-golden` 生成 ASR baseline
- [ ] 新增 `tests/golden/test_vision_golden.py`：视觉分析回归测试

---

## P12：未来扩展（低优先级 / GPU 依赖）

### P12-A：大模型视觉适配器
- [ ] MoCha（复杂遮挡人物替换）
- [ ] HunyuanCustom（多主体/联合替换）
- [ ] VACE（场景/对象编辑）
- [ ] LTX-2.3 22B（完整音视频生成）

### P12-B：视觉检索 + VLM 项目理解
- [ ] DINOv3 + Qwen3-VL Embedding（服装/场景一致性检索）
- [ ] Gemini 3.1 Pro / Qwen3-VL-235B（跨集剧情/实体抽取）

### P12-C：CoTracker3 点轨迹
- [ ] 蒙版漂移校验、道具追踪、屏幕方向验证

### P12-D：Mac 客户端签名/公证
- [ ] Apple Developer 证书，Tauri 签名配置，DMG 公证，自动更新

### P12-E：Staging 环境
- [ ] 独立 Modal Environment、独立 DB schema、独立 S3 bucket

### P12-F：模型 6 步引入流程自动化
- [ ] Research → Sandbox → Benchmark → Repro Gate → Candidate → Approved 各阶段 checklist

---

## 执行顺序

```
P10-A → P10-B → P10-C → P10-D   (本轮，约5天)
P11-A → P11-B → P11-C            (次轮，约7天)
P12-*                             (按需，GPU/资源就绪后)
```

每完成一项，在 `docs/COMPLETION_LOG.md` 追加记录。
