import logging
import os
import sys
import threading
import time
from datetime import datetime

LOG_DIR = "logs"
_log_file = None


def setup_logging():
    """配置日志：写入 timestamped 文件，不输出到控制台。"""
    global _log_file
    os.makedirs(LOG_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file = os.path.join(LOG_DIR, f"session_{timestamp}.log")

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(_log_file, encoding="utf-8")],
    )

    # 抑制 httpx/httpcore 底层连接日志（过于冗长）
    for noisy in ("httpx", "httpcore", "httpcore.proxy", "httpcore.http11", "httpcore.connection"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return _log_file


def get_log_path() -> str:
    return _log_file or ""


# ── 实时计时器 ──

def run_with_timer(func, *args, **kwargs):
    """以实时计时器包装一个阻塞调用。

    调用期间持续显示 "正在生成会话(已用时 X.Xs)"，
    结束后清除计时行并返回函数结果。
    """
    result = [None]
    done = threading.Event()

    def worker():
        try:
            result[0] = func(*args, **kwargs)
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    start = time.time()
    while not done.is_set():
        elapsed = time.time() - start
        print(f"\r正在生成会话(已用时 {elapsed:.1f}s)", end="", flush=True)
        time.sleep(0.1)

    # 清除计时行
    print("\r" + " " * 55 + "\r", end="", flush=True)
    return result[0]
