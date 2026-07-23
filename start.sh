#!/usr/bin/env bash
# =============================================================================
#  VTV 一键启动脚本
#  用法: ./start.sh [选项]
#
#  选项:
#    --modal       同时部署所有 Modal Apps（需要 Modal 账号）
#    --stop        停止所有本地服务
#    --reset       清空数据库和对象存储并重新初始化
#    --status      查看各服务运行状态
#    --help        显示帮助
# =============================================================================
set -euo pipefail

# ── 颜色 ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${BLUE}▶${RESET} $*"; }
ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET} $*"; }
err()  { echo -e "${RED}✗${RESET} $*" >&2; }
sep()  { echo -e "${CYAN}────────────────────────────────────────────────${RESET}"; }

# ── 根目录 ───────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 加载 .env ────────────────────────────────────────────────────────────────
if [[ -f .env ]]; then
  set -a; source .env; set +a
  ok "已加载 .env"
else
  warn ".env 不存在，使用默认值（运行 cp .env.example .env 后编辑）"
fi

DB_URL="${VTV_DATABASE_URL:-postgresql+asyncpg://vtv:vtv@127.0.0.1:5432/vtv}"
S3_ENDPOINT="${VTV_S3_ENDPOINT:-http://127.0.0.1:9000}"
S3_ACCESS_KEY="${VTV_S3_ACCESS_KEY:-vtv}"
S3_SECRET_KEY="${VTV_S3_SECRET_KEY:-change-me-in-non-local-environments}"
S3_BUCKET="${VTV_S3_BUCKET:-vtv-local}"

# ── 参数解析 ─────────────────────────────────────────────────────────────────
OPT_MODAL=0; OPT_STOP=0; OPT_RESET=0; OPT_STATUS=0
for arg in "$@"; do
  case $arg in
    --modal)  OPT_MODAL=1 ;;
    --stop)   OPT_STOP=1 ;;
    --reset)  OPT_RESET=1 ;;
    --status) OPT_STATUS=1 ;;
    --help|-h)
      echo -e "${BOLD}VTV 一键启动脚本${RESET}"
      echo ""
      echo "用法: ./start.sh [选项]"
      echo ""
      echo "  （无选项）   启动 PostgreSQL + MinIO，应用迁移，启动控制 API + 编排器"
      echo "  --modal      同时部署所有 Modal Apps（analysis/audio/visual/production/assemble）"
      echo "  --stop       停止所有本地服务"
      echo "  --reset      清空数据并重新初始化（危险！）"
      echo "  --status     查看各服务运行状态"
      exit 0
      ;;
    *) err "未知选项: $arg"; exit 1 ;;
  esac
done

# ── --status ─────────────────────────────────────────────────────────────────
if [[ $OPT_STATUS -eq 1 ]]; then
  sep
  echo -e "${BOLD}服务状态${RESET}"
  sep
  docker compose ps 2>/dev/null || warn "Docker Compose 未运行"
  echo ""
  echo -n "控制 API (8000): "
  curl -sf http://127.0.0.1:8000/healthz -o /dev/null && echo -e "${GREEN}运行中${RESET}" || echo -e "${RED}未运行${RESET}"
  echo -n "编排器 PID 文件: "
  [[ -f /tmp/vtv-orchestrator.pid ]] && echo -e "${GREEN}$(cat /tmp/vtv-orchestrator.pid)${RESET}" || echo -e "${YELLOW}未启动${RESET}"
  exit 0
fi

# ── --stop ───────────────────────────────────────────────────────────────────
if [[ $OPT_STOP -eq 1 ]]; then
  log "停止本地服务..."
  if [[ -f /tmp/vtv-orchestrator.pid ]]; then
    kill "$(cat /tmp/vtv-orchestrator.pid)" 2>/dev/null && ok "编排器已停止" || true
    rm -f /tmp/vtv-orchestrator.pid
  fi
  if [[ -f /tmp/vtv-api.pid ]]; then
    kill "$(cat /tmp/vtv-api.pid)" 2>/dev/null && ok "控制 API 已停止" || true
    rm -f /tmp/vtv-api.pid
  fi
  docker compose stop
  ok "Docker 服务已停止"
  exit 0
fi

# ── --reset ──────────────────────────────────────────────────────────────────
if [[ $OPT_RESET -eq 1 ]]; then
  warn "即将清空所有本地数据！"
  read -rp "确认输入 YES: " confirm
  [[ "$confirm" == "YES" ]] || { log "已取消"; exit 0; }
  docker compose down -v
  ok "数据已清空"
fi

# =============================================================================
#  检查依赖
# =============================================================================
sep
echo -e "${BOLD}1. 检查依赖${RESET}"
sep

check_cmd() {
  if command -v "$1" &>/dev/null; then ok "$1"; else err "$1 未找到 — $2"; exit 1; fi
}
check_cmd docker  "请安装 Docker Desktop"
check_cmd uv      "请运行: curl -LsSf https://astral.sh/uv/install.sh | sh"
check_cmd python3 "请安装 Python 3.12+"

# =============================================================================
#  启动本地服务（PostgreSQL + MinIO）
# =============================================================================
sep
echo -e "${BOLD}2. 启动 PostgreSQL + MinIO${RESET}"
sep

docker compose up -d --wait
ok "PostgreSQL 已就绪（:5432）"
ok "MinIO 已就绪（:9000  Console: http://127.0.0.1:9001）"

# =============================================================================
#  安装 Python 依赖
# =============================================================================
sep
echo -e "${BOLD}3. 安装 Python 依赖${RESET}"
sep

uv sync --all-packages --quiet
ok "依赖已同步"

# =============================================================================
#  应用数据库迁移
# =============================================================================
sep
echo -e "${BOLD}4. 应用数据库迁移${RESET}"
sep

uv run python scripts/apply_migrations.py "$DB_URL"
ok "迁移完成"

# =============================================================================
#  初始化 MinIO Bucket
# =============================================================================
sep
echo -e "${BOLD}5. 初始化 MinIO Bucket（${S3_BUCKET}）${RESET}"
sep

uv run python - <<PYEOF
import sys
try:
    from minio import Minio
    from minio.error import S3Error
    c = Minio(
        "${S3_ENDPOINT}".replace("http://", "").replace("https://", ""),
        access_key="${S3_ACCESS_KEY}",
        secret_key="${S3_SECRET_KEY}",
        secure="${S3_ENDPOINT}".startswith("https"),
    )
    if not c.bucket_exists("${S3_BUCKET}"):
        c.make_bucket("${S3_BUCKET}")
        print("bucket created: ${S3_BUCKET}")
    else:
        print("bucket exists: ${S3_BUCKET}")
except ImportError:
    # minio SDK not in venv — use mc or skip
    print("minio SDK not found, skipping bucket init (install with: uv pip install minio)")
except Exception as e:
    print(f"warn: {e}", file=sys.stderr)
PYEOF
ok "Bucket 就绪"

# =============================================================================
#  部署 Modal Apps（可选）
# =============================================================================
if [[ $OPT_MODAL -eq 1 ]]; then
  sep
  echo -e "${BOLD}6. 部署 Modal Apps${RESET}"
  sep

  MODAL_APPS=(analysis audio visual production assemble)
  for app in "${MODAL_APPS[@]}"; do
    log "部署 modal_apps/${app}.py ..."
    uv run modal deploy "modal_apps/${app}.py" \
      && ok "vtv-${app} 部署成功" \
      || warn "vtv-${app} 部署失败（跳过）"
  done
fi

# =============================================================================
#  启动控制 API
# =============================================================================
sep
echo -e "${BOLD}7. 启动控制 API（后台，:8000）${RESET}"
sep

# 先停止旧进程
if [[ -f /tmp/vtv-api.pid ]]; then
  kill "$(cat /tmp/vtv-api.pid)" 2>/dev/null || true
  rm -f /tmp/vtv-api.pid
fi

nohup uv run uvicorn vtv_control_api.app:app \
  --host 127.0.0.1 --port 8000 \
  --log-level warning \
  > /tmp/vtv-api.log 2>&1 &
echo $! > /tmp/vtv-api.pid

# 等待 API 就绪
log "等待控制 API 就绪..."
for i in $(seq 1 20); do
  if curl -sf http://127.0.0.1:8000/healthz -o /dev/null 2>/dev/null; then
    ok "控制 API 已就绪 → http://127.0.0.1:8000"
    break
  fi
  sleep 0.5
  if [[ $i -eq 20 ]]; then
    err "控制 API 启动超时，查看日志: tail -f /tmp/vtv-api.log"
  fi
done

# =============================================================================
#  启动编排器
# =============================================================================
sep
echo -e "${BOLD}8. 启动编排器（后台）${RESET}"
sep

if [[ -f /tmp/vtv-orchestrator.pid ]]; then
  kill "$(cat /tmp/vtv-orchestrator.pid)" 2>/dev/null || true
  rm -f /tmp/vtv-orchestrator.pid
fi

nohup uv run vtv-orchestrator "$DB_URL" \
  > /tmp/vtv-orchestrator.log 2>&1 &
echo $! > /tmp/vtv-orchestrator.pid
ok "编排器已启动（PID $(cat /tmp/vtv-orchestrator.pid)）"

# =============================================================================
#  完成
# =============================================================================
sep
echo -e "${BOLD}${GREEN}✓ VTV 启动完成${RESET}"
sep
echo ""
echo -e "  控制 API       → ${CYAN}http://127.0.0.1:8000${RESET}"
echo -e "  API Docs       → ${CYAN}http://127.0.0.1:8000/docs${RESET}"
echo -e "  MinIO Console  → ${CYAN}http://127.0.0.1:9001${RESET}  (vtv / change-me-in-non-local-environments)"
echo ""
echo -e "  日志:"
echo -e "    tail -f /tmp/vtv-api.log"
echo -e "    tail -f /tmp/vtv-orchestrator.log"
echo ""
echo -e "  停止: ${YELLOW}./start.sh --stop${RESET}"
if [[ $OPT_MODAL -eq 0 ]]; then
  echo -e "  Modal 部署: ${YELLOW}./start.sh --modal${RESET}"
fi
echo ""
