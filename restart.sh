#!/usr/bin/env bash
# 一键重启前后端（Git Bash / Linux / macOS 通用）。
#   用法：
#     ./restart.sh           # live 模式（读仓库根 .env 的模型三件套）
#     ./restart.sh mock      # 强制本地 mock 降级（不需要 Key）
#   端口可用环境变量覆盖：BACKEND_PORT=8001 ./restart.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
MODE="${1:-live}"

stop_port() {
  local pid
  pid="$(netstat -ano 2>/dev/null | grep ":$1 " | grep LISTEN | awk '{print $5}' | head -1)"
  if [ -n "$pid" ]; then
    echo "[stop] killing PID $pid on port $1"
    taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null || true
  fi
}

echo "=== restarting kbqa: backend=:$BACKEND_PORT frontend=:$FRONTEND_PORT mode=$MODE ==="

stop_port "$BACKEND_PORT"
stop_port "$FRONTEND_PORT"

echo "[backend] starting (port $BACKEND_PORT, mode $MODE) ..."
if [ "$MODE" = "mock" ]; then
  ( cd "$ROOT/starter" && ENV_FILE= LLM_BASE_URL= LLM_API_KEY= LLM_MODEL= \
      .venv/Scripts/python.exe -m uvicorn kbqa.server:app --host 127.0.0.1 --port "$BACKEND_PORT" ) &
else
  ( cd "$ROOT/starter" && .venv/Scripts/python.exe -m uvicorn kbqa.server:app \
      --host 127.0.0.1 --port "$BACKEND_PORT" ) &
fi

echo "[frontend] starting (port $FRONTEND_PORT) ..."
( cd "$ROOT/frontend" && VITE_API_TARGET="http://127.0.0.1:$BACKEND_PORT" \
    npm run dev -- --port "$FRONTEND_PORT" --host 127.0.0.1 --strictPort ) &

echo
echo "  backend   http://127.0.0.1:$BACKEND_PORT/api/health"
echo "  frontend  http://127.0.0.1:$FRONTEND_PORT"
echo
echo "后端起来需要几秒，首次请求前稍等。"
