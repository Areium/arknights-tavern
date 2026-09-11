# -*- coding: utf-8 -*-
r"""Windows WASAPI 回环录音：录下系统正在播放的声音（含浏览器）。
用法: python record_loopback.py <秒数> <输出路径>
例:   python record_loopback.py 150 D:\CloudMusic\mureka_song1.wav
"""
import sys, time, wave
import pyaudiowpatch as pyaudio

def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    out = sys.argv[2] if len(sys.argv) > 2 else "loopback.wav"
    p = pyaudio.PyAudio()
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    except Exception as e:
        print("无 WASAPI 主机:", e); p.terminate(); return 1
    default = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    dev = None
    if not default.get("isLoopbackDevice"):
        for lo in p.get_loopback_device_info_generator():
            if default["name"] in lo["name"]:
                dev = lo; break
    if dev is None:
        print("未找到回环设备，请用: python record_loopback.py --list 查看设备")
        p.terminate(); return 1
    print("录制设备:", dev["name"])
    print(f"开始录制 {dur:.0f} 秒 -> {out}  （现在去播放歌曲！）")
    stream = p.open(format=pyaudio.paInt16, channels=2, rate=int(dev["defaultSampleRate"]),
                    input=True, input_device_index=dev["index"])
    frames = []
    end = time.time() + dur
    try:
        while time.time() < end:
            frames.append(stream.read(int(dev["defaultSampleRate"] * 0.25)))
    finally:
        stream.stop_stream(); stream.close(); p.terminate()
    data = b"".join(frames)
    with wave.open(out, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(int(dev["defaultSampleRate"]))
        w.writeframes(data)
    print("完成:", out, round(len(data)/1048576, 1), "MB")

if __name__ == "__main__":
    main()
