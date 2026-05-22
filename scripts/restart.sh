#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo "  Arknights Txt — 重启前后端"
echo "============================================"
echo ""

cd "$PROJECT_DIR"

echo "[1/3] 正在停止旧进程..."

# 杀掉占用 5000 端口的进程
if command -v lsof &>/dev/null; then
    PID_5000=$(lsof -ti:5000 2>/dev/null || true)
    if [ -n "$PID_5000" ]; then
        kill -9 $PID_5000 2>/dev/null || true
        echo "  已停止 PID $PID_5000 (Flask :5000)"
    fi
    PID_5173=$(lsof -ti:5173 2>/dev/null || true)
    if [ -n "$PID_5173" ]; then
        kill -9 $PID_5173 2>/dev/null || true
        echo "  已停止 PID $PID_5173 (Vite :5173)"
    fi
elif command -v netstat &>/dev/null; then
    # Windows Git Bash fallback
    for pid in $(netstat -ano 2>/dev/null | grep -E ':5000.*LISTENING' | awk '{print $5}'); do
        taskkill //F //PID "$pid" 2>/dev/null && echo "  已停止 PID $pid (Flask :5000)"
    done
    for pid in $(netstat -ano 2>/dev/null | grep -E ':5173.*LISTENING' | awk '{print $5}'); do
        taskkill //F //PID "$pid" 2>/dev/null && echo "  已停止 PID $pid (Vite :5173)"
    done
fi

echo "  旧进程已清理"
echo ""

echo "[2/3] 启动 Flask 后端..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    start "Flask Backend" cmd //c "cd /d $(cygpath -w "$PROJECT_DIR") && python src/app.py"
else
    osascript -e 'tell app "Terminal" to do script "cd '"$PROJECT_DIR"' && python src/app.py"' 2>/dev/null || \
    gnome-terminal -- bash -c "cd '$PROJECT_DIR' && python src/app.py; exec bash" 2>/dev/null || \
    xterm -e "cd '$PROJECT_DIR' && python src/app.py; exec bash" 2>/dev/null || \
    (python src/app.py &)
fi
echo "  Flask 已启动 (http://127.0.0.1:5000)"
echo ""

echo "[3/3] 启动 Vite 前端..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    start "Vite Frontend" cmd //c "cd /d $(cygpath -w "$PROJECT_DIR")\\frontend && npm run dev"
else
    osascript -e 'tell app "Terminal" to do script "cd '"$PROJECT_DIR"'/frontend && npm run dev"' 2>/dev/null || \
    gnome-terminal -- bash -c "cd '$PROJECT_DIR/frontend' && npm run dev; exec bash" 2>/dev/null || \
    (cd frontend && npm run dev &)
fi
echo "  Vite 已启动 (http://localhost:5173)"
echo ""

echo "============================================"
echo "  启动完成！等待窗口加载后访问："
echo "    http://localhost:5173"
echo "============================================"
