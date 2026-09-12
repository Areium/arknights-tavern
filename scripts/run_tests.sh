#!/usr/bin/env bash
# 统一测试入口：pytest 用例（tests/ + 无外部依赖的 perf_tests）+ 脚本式集成检查。
#
#   bash scripts/run_tests.sh              # 全部
#   bash scripts/run_tests.sh --pytest-only
#   bash scripts/run_tests.sh --legacy-only
#
# 脚本式检查位于 tests/legacy/（历史上是 test_*.py，import 即执行并 sys.exit，
# 会被 pytest 收集器当成内部错误，故移出收集路径，由本脚本显式调用）。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# perf_tests 下无网络/LLM 依赖的战斗与结算用例（嵌入/记忆/前缀缓存类需外部服务，不入网）
PERF_TESTS=(
  perf_tests/test_combat_runtime_v1.py
  perf_tests/test_combat_data_v1.py
  perf_tests/test_settlement_v1.py
  perf_tests/test_card_json_roundtrip.py
  perf_tests/test_cv_budget.py
)

RUN_PYTEST=1
RUN_LEGACY=1
for arg in "$@"; do
  case "$arg" in
    --pytest-only) RUN_LEGACY=0 ;;
    --legacy-only) RUN_PYTEST=0 ;;
    *) echo "未知参数: $arg"; exit 2 ;;
  esac
done

PY="${PYTHON:-python3}"
failed=0

if [ "$RUN_PYTEST" = "1" ]; then
  echo "== pytest: tests/ =="
  "$PY" -m pytest tests/ || failed=1
  echo "== pytest: perf_tests（无外部依赖子集）=="
  "$PY" -m pytest "${PERF_TESTS[@]}" || failed=1
fi

if [ "$RUN_LEGACY" = "1" ]; then
  for script in tests/legacy/*.py; do
    [ -e "$script" ] || continue
    echo "== legacy: $script =="
    # 脚本按 src/ 在 sys.path 上编写；移动目录后由 runner 提供 PYTHONPATH
    PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PY" "$script" || failed=1
  done
fi

if [ "$failed" = "0" ]; then
  echo "全部通过"
else
  echo "存在失败项"
fi
exit "$failed"
