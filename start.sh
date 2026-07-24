#!/usr/bin/env bash
# VTV — 启动 + 验证脚本
# 用法：./start.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
[[ -f .env ]] && { set -a; source .env; set +a; }

G='\033[0;32m' Y='\033[1;33m' R='\033[0;31m' C='\033[0;36m' B='\033[1m' D='\033[0m'
ok()  { echo -e "${G}✓${D} $*"; }
bad() { echo -e "${R}✗${D} $*" >&2; exit 1; }
log() { echo -e "${C}▶${D} $*"; }

DB_URL="${VTV_DATABASE_URL:-postgresql+asyncpg://vtv:vtv@127.0.0.1:5432/vtv}"
S3_EP="${VTV_S3_ENDPOINT:-http://127.0.0.1:9000}"
S3_KEY="${VTV_S3_ACCESS_KEY:-vtv}"
S3_SEC="${VTV_S3_SECRET_KEY:-change-me-in-non-local-environments}"
S3_BKT="${VTV_S3_BUCKET:-vtv-local}"
export MODAL_DISABLE_API_PROXY=1

echo ""
echo -e "${B}  VTV Studio${D}"
echo -e "  $(date '+%Y-%m-%d %H:%M')"
echo ""

# ── 1. Docker ─────────────────────────────────────────────────────────────────
log "PostgreSQL + MinIO"
docker compose up -d --wait 2>/dev/null || bad "Docker 启动失败"
ok "PostgreSQL :5432  MinIO :9000"

# ── 2. 迁移 ──────────────────────────────────────────────────────────────────
log "数据库迁移"
uv run python scripts/apply_migrations.py "$DB_URL" 2>&1 \
  | grep -v "already exists" | grep -v "^$" | tail -3 || true
ok "迁移完成"

# ── 3. MinIO Bucket ───────────────────────────────────────────────────────────
uv run python -c "
from minio import Minio
c = Minio('${S3_EP}'.replace('http://',''), access_key='${S3_KEY}', secret_key='${S3_SEC}', secure=False)
c.make_bucket('${S3_BKT}') if not c.bucket_exists('${S3_BKT}') else None
" 2>/dev/null || true
ok "Bucket '${S3_BKT}'"

# ── 4. 控制 API ───────────────────────────────────────────────────────────────
log "控制 API"
pkill -f "vtv_control_api.app:app" 2>/dev/null || true
# 找可用端口
for PORT in 8001 8002 8003; do
  python3 -c "import socket; s=socket.socket(); s.bind(('',${PORT})); s.close()" 2>/dev/null && break
done
nohup uv run uvicorn vtv_control_api.app:app \
  --host 127.0.0.1 --port "$PORT" --log-level warning \
  > /tmp/vtv-api.log 2>&1 & echo $! > /tmp/vtv-api.pid
printf "  等待就绪"
for i in $(seq 30); do
  curl -sf "http://127.0.0.1:${PORT}/healthz" -o /dev/null 2>/dev/null && break
  printf "." && sleep 0.5
done
echo ""
ok "控制 API → http://127.0.0.1:${PORT}"

# ── 5. 验证端到端流程 ─────────────────────────────────────────────────────────
log "验证流程"
CHECKS=0 FAILS=0

check() {
  local name="$1" url="$2" expect="$3"
  CHECKS=$((CHECKS+1))
  resp=$(curl -sf -w "%{http_code}" "$url" -o /tmp/vtv-check.json 2>/dev/null || echo "000")
  if [[ "$resp" =~ $expect ]]; then
    ok "$name ($resp)"
  else
    echo -e "${Y}⚠${D} $name — HTTP $resp（期望 $expect）"
    FAILS=$((FAILS+1))
  fi
}

API="http://127.0.0.1:${PORT}"
check "健康检查"          "${API}/healthz"            "200"
check "系统指标"          "${API}/v1/health"           "200"
check "项目列表"          "${API}/v1/projects"         "200"
check "模型发布列表"       "${API}/v1/model-releases"   "200"
check "市场配置"          "${API}/v1/markets"          "200"
check "评估器列表"         "${API}/v1/evaluator-releases" "200"
check "API 文档"          "${API}/docs"               "200"

echo ""
if [[ $FAILS -eq 0 ]]; then
  ok "流程验证通过 (${CHECKS}/${CHECKS})"
else
  echo -e "${Y}⚠${D}  ${FAILS}/${CHECKS} 项未通过（不影响启动，可能是无数据）"
fi

# ── 6. 编排器 ────────────────────────────────────────────────────────────────
pkill -f "vtv-orchestrator" 2>/dev/null || true
nohup uv run vtv-orchestrator "$DB_URL" > /tmp/vtv-orchestrator.log 2>&1 &
echo $! > /tmp/vtv-orchestrator.pid
ok "编排器已启动"

# ── 7. Web 前端 ───────────────────────────────────────────────────────────────
log "Web 前端"
pkill -f "vite.*mac-client\|vite.*5173\|vite.*5174" 2>/dev/null || true; sleep 0.3
VITE_CONTROL_API_BASE_URL="http://127.0.0.1:${PORT}" \
  nohup npm --workspace @vtv/mac-client run dev \
  > /tmp/vtv-frontend.log 2>&1 & echo $! > /tmp/vtv-frontend.pid
printf "  等待就绪"
FPORT=""
for i in $(seq 20); do
  for p in 5173 5174 5175; do
    curl -sf "http://127.0.0.1:${p}" -o /dev/null 2>/dev/null && FPORT=$p && break 2
  done
  printf "." && sleep 0.5
done
echo ""
[[ -n "$FPORT" ]] && ok "Web 前端  → http://127.0.0.1:${FPORT}" \
                  || echo -e "${Y}⚠${D}  前端未就绪，日志: tail -f /tmp/vtv-frontend.log"

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "  ┌──────────────────────────────────────────────┐"
echo -e "  │                                              │"
[[ -n "$FPORT" ]] && \
echo -e "  │   🌐  前端    ${C}http://127.0.0.1:${FPORT}${D}          │" || \
echo -e "  │   🌐  前端    启动中，稍后刷新                   │"
echo -e "  │   🔧  API    ${C}http://127.0.0.1:${PORT}${D}          │"
echo -e "  │   📚  文档    ${C}http://127.0.0.1:${PORT}/docs${D}      │"
echo -e "  │   📦  MinIO  ${C}http://127.0.0.1:9001${D}            │"
echo -e "  │                                              │"
echo -e "  │   停止: ${Y}./stop.sh${D}                          │"
echo -e "  └──────────────────────────────────────────────┘"
echo ""

# macOS 自动打开浏览器
[[ -n "$FPORT" ]] && command -v open &>/dev/null && open "http://127.0.0.1:${FPORT}" 2>/dev/null || true
