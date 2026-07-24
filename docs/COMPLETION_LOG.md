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
