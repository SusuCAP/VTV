#!/usr/bin/env bash
# VTV — 停止脚本
cd "$(dirname "${BASH_SOURCE[0]}")"
G='\033[0;32m' D='\033[0m'; ok() { echo -e "${G}✓${D} $*"; }

for f in /tmp/vtv-api.pid /tmp/vtv-orchestrator.pid /tmp/vtv-frontend.pid; do
  [[ -f $f ]] && { kill "$(cat $f)" 2>/dev/null; rm -f $f; ok "停止 $(basename $f .pid)"; }
done
pkill -f "vtv_control_api.app:app" 2>/dev/null || true
pkill -f "vtv-orchestrator" 2>/dev/null || true
pkill -f "vite.*mac-client" 2>/dev/null || true
docker compose stop 2>/dev/null && ok "Docker 已停止"
echo "done"
