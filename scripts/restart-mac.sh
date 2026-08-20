#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════
#  Arknights Tavern — macOS 一键重启脚本
#  1. 检查依赖（Python 包 / Node 模块）
#  2. 停止旧进程（Flask + Vite）
#  3. 启动 Flask 后端 + Vite 前端
#  4. Ctrl+C 时自动清理所有进程
# ═══════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python3"
PID_FILE="$PROJECT_DIR/.dev-pids"
FLOG="/tmp/arknights-flask.log"
VLOG="/tmp/arknights-vite.log"

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "  ${CYAN}═══════════════════════════════════════${NC}"
echo -e "  ${CYAN}  Arknights Tavern — 重启前后端${NC}"
echo -e "  ${CYAN}═══════════════════════════════════════${NC}"
echo ""

# ── 0. 前置检查 ──
echo -e "  ${YELLOW}●${NC} 检查运行环境..."

if [ ! -f "$VENV_PYTHON" ]; then
  echo -e "  ${RED}✗ .venv 不存在，请先创建虚拟环境: python3 -m venv .venv${NC}"
  exit 1
fi

# 检查关键 Python 依赖
MISSING_PKGS=""
for pkg in flask flask_cors frontmatter yaml PIL httpx chromadb; do
  if ! "$VENV_PYTHON" -c "import $pkg" 2>/dev/null; then
    MISSING_PKGS="$MISSING_PKGS $pkg"
  fi
done
if [ -n "$MISSING_PKGS" ]; then
  echo -e "  ${YELLOW}⚠ 缺少 Python 包:${MISSING_PKGS}${NC}"
  echo -e "  ${YELLOW}  正在安装...${NC}"
  "$VENV_PYTHON" -m pip install -q -r "$PROJECT_DIR/requirements.txt" || {
    echo -e "  ${RED}✗ 安装失败，请手动运行: pip install -r requirements.txt${NC}"
    exit 1
  }
  echo -e "  ${GREEN}✓ 依赖安装完成${NC}"
else
  echo -e "  ${GREEN}✓ Python 依赖完整${NC}"
fi

# 检查 Node 模块
if [ ! -d "$PROJECT_DIR/frontend/node_modules" ]; then
  echo -e "  ${YELLOW}⚠ 缺少 Node 模块，正在安装...${NC}"
  cd "$PROJECT_DIR/frontend" && npm install --silent && cd "$PROJECT_DIR"
fi
echo -e "  ${GREEN}✓ Node 模块就绪${NC}"
echo ""

# ── 1. 停止旧进程 ──
echo -e "  ${YELLOW}●${NC} 停止旧进程..."

# 仅杀掉本项目目录相关的 Python 进程（避免误杀其他项目）
if [ -f "$PID_FILE" ]; then
  while IFS= read -r pid; do
    kill "$pid" 2>/dev/null || true
  done < "$PID_FILE"
  rm -f "$PID_FILE"
fi

# 清理占用端口的进程
for port in 5000 5173; do
  pids=$(lsof -ti tcp:$port 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
done
sleep 1
echo -e "  ${GREEN}✓ 端口 5000/5173 已释放${NC}"
echo ""

# ── 2. 启动 Flask ──
echo -e "  ${YELLOW}●${NC} 启动 Flask 后端..."
cd "$PROJECT_DIR"
"$VENV_PYTHON" "$PROJECT_DIR/src/app.py" > "$FLOG" 2>&1 &
FLASK_PID=$!
echo "$FLASK_PID" > "$PID_FILE"

# 等待就绪（最多 30 秒）
for i in $(seq 1 30); do
  if curl -s --connect-timeout 1 http://127.0.0.1:5000/api/status > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Flask 已就绪${NC} (PID $FLASK_PID, http://127.0.0.1:5000)"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo -e "  ${RED}✗ Flask 启动超时${NC}，末 5 行日志:"
    echo "  ─────"
    tail -5 "$FLOG" 2>/dev/null | sed 's/^/  │ /'
    echo "  ─────"
    exit 1
  fi
  sleep 1
done
echo ""

# ── 3. 启动 Vite ──
echo -e "  ${YELLOW}●${NC} 启动 Vite 前端..."
cd "$PROJECT_DIR/frontend"
npx vite --port 5173 > "$VLOG" 2>&1 &
VITE_PID=$!
echo "$VITE_PID" >> "$PID_FILE"

# 等待就绪（最多 30 秒）
for i in $(seq 1 30); do
  if curl -s --connect-timeout 1 http://localhost:5173 > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Vite 已就绪${NC} (PID $VITE_PID, http://localhost:5173)"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo -e "  ${RED}✗ Vite 启动超时${NC}，末 5 行日志:"
    echo "  ─────"
    tail -5 "$VLOG" 2>/dev/null | sed 's/^/  │ /'
    echo "  ─────"
    exit 1
  fi
  sleep 1
done
cd "$PROJECT_DIR"
echo ""

echo -e "  ${CYAN}═══════════════════════════════════════${NC}"
echo -e "  ${GREEN}启动完成！${NC}"
echo -e "    Flask  : http://127.0.0.1:5000"
echo -e "    Vite   : http://localhost:5173"
echo -e "    日志   : $FLOG"
echo -e "             $VLOG"
echo -e "  ${CYAN}═══════════════════════════════════════${NC}"
echo ""

open http://localhost:5173 2>/dev/null || true

# ── 清理函数（Ctrl+C 时触发）──
cleanup() {
  echo ""
  echo -e "  ${YELLOW}⏹  正在停止...${NC}"
  if [ -f "$PID_FILE" ]; then
    while IFS= read -r pid; do
      kill "$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
  echo -e "  ${GREEN}✓ 已停止${NC}"
  exit 0
}

trap cleanup SIGINT SIGTERM
wait
