#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════
#  Arknights Tavern — macOS 一键重启脚本
#  1. 检查依赖（Python 包 / Node 模块）
#  2. 停止旧进程（Flask + Vite）
#  3. 启动 Flask 后端 + Vite 前端（Electron 游戏窗口由 vite-plugin-electron 拉起）
#  4. 关闭游戏窗口 / Ctrl+C / 脚本异常退出 → 自动清理整棵进程树并退出
#
#  本次修改只动「启动与清理逻辑」：依赖检查、端口、日志文件、启动命令、
#  浏览器自动打开行为均保持不变。
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

FLASK_PID=""
VITE_PID=""
CLEANED=0

# ── 取直接子进程（优先 pgrep，缺失时回退 ps -ef 解析；macOS 两者都可用）──
children_of() {
  local pid="$1"
  if command -v pgrep >/dev/null 2>&1; then
    pgrep -P "$pid" 2>/dev/null || true
  else
    ps -ef 2>/dev/null | awk -v p="$pid" '$3 == p { print $2 }'
  fi
}

# ── 结束整棵进程树 ──
# npx → node(vite) → electron 是多层子进程，只 kill 顶层 PID 会留下 Electron 窗口。
kill_tree() {
  local pid="$1" sig="${2:-TERM}" kid
  [ -z "$pid" ] && return 0
  for kid in $(children_of "$pid"); do
    kill_tree "$kid" "$sig"
  done
  kill -"$sig" "$pid" 2>/dev/null || true
}

# ── 清理函数 ──
# 挂到 EXIT/INT/TERM 上，因此「正常关游戏窗口」「Ctrl+C」「脚本报错退出」都会执行。
cleanup() {
  local code=$?
  if [ "$CLEANED" = "1" ]; then return 0; fi
  CLEANED=1
  trap - EXIT INT TERM

  echo ""
  echo -e "  ${YELLOW}⏹  正在停止...${NC}"

  # 1) 先温和终止整棵树
  for pid in "$VITE_PID" "$FLASK_PID"; do
    if [ -n "$pid" ]; then kill_tree "$pid" TERM; fi
  done
  if [ -f "$PID_FILE" ]; then
    while IFS= read -r pid; do
      if [ -n "$pid" ]; then kill_tree "$pid" TERM; fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi

  sleep 1

  # 2) 仍未退出的强杀
  for pid in "$VITE_PID" "$FLASK_PID"; do
    if [ -n "$pid" ]; then kill_tree "$pid" KILL; fi
  done

  # 3) 兜底：端口占用者 + 本项目内的 Electron
  for port in 5000 5173; do
    local pids
    pids=$(lsof -ti tcp:$port 2>/dev/null || true)
    if [ -n "$pids" ]; then
      echo "$pids" | xargs kill -9 2>/dev/null || true
    fi
  done
  pkill -f "$PROJECT_DIR/frontend/node_modules/electron" 2>/dev/null || true

  echo -e "  ${GREEN}✓ 已停止${NC}"
  exit "$code"
}

# 尽早挂上，避免「启动阶段按 Ctrl+C」时进程残留（旧版在最后才 trap）
trap cleanup EXIT INT TERM

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
    if [ -n "$pid" ]; then kill_tree "$pid" TERM; fi
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

# ── 3. 启动 Vite（vite-plugin-electron 会拉起 Electron 游戏窗口）──
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
echo -e "    关闭游戏窗口或按 Ctrl+C 即自动清理并退出"
echo -e "  ${CYAN}═══════════════════════════════════════${NC}"
echo ""

open http://localhost:5173 2>/dev/null || true

# ── 4. 等待关键进程结束 ──
# 前端退出 = Electron 游戏窗口被关闭（vite-plugin-electron 在 Electron 退出时
# 会调用 process.exit），此时主动结束脚本，终端随之释放；
# 旧版用 `wait` 会一直等 Flask，导致关掉游戏窗口后终端窗口不会退出。
while :; do
  if ! kill -0 "$VITE_PID" 2>/dev/null; then
    echo -e "  ${GREEN}✓ 前端已退出（游戏窗口已关闭）${NC}"
    break
  fi
  if ! kill -0 "$FLASK_PID" 2>/dev/null; then
    echo -e "  ${YELLOW}⚠ 后端已退出${NC}"
    break
  fi
  sleep 1
done
