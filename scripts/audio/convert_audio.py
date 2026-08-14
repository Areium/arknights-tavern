# -*- coding: utf-8 -*-
"""任意音频 → 干净 wav/mp3（44.1k/16bit，去元数据）。
用法: python convert_audio.py <输入> <输出.mp3|.wav>
"""
import sys, subprocess, os

FF = r"D:\Program\Environment\miniconda3\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"

def main():
    src, out = sys.argv[1], sys.argv[2]
    codec = "pcm_s16le" if out.lower().endswith(".wav") else "libmp3lame"
    extra = [] if out.lower().endswith(".wav") else ["-q:a", "2", "-id3v2_version", "3", "-write_xing", "1"]
    r = subprocess.run([FF, "-y", "-i", src, "-map_metadata", "-1", "-ac", "2", "-ar", "44100",
                        "-c:a", codec, *extra, out], capture_output=True)
    if r.returncode != 0:
        print("失败:", (r.stderr or b"").decode("utf-8", "replace")[-500:]); return 1
    print("完成:", out, round(os.path.getsize(out)/1048576, 2), "MB")

if __name__ == "__main__":
    main()
