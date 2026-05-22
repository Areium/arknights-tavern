#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "============================================"
echo "  Arknights Txt — 重启前后端"
echo "============================================"
echo ""

# ── 1. 停止旧进程 ──
echo "[1/3] 正在停止旧进程..."

kill_port() {
    local port=$1 name=$2
    local pid=""
    if command -v lsof &>/dev/null; then
        pid=$(lsof -ti:"$port" 2>/dev/null || true)
    elif command -v netstat &>/dev/null; then
        pid=$(netstat -ano 2>/dev/null | grep ":$port" | grep LISTENING | awk '{print $5}' | head -1)
    fi
    if [ -n "$pid" ]; then
        if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
            taskkill //F //PID "$pid" 2>/dev/null || true
        else
            kill -9 "$pid" 2>/dev/null || true
        fi
        echo "  已停止 PID $pid ($name :$port)"
    fi
}

kill_port 5000 "Flask"
kill_port 5173 "Vite"

# Windows 下额外清理
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    taskkill //F //IM python.exe 2>/dev/null || true
fi

echo "  旧进程已清理"
echo ""

# ── 2. 启动 Flask ──
echo "[2/3] 启动 Flask 后端..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    # Git Bash on Windows
    start "Flask Backend" cmd //k "cd /d "$PROJECT_DIR" && python src/app.py"
else
    python "$PROJECT_DIR/src/app.py" &
fi
echo "  Flask 已启动 (http://127.0.0.1:5000)"
echo ""

# ── 3. 启动 Vite ──
echo "[3/3] 启动 Vite 前端..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    start "Vite Frontend" cmd //k "cd /d "$PROJECT_DIR\\frontend" && npm run dev"
else
    (cd "$PROJECT_DIR/frontend" && npm run dev) &
fi
echo "  Vite 已启动 (http://localhost:5173)"
echo ""

echo "============================================"
echo "  启动完成！等待窗口加载后访问："
echo "    http://localhost:5173"
echo "============================================"
