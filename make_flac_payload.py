#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_flac_payload.py —— 造一个「结构合法」的最小 FLAC，用来测试 FLAC 标签写入

之前 selftest.js 造的是 `fLaC` + 随机字节，mutagen 根本解析不了，
所以测不到 FLAC 标签路径。这里按 FLAC 规范真正拼一个 STREAMINFO 块。

用法: python make_flac_payload.py <输出.flac>
"""
import pathlib
import struct
import sys


def build_flac(total_samples=44100 * 10, sample_rate=44100, channels=2, bps=16,
               frame_bytes=200000):
    out = bytearray(b"fLaC")

    # ── METADATA_BLOCK_HEADER: 1 bit last + 7 bit type(=0 STREAMINFO) + 24 bit 长度 ──
    out.append(0x80 | 0x00)              # last-block = 1, type = STREAMINFO
    out += (34).to_bytes(3, "big")

    # ── STREAMINFO (34 字节) ──
    si = bytearray()
    si += struct.pack(">HH", 4096, 4096)          # min / max block size
    si += (0).to_bytes(3, "big")                  # min frame size
    si += (0).to_bytes(3, "big")                  # max frame size
    # 20 bit 采样率 | 3 bit (声道数-1) | 5 bit (位深-1) | 36 bit 总采样数
    packed = (sample_rate << 44) | ((channels - 1) << 41) | ((bps - 1) << 36) | total_samples
    si += packed.to_bytes(8, "big")
    si += bytes(16)                               # MD5（全 0 = 未提供）
    assert len(si) == 34, len(si)
    out += si

    # ── 之后是音频帧。这里不需要真的能解码，只要有内容让文件成立 ──
    out += bytes((i * 7 + 13) & 0xFF for i in range(frame_bytes))
    return bytes(out)


if __name__ == "__main__":
    dest = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "payload.flac")
    data = build_flac()
    dest.write_bytes(data)
    print(f"写出 {dest} ({len(data)} 字节)")

    # 自检：mutagen 必须能打开并成功写入标签
    sys.path.insert(0, str(pathlib.Path(__file__).parent / "runtime"))
    import os
    rt = pathlib.Path(__file__).parent / "runtime"
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(rt))
        except OSError:
            pass
    from mutagen.flac import FLAC, Picture

    f = FLAC(dest)
    f["artist"] = ["测试艺术家"]
    f["title"] = ["测试标题"]
    pic = Picture()
    pic.type = 3
    pic.mime = "image/jpeg"
    pic.data = b"\xff\xd8\xff" + bytes(100) + b"\xff\xd9"
    f.add_picture(pic)
    f.save()
    print("mutagen 读写自检: OK")

    f2 = FLAC(dest)
    print("  回读 artist =", f2.get("artist"), "| pictures =", len(f2.pictures),
          "| 时长 =", round(f2.info.length, 2), "秒")
