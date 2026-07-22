# 本地开发运行手册

## 环境

- Python：项目 `.venv`，通过 `uv sync --all-packages` 建立。
- Node：项目局部依赖；本机无 `cnpm` 时使用 `npm ci`。
- PostgreSQL/MinIO：`docker compose up -d postgres minio`。

## 启动顺序

```bash
.venv/bin/python scripts/apply_migrations.py \
  postgresql+asyncpg://vtv:vtv@127.0.0.1:5432/vtv

VTV_DATABASE_URL=postgresql+asyncpg://vtv:vtv@127.0.0.1:5432/vtv \
  .venv/bin/uvicorn vtv_control_api.app:app --host 127.0.0.1 --port 8000

npm run dev:mac

.venv/bin/vtv-orchestrator \
  postgresql+asyncpg://vtv:vtv@127.0.0.1:5432/vtv
```

Mac 客户端默认访问 `http://127.0.0.1:8000`；可通过 `VITE_CONTROL_API_BASE_URL` 覆盖。控制 API 不可用时客户端明确显示“离线演示”，不会把演示数据标记为服务端状态。

## 当前联调接口

- `GET/POST /v1/projects`
- `GET /v1/projects/{id}`
- `GET /v1/projects/{id}/episodes`
- `GET /v1/projects/{id}/jobs`
- `POST /v1/projects/{id}/analysis-jobs`
- multipart upload init/complete/status
