#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_mci.py —— 验证 MCI 播放后端能否真的放真实音频

用三类真实文件测：
  1. 系统自带 WAV（基线）
  2. 用户磁盘上的真实 MP3（320 kbps，主要用例）
  3. 从真实 NCM 解密出来的 MP3
"""
import builtins
import io
import pathlib
import sys
import time

_buf = io.StringIO()
_rp = builtins.print


def print(*a, **k):          # noqa: A001
    k["file"] = _buf
    return _rp(*a, **k)


HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ncm_audio

print("=" * 78)
print("MCI 播放后端测试")
print("=" * 78)

MP3_DIR = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload")
candidates = [
    ("系统 WAV", pathlib.Path(r"C:\Windows\Media\Alarm01.wav")),
    ("真实 MP3", None),
    ("NCM 解密出的 MP3", HERE / "real-samples" / "Wake (Studio).mp3"),
]
mp3s = sorted(MP3_DIR.glob("*.mp3")) if MP3_DIR.exists() else []
if mp3s:
    candidates[1] = ("真实 MP3", mp3s[0])


def probe(label, path, do_seek=True):
    print()
    print("-" * 78)
    print(f"[{label}] {path}")
    print("-" * 78)
    if path is None or not pathlib.Path(path).exists():
        print("  文件不存在，跳过")
        return None
    size = pathlib.Path(path).stat().st_size
    print(f"  文件大小: {size} 字节 ({size / 1024 / 1024:.1f} MB)")

    p = ncm_audio.MciPlayer()
    t0 = time.time()
    ok = p.open(path)
    dt = time.time() - t0
    print(f"  open(): {ok}  耗时 {dt * 1000:.0f} ms")
    if not ok:
        print(f"    错误: {p.last_error}")
        return None

    dur = p.duration_ms()
    print(f"  时长: {dur} ms  ({dur / 1000:.1f} 秒)")
    print(f"  初始 mode: {p.mode()!r}")
    print(f"  初始 position: {p.position_ms()} ms")

    print("  play() ->", p.play())
    time.sleep(0.9)
    m = p.mode()
    pos1 = p.position_ms()
    print(f"  0.9 秒后 mode={m!r} position={pos1} ms")
    time.sleep(1.0)
    pos2 = p.position_ms()
    print(f"  再等 1 秒 position={pos2} ms   （应明显增大）")
    advancing = pos2 > pos1

    print("  pause() ->", p.pause())
    time.sleep(0.35)
    mode_p = p.mode()
    pos3 = p.position_ms()
    time.sleep(0.5)
    pos4 = p.position_ms()
    print(f"  pause 后 mode={mode_p!r} position {pos3} -> {pos4}  （应基本不变）")
    paused_ok = mode_p == "paused" and abs(pos4 - pos3) < 120

    print("  play() 恢复 ->", p.play())
    time.sleep(0.6)
    print(f"  恢复后 mode={p.mode()!r} position={p.position_ms()} ms")

    seek_ok = None
    if do_seek and dur > 20000:
        target = dur // 2
        print(f"  seek_ms({target}) ->", p.seek_ms(target))
        time.sleep(0.5)
        after = p.position_ms()
        seek_ok = abs(after - target) < 2000
        print(f"  seek 后 position={after} ms  （目标 {target}，偏差 {abs(after - target)}）")

    print("  set_volume(0.25) ->", p.set_volume(0.25))
    print("  set_volume(0.9)  ->", p.set_volume(0.9))

    print("  stop() ->", p.stop())
    time.sleep(0.3)
    print(f"  stop 后 mode={p.mode()!r} position={p.position_ms()} ms")

    p.close()
    print(f"  close() 完成，is_open={p.is_open}")

    return {"advancing": advancing, "paused_ok": paused_ok, "seek_ok": seek_ok,
            "duration": dur}


results = {}
for label, path in candidates:
    results[label] = probe(label, path)

print()
print("=" * 78)
print("结论")
print("=" * 78)
for label, r in results.items():
    if r is None:
        print(f"  {label:<22} 未能打开")
        continue
    print(f"  {label:<22} 时长 {r['duration'] / 1000:>6.1f}s   "
          f"播放推进={r['advancing']}  暂停有效={r['paused_ok']}  "
          f"跳转={'N/A' if r['seek_ok'] is None else r['seek_ok']}")

pathlib.Path("mci-report.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp("报告 -> mci-report.txt")
