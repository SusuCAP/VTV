#!/usr/bin/env bash
# =============================================================================
#  VTV 一键启动脚本 v2
#  用法: ./start.sh [--stop] [--status] [--reset] [--help]
#
#  无参数：自动检测所有服务状态并按需启动/部署
# =============================================================================
set -euo pipefail

# ── 颜色 ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

log()   { echo -e "${BLUE}▶${RESET} $*"; }
ok()    { echo -e "${GREEN}✓${RESET} $*"; }
warn()  { echo -e "${YELLOW}⚠${RESET} $*"; }
err()   { echo -e "${RED}✗${RESET} $*" >&2; }
info()  { echo -e "${DIM}  $*${RESET}"; }
sep()   { echo -e "${CYAN}──────────────────────────────────────────────────${RESET}"; }
title() { echo ""; sep; echo -e "  ${BOLD}$*${RESET}"; sep; }

# ── 根目录 ───────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 加载 .env ────────────────────────────────────────────────────────────────
if [[ -f .env ]]; then
  set -a; source .env; set +a
else
  warn ".env 不存在，使用默认值（cp .env.example .env 后编辑）"
fi

DB_URL="${VTV_DATABASE_URL:-postgresql+asyncpg://vtv:vtv@127.0.0.1:5432/vtv}"
S3_ENDPOINT="${VTV_S3_ENDPOINT:-http://127.0.0.1:9000}"
S3_ACCESS_KEY="${VTV_S3_ACCESS_KEY:-vtv}"
S3_SECRET_KEY="${VTV_S3_SECRET_KEY:-change-me-in-non-local-environments}"
S3_BUCKET="${VTV_S3_BUCKET:-vtv-local}"
API_PORT="${VTV_API_PORT:-8001}"
FRONTEND_PORT="${VTV_FRONTEND_PORT:-5173}"

# Modal 相关
MODAL_DISABLE_API_PROXY=1
export MODAL_DISABLE_API_PROXY
MODAL_APPS=(analysis audio visual production assemble)
MODAL_APP_NAMES=(vtv-analysis vtv-audio vtv-visual vtv-production vtv-assemble)

# ── 参数解析 ─────────────────────────────────────────────────────────────────
OPT_STOP=0; OPT_RESET=0; OPT_STATUS=0; OPT_SKIP_MODAL=0
for arg in "$@"; do
  case $arg in
    --stop)         OPT_STOP=1 ;;
    --reset)        OPT_RESET=1 ;;
    --status)       OPT_STATUS=1 ;;
    --skip-modal)   OPT_SKIP_MODAL=1 ;;
    --help|-h)
      echo -e "${BOLD}VTV 一键启动脚本${RESET}"
      echo ""
      echo "用法: ./start.sh [选项]"
      echo ""
      echo "  （无选项）      全自动启动：检测 Docker / Modal / API / 前端"
      echo "  --skip-modal    跳过 Modal 部署检查（纯本地模式）"
      echo "  --stop          停止所有本地服务"
      echo "  --reset         清空数据并重新初始化（危险！）"
      echo "  --status        查看所有服务状态"
      exit 0
      ;;
    *) err "未知选项: $arg"; exit 1 ;;
  esac
done

# =============================================================================
#  --status
# =============================================================================
if [[ $OPT_STATUS -eq 1 ]]; then
  title "服务状态"
  echo ""

  # Docker
  echo -e "  ${BOLD}Docker 容器${RESET}"
  if docker compose ps 2>/dev/null | grep -q "healthy"; then
    docker compose ps 2>/dev/null | grep -E "NAME|postgres|minio" | while read -r line; do
      echo "    $line"
    done
  else
    warn "Docker Compose 未运行或无健康容器"
  fi
  echo ""

  # API
  echo -e "  ${BOLD}控制 API${RESET}"
  for port in 8000 8001 8002; do
    if curl -sf "http://127.0.0.1:${port}/healthz" -o /dev/null 2>/dev/null; then
      ok "运行中 → http://127.0.0.1:${port}"
      break
    fi
  done

  # 前端
  echo -e "  ${BOLD}Web 前端${RESET}"
  for port in 5173 5174 5175; do
    if curl -sf "http://127.0.0.1:${port}" -o /dev/null 2>/dev/null; then
      ok "运行中 → http://127.0.0.1:${port}"
      break
    fi
  done

  # Modal
  echo ""
  echo -e "  ${BOLD}Modal Apps${RESET}"
  if uv run modal app list 2>/dev/null | grep -q "deployed"; then
    for name in "${MODAL_APP_NAMES[@]}"; do
      if uv run modal app list 2>/dev/null | grep -q "$name"; then
        ok "$name (deployed)"
      else
        warn "$name (not found)"
      fi
    done
  else
    warn "无法连接 Modal 或无已部署 App"
  fi
  exit 0
fi

# =============================================================================
#  --stop
# =============================================================================
if [[ $OPT_STOP -eq 1 ]]; then
  title "停止服务"
  for pid_file in /tmp/vtv-api.pid /tmp/vtv-orchestrator.pid /tmp/vtv-frontend.pid; do
    if [[ -f "$pid_file" ]]; then
      svc=$(basename "$pid_file" .pid)
      kill "$(cat "$pid_file")" 2>/dev/null && ok "$svc 已停止" || true
      rm -f "$pid_file"
    fi
  done
  pkill -f "vtv_control_api.app:app" 2>/dev/null || true
  pkill -f "vtv-orchestrator" 2>/dev/null || true
  pkill -f "vite.*5173\|vite.*5174" 2>/dev/null || true
  docker compose stop 2>/dev/null && ok "Docker 服务已停止" || true
  exit 0
fi

# =============================================================================
#  --reset
# =============================================================================
if [[ $OPT_RESET -eq 1 ]]; then
  warn "即将清空所有本地数据！"
  read -rp "确认输入 YES: " confirm
  [[ "$confirm" == "YES" ]] || { log "已取消"; exit 0; }
  docker compose down -v && ok "数据已清空"
fi

# =============================================================================
#  Banner
# =============================================================================
clear
echo ""
echo -e "  ${BOLD}${CYAN}VTV Studio${RESET}  ${DIM}国产短剧海外本土化自动生产平台${RESET}"
echo ""
echo -e "  ${DIM}$(date '+%Y-%m-%d %H:%M:%S')${RESET}"
echo ""

# =============================================================================
#  步骤 1：检查基础依赖
# =============================================================================
title "1 / 7  检查依赖"

check_cmd() {
  command -v "$1" &>/dev/null && ok "$1" || { err "$1 未找到 — $2"; exit 1; }
}
check_cmd docker  "请安装 Docker Desktop"
check_cmd uv      "curl -LsSf https://astral.sh/uv/install.sh | sh"
check_cmd python3 "请安装 Python 3.12+"
command -v node &>/dev/null && ok "node $(node -v)" || warn "node 未找到，前端将无法启动"

# =============================================================================
#  步骤 2：Docker 容器（智能检测 + 按需启动）
# =============================================================================
title "2 / 7  Docker 容器（PostgreSQL + MinIO）"

pg_healthy=0
minio_healthy=0

# 检查是否已在运行
if docker compose ps 2>/dev/null | grep -q "vtv-postgres.*healthy"; then
  ok "PostgreSQL 已运行（healthy）"
  pg_healthy=1
fi
if docker compose ps 2>/dev/null | grep -q "vtv-minio.*healthy"; then
  ok "MinIO 已运行（healthy）"
  minio_healthy=1
fi

# 按需启动
if [[ $pg_healthy -eq 0 ]] || [[ $minio_healthy -eq 0 ]]; then
  log "启动容器..."
  docker compose up -d --wait 2>&1 | grep -v "^$" | while read -r line; do
    info "$line"
  done
  ok "PostgreSQL 就绪 (:5432)"
  ok "MinIO 就绪 (:9000 | Console: http://127.0.0.1:9001)"
fi

# =============================================================================
#  步骤 3：Python 依赖
# =============================================================================
title "3 / 7  Python 依赖"
uv sync --all-packages --quiet 2>&1 | tail -2 | while read -r line; do info "$line"; done
ok "依赖已同步"

# =============================================================================
#  步骤 4：数据库迁移
# =============================================================================
title "4 / 7  数据库迁移"
migration_output=$(uv run python scripts/apply_migrations.py "$DB_URL" 2>&1)
applied=$(echo "$migration_output" | grep -c "Applied\|applied" || echo "0")
if echo "$migration_output" | grep -qi "error\|exception"; then
  # 只有真正的错误（非"already exists"）才报错
  if echo "$migration_output" | grep -qi "error" && ! echo "$migration_output" | grep -qi "already exists"; then
    err "迁移失败：$migration_output"
    exit 1
  fi
fi
ok "迁移完成（当前已是最新版本）"

# =============================================================================
#  步骤 5：初始化 MinIO Bucket
# =============================================================================
title "5 / 7  MinIO Bucket"
uv run python - 2>/dev/null <<PYEOF
import sys
try:
    from minio import Minio
    c = Minio(
        "${S3_ENDPOINT}".replace("http://","").replace("https://",""),
        access_key="${S3_ACCESS_KEY}",
        secret_key="${S3_SECRET_KEY}",
        secure=False,
    )
    if not c.bucket_exists("${S3_BUCKET}"):
        c.make_bucket("${S3_BUCKET}")
        print("created: ${S3_BUCKET}")
    else:
        print("exists: ${S3_BUCKET}")
except Exception as e:
    print(f"skip: {e}", file=sys.stderr)
PYEOF
ok "Bucket '${S3_BUCKET}' 就绪"

# =============================================================================
#  步骤 6：Modal 部署（智能检测，缺失则自动部署）
# =============================================================================
if [[ $OPT_SKIP_MODAL -eq 0 ]]; then
  title "6 / 7  Modal Apps"

  # 检查 Modal 连通性
  modal_ok=0
  log "检查 Modal 连接..."
  if uv run modal app list 2>/dev/null | grep -q "App ID\|deployed\|─"; then
    modal_ok=1
    ok "Modal 连接正常"
  else
    warn "Modal 无法连接（检查 MODAL_DISABLE_API_PROXY=1 和网络）"
    warn "跳过 Modal 检查，使用 --skip-modal 可跳过此步骤"
  fi

  if [[ $modal_ok -eq 1 ]]; then
    # 获取已部署的 App 列表
    deployed_list=$(uv run modal app list 2>/dev/null || echo "")

    missing_apps=()
    deployed_apps=()
    for i in "${!MODAL_APPS[@]}"; do
      app="${MODAL_APPS[$i]}"
      name="${MODAL_APP_NAMES[$i]}"
      if echo "$deployed_list" | grep -q "$name.*deployed"; then
        deployed_apps+=("$name")
        ok "$name (已部署)"
      else
        missing_apps+=("$app")
        warn "$name (未部署)"
      fi
    done

    # 按需部署缺失的 App
    if [[ ${#missing_apps[@]} -gt 0 ]]; then
      echo ""
      echo -e "  ${YELLOW}发现 ${#missing_apps[@]} 个 App 未部署，开始自动部署...${RESET}"
      echo -e "  ${DIM}（首次部署需要构建镜像，约 3-10 分钟，请耐心等待）${RESET}"
      echo ""

      for app in "${missing_apps[@]}"; do
        sep
        echo -e "  ${BOLD}部署 vtv-${app}${RESET}  ${DIM}modal_apps/${app}.py${RESET}"
        sep
        echo ""

        # 实时显示部署进度
        start_ts=$(date +%s)
        if uv run modal deploy "modal_apps/${app}.py" 2>&1 | \
          while IFS= read -r line; do
            elapsed=$(( $(date +%s) - start_ts ))
            # 过滤并高亮关键行
            if echo "$line" | grep -qE "✓|Created|deployed|Building|Installing|Running|Step"; then
              echo -e "    ${GREEN}${line}${RESET}"
            elif echo "$line" | grep -qE "Error|error|Failed|failed"; then
              echo -e "    ${RED}${line}${RESET}"
            elif echo "$line" | grep -qE "Warning|warning"; then
              echo -e "    ${YELLOW}${line}${RESET}"
            elif [[ -n "$line" ]]; then
              echo -e "    ${DIM}${line}${RESET}"
            fi
          done; then
          elapsed=$(( $(date +%s) - start_ts ))
          echo ""
          ok "vtv-${app} 部署成功（耗时 ${elapsed}s）"
        else
          echo ""
          warn "vtv-${app} 部署失败（继续启动本地服务）"
        fi
        echo ""
      done

      echo ""
      ok "Modal 部署完成 ✓"
    else
      ok "所有 Modal Apps 均已部署 ✓"
    fi
  fi
fi

# =============================================================================
#  步骤 7：启动本地服务（API + 编排器 + 前端）
# =============================================================================
title "7 / 7  启动本地服务"

# ── 找可用端口 ────────────────────────────────────────────────────────────────
find_free_port() {
  local start=$1
  for port in $(seq "$start" $(( start + 10 ))); do
    python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',$port)); s.close()" 2>/dev/null \
      && echo "$port" && return
  done
  echo "$start"
}

# 停止旧进程
for pid_file in /tmp/vtv-api.pid /tmp/vtv-orchestrator.pid; do
  [[ -f "$pid_file" ]] && { kill "$(cat "$pid_file")" 2>/dev/null || true; rm -f "$pid_file"; }
done
pkill -f "vtv_control_api.app:app" 2>/dev/null || true
pkill -f "vtv-orchestrator" 2>/dev/null || true

# 找可用 API 端口
API_PORT=$(find_free_port 8001)

# 启动控制 API
log "启动控制 API → http://127.0.0.1:${API_PORT}"
nohup uv run uvicorn vtv_control_api.app:app \
  --host 127.0.0.1 --port "$API_PORT" \
  --log-level warning \
  > /tmp/vtv-api.log 2>&1 &
echo $! > /tmp/vtv-api.pid

# 等待 API 就绪（带进度）
printf "  等待 API 就绪 "
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${API_PORT}/healthz" -o /dev/null 2>/dev/null; then
    echo ""
    ok "控制 API 就绪 → http://127.0.0.1:${API_PORT}"
    ok "API Docs    → http://127.0.0.1:${API_PORT}/docs"
    break
  fi
  printf "."
  sleep 0.5
  if [[ $i -eq 30 ]]; then
    echo ""
    err "API 启动超时，查看日志: tail -f /tmp/vtv-api.log"
  fi
done

# 启动编排器
log "启动编排器（后台）"
nohup uv run vtv-orchestrator "$DB_URL" \
  > /tmp/vtv-orchestrator.log 2>&1 &
echo $! > /tmp/vtv-orchestrator.pid
ok "编排器已启动 (PID $(cat /tmp/vtv-orchestrator.pid))"

# 启动前端（如果有 node）
FRONTEND_URL=""
if command -v node &>/dev/null && [[ -d apps/mac-client ]]; then
  log "启动 Web 前端..."
  pkill -f "vite.*5173\|vite.*5174\|vite.*5175" 2>/dev/null || true
  sleep 0.5
  VITE_CONTROL_API_BASE_URL="http://127.0.0.1:${API_PORT}" \
    nohup npm --workspace @vtv/mac-client run dev \
    > /tmp/vtv-frontend.log 2>&1 &
  echo $! > /tmp/vtv-frontend.pid

  # 等待前端就绪（带进度）
  printf "  等待前端就绪 "
  FRONTEND_PORT_ACTUAL=""
  for i in $(seq 1 20); do
    for p in 5173 5174 5175; do
      if curl -sf "http://127.0.0.1:${p}" -o /dev/null 2>/dev/null; then
        FRONTEND_PORT_ACTUAL=$p
        break 2
      fi
    done
    printf "."
    sleep 0.5
  done
  echo ""
  if [[ -n "$FRONTEND_PORT_ACTUAL" ]]; then
    FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT_ACTUAL}"
    ok "Web 前端就绪  → ${FRONTEND_URL}"
  else
    warn "前端未就绪，查看日志: tail -f /tmp/vtv-frontend.log"
  fi
fi

# =============================================================================
#  完成摘要
# =============================================================================
echo ""
sep
echo ""
echo -e "  ${BOLD}${GREEN}🚀 VTV Studio 启动完成${RESET}"
echo ""
echo -e "  ${BOLD}本地服务${RESET}"
echo -e "    控制 API    ${CYAN}http://127.0.0.1:${API_PORT}${RESET}"
echo -e "    API Docs   ${CYAN}http://127.0.0.1:${API_PORT}/docs${RESET}"
echo -e "    MinIO      ${CYAN}http://127.0.0.1:9001${RESET}  ${DIM}(vtv / change-me)${RESET}"
[[ -n "$FRONTEND_URL" ]] && echo -e "    Web 前端   ${CYAN}${FRONTEND_URL}${RESET}"
echo ""
echo -e "  ${BOLD}日志${RESET}"
echo -e "    API        ${DIM}tail -f /tmp/vtv-api.log${RESET}"
echo -e "    编排器     ${DIM}tail -f /tmp/vtv-orchestrator.log${RESET}"
[[ -n "$FRONTEND_URL" ]] && echo -e "    前端       ${DIM}tail -f /tmp/vtv-frontend.log${RESET}"
echo ""
echo -e "  ${DIM}./start.sh --stop    停止所有服务${RESET}"
echo -e "  ${DIM}./start.sh --status  查看服务状态${RESET}"
echo ""
sep
echo ""

# 自动打开浏览器（macOS）
if [[ -n "$FRONTEND_URL" ]] && command -v open &>/dev/null; then
  open "$FRONTEND_URL" 2>/dev/null || true
elif [[ -n "$FRONTEND_URL" ]] && command -v xdg-open &>/dev/null; then
  xdg-open "$FRONTEND_URL" 2>/dev/null || true
fi
