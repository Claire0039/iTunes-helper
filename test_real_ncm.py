#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_real_ncm.py —— 用用户磁盘上的【真实】网易云 NCM 文件验证解码核心

之前所有样本都是我按规范合成的；这是唯一的真实数据，也是最有价值的验证。
同时用真实的 MP3 验证标签 / 封面读取。
"""
import builtins
import io
import os
import pathlib
import sys

_buf = io.StringIO()
_rp = builtins.print


def print(*a, **k):          # noqa: A001
    k["file"] = _buf
    return _rp(*a, **k)


HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.append(str(HERE / "runtime"))
if hasattr(os, "add_dll_directory"):
    for d in (HERE / "runtime", HERE / "runtime" / "PySide6"):
        if d.is_dir():
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass

import ncm_core

REAL_NCM = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload\VipSongsDownload"
                        r"\Hillsong Young & Free - Wake (Studio).ncm")
MP3_DIR = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload")

print("=" * 78)
print("真实 NCM 文件解码")
print("=" * 78)
print(f"文件: {REAL_NCM}")
print(f"存在: {REAL_NCM.exists()}")
if REAL_NCM.exists():
    print(f"大小: {REAL_NCM.stat().st_size} 字节")
    raw = REAL_NCM.read_bytes()
    print(f"魔数: {raw[:8]!r}")
    print()

    info = ncm_core.parse(raw)
    print("--- 容器解析结果 ---")
    print(f"  密钥材料长度   : {len(info['key'])} 字节")
    print(f"  音频起始偏移   : {info['audio_off']}  (0x{info['audio_off']:X})")
    print(f"  封面           : {info['cover_mime']} / "
          f"{len(info['cover']) if info['cover'] else 0} 字节")
    print()
    print("--- 原始元数据 JSON ---")
    import json
    print(json.dumps(info["metadata"], ensure_ascii=False, indent=2)[:1600])
    print()
    meta = ncm_core.normalize_metadata(info["metadata"])
    print("--- 归一化后 ---")
    for k, v in meta.items():
        print(f"  {k:<14} {v!r}")
    print()

    audio, ext, meta, cover, mime = ncm_core.read_ncm(REAL_NCM)
    print("--- 解密结果 ---")
    print(f"  音频长度   : {len(audio)} 字节")
    print(f"  真实格式   : {ext}  (元数据自述: {meta['format_hint']})")
    print(f"  前 16 字节 : {audio[:16].hex(' ')}")
    print(f"  封面       : {mime} / {len(cover) if cover else 0} 字节")
    print()

    # 落盘供播放测试
    dest_dir = HERE / "real-samples"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / f"Wake (Studio).{ext}"
    dest.write_bytes(audio)
    print(f"  已写出: {dest}  ({dest.stat().st_size} 字节)")
    if cover:
        cdest = dest_dir / f"cover.{mime.split('/')[-1]}"
        cdest.write_bytes(cover)
        print(f"  已写出封面: {cdest}")

print()
print("=" * 78)
print("真实 MP3 的标签与封面读取（播放列表/详情面板要用）")
print("=" * 78)
try:
    import mutagen
    from mutagen.id3 import ID3
    from mutagen.mp3 import MP3

    mp3s = sorted(MP3_DIR.glob("*.mp3"))[:4]
    for p in mp3s:
        print(f"\n  === {p.name} ===")
        try:
            m = MP3(p)
            print(f"    时长 {m.info.length:.1f} 秒   比特率 {m.info.bitrate // 1000} kbps   "
                  f"采样率 {m.info.sample_rate} Hz")
            t = ID3(p)
            print(f"    标题: {t.get('TIT2')}")
            print(f"    艺术家: {t.get('TPE1')}")
            print(f"    专辑: {t.get('TALB')}")
            apic = t.getall("APIC")
            print(f"    封面: {len(apic)} 张" + (f"，第一张 {apic[0].mime} "
                  f"{len(apic[0].data)} 字节" if apic else ""))
            print(f"    时长标签: {t.get('TLEN')}")
        except Exception as exc:
            print(f"    读取失败: {type(exc).__name__}: {exc}")
except Exception as exc:
    print(f"  mutagen 不可用: {exc}")

pathlib.Path("real-ncm-report.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp(f"报告 -> real-ncm-report.txt ({len(_buf.getvalue())} 字符)")
