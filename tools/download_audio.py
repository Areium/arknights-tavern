#!/usr/bin/env python3
"""从 PseudoMon/arknights-audio 下载方舟战斗音效/BGM 到 data/audio/。

源仓库: https://github.com/PseudoMon/arknights-audio (global-server-voices 分支)
音频为 WAV，浏览器原生支持。脚本幂等：已存在且非空则跳过。

用法: python tools/download_audio.py
"""
import os
import sys
import urllib.request

BASE_URL = "https://raw.githubusercontent.com/PseudoMon/arknights-audio/global-server-voices/"
DEST_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "audio")

# 目标文件名 → 源仓库路径
SFX = {
    "hit": "battle/b_ui/b_ui_whoosh.wav",
    "crit": "battle/b_ui/b_ui_star.wav",
    "heal": "battle/b_char/b_char_healboost.wav",
    "shield": "battle/b_char/b_char_addshield.wav",
    "death": "battle/b_char/b_char_dead.wav",
    "enemy_death": "battle/b_enemy/b_enemy_dead_n.wav",
    "victory": "battle/b_ui/b_ui_win.wav",
    "defeat": "battle/b_ui/b_ui_lose.wav",
    "card": "battle/b_ui/b_ui_mark.wav",
    "ui": "battle/b_ui/b_ui_mark.wav",
}
BGM = {
    "combat_intro.wav": "music/a001/m_dia_farce_intro.wav",
    "combat_loop.wav": "music/a001/m_dia_farce_loop.wav",
}


def download(url: str, dest: str) -> bool:
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"  SKIP 已有 {os.path.relpath(dest)}")
        return True
    print(f"  下载 {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if not data or resp.status != 200:
            print(f"  FAIL HTTP {resp.status} {url}")
            return False
    except Exception as e:
        print(f"  FAIL {e}")
        return False
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    print(f"  OK {os.path.relpath(dest)} ({len(data)//1024}KB)")
    return True


def main():
    ok = 0
    fail = 0
    print("== SFX ==")
    for name, src in SFX.items():
        dest = os.path.join(DEST_ROOT, "sfx", f"{name}.wav")
        ok += download(BASE_URL + src, dest)
    print("== BGM ==")
    for fname, src in BGM.items():
        dest = os.path.join(DEST_ROOT, "bgm", fname)
        ok += download(BASE_URL + src, dest)
    print(f"\n完成: {ok} 成功, {fail} 失败" if fail == 0 else f"\n完成: {ok} 成功, {fail} 失败")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
