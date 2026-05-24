#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════
#  Arknights Tavern — macOS 一键重启脚本
#  1. 停止旧进程（Flask + Vite + Electron）
#  2. 启动 Flask 后端（最长等待 30s）
#  3. 启动 Vite 前端开发服务器（最长等待 30s）
# ═══════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python3"
PID_FILE="$PROJECT_DIR/.dev-pids"
FLOG="/tmp/arknights-flask.log"
VLOG="/tmp/arknights-vite.log"

cleanup() {
  echo ""
  echo "  ⏹  正在停止..."
  if [ -f "$PID_FILE" ]; then
    while IFS= read -r pid; do
      kill "$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
  lsof -ti tcp:5000 2>/dev/null | xargs kill -9 2>/dev/null || true
  lsof -ti tcp:5173 2>/dev/null | xargs kill -9 2>/dev/null || true
  echo "  ✓ 已停止"
  exit 0
}

trap cleanup SIGINT SIGTERM

echo ""
echo "  ═══════════════════════════════════════"
echo "    Arknights Tavern — 重启前后端"
echo "  ═══════════════════════════════════════"
echo ""

# ── 1. 停止旧进程 ──
echo "  ● 停止旧进程..."
lsof -ti tcp:5000 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti tcp:5173 2>/dev/null | xargs kill -9 2>/dev/null || true
pkill -f "python.*app.py" 2>/dev/null || true
sleep 1
echo "  ✓ 端口 5000/5173 已释放"
echo ""

# ── 2. 启动 Flask ──
echo "  ● 启动 Flask 后端..."
export FLASK_DEBUG=false
if [ -f "$PYTHON" ]; then
  nohup "$PYTHON" "$PROJECT_DIR/src/app.py" > "$FLOG" 2>&1 &
else
  nohup python3 "$PROJECT_DIR/src/app.py" > "$FLOG" 2>&1 &
fi
FLASK_PID=$!
echo "$FLASK_PID" > "$PID_FILE"

# 等待就绪（最多 30 秒）
echo -n "  "
for i in $(seq 1 30); do
  if curl -s --connect-timeout 1 http://127.0.0.1:5000/api/status > /dev/null 2>&1; then
    echo ""
    echo "  ✓ Flask 已就绪 (PID $FLASK_PID, http://127.0.0.1:5000)"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo ""
    echo "  ✗ Flask 启动超时（30s），最后 5 行日志:"
    echo "  ─────"
    tail -5 "$FLOG" 2>/dev/null | sed 's/^/  │ /'
    echo "  ─────"
    echo "  ☞ 查看完整日志: $FLOG"
    exit 1
  fi
  echo -n "."
  sleep 1
done
echo ""

# ── 3. 启动 Vite ──
echo "  ● 启动 Vite 前端..."
cd "$PROJECT_DIR/frontend"
nohup npx vite --port 5173 > "$VLOG" 2>&1 &
VITE_PID=$!
echo "$VITE_PID" >> "$PID_FILE"

# 等待就绪（最多 30 秒）
echo -n "  "
for i in $(seq 1 30); do
  if curl -s --connect-timeout 1 http://localhost:5173 > /dev/null 2>&1; then
    echo ""
    echo "  ✓ Vite 已就绪 (PID $VITE_PID, http://localhost:5173)"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo ""
    echo "  ✗ Vite 启动超时（30s），最后 5 行日志:"
    echo "  ─────"
    tail -5 "$VLOG" 2>/dev/null | sed 's/^/  │ /'
    echo "  ─────"
    echo "  ☞ 查看完整日志: $VLOG"
    exit 1
  fi
  echo -n "."
  sleep 1
done
cd "$PROJECT_DIR"
echo ""

echo "  ═══════════════════════════════════════"
echo "   启动完成！"
echo "     Flask  : http://127.0.0.1:5000"
echo "     Vite   : http://localhost:5173"
echo "    日志    : $FLOG"
echo "              $VLOG"
echo "  ═══════════════════════════════════════"
echo ""

open http://localhost:5173 2>/dev/null || true

wait
