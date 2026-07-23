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

## Modal 计算平面

### 连接说明

Modal 1.5+ 会自动读取系统代理（`urllib.request.getproxies()`）。macOS 开启终端代理工具时，系统网络设置中存在 `http://127.0.0.1:xxxx`，Modal 检测到后尝试通过 `python-socks` 建立 gRPC 代理连接，但该包未安装，导致连接**瞬间失败**（0.004s，不是超时）。

**根治方案：设置 `MODAL_DISABLE_API_PROXY=1`。**

建议加入 `~/.zshrc`（永久生效）：

```bash
echo 'export MODAL_DISABLE_API_PROXY=1' >> ~/.zshrc
source ~/.zshrc
```

### 部署命令

```bash
# 设置 token（仅首次或更换账号时需要）
MODAL_DISABLE_API_PROXY=1 uv run modal token set \
  --token-id <token-id> \
  --token-secret <token-secret> \
  --profile=zhuaiba88

uv run modal profile activate zhuaiba88

# 部署分析 App
MODAL_DISABLE_API_PROXY=1 uv run modal deploy modal_apps/analysis.py

# 查看已部署 App
MODAL_DISABLE_API_PROXY=1 uv run modal app list
```

已部署 App：`vtv-analysis`（profile: zhuaiba88）
Dashboard：https://modal.com/apps/zhuaiba88/main/deployed/vtv-analysis

### 备选方案

如果需要代理访问 Modal，安装 `python-socks`：

```bash
uv add "python-socks[asyncio]"
```

安装后**无需** `MODAL_DISABLE_API_PROXY=1`，Modal 会通过 HTTP 代理建立 gRPC 连接。

## 当前联调接口

- `GET/POST /v1/projects`
- `GET /v1/projects/{id}`
- `GET /v1/projects/{id}/episodes`
- `GET /v1/projects/{id}/jobs`
- `POST /v1/projects/{id}/analysis-jobs`
- multipart upload init/complete/status
