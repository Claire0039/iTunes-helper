#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列出 PE 资源段里的图标资源，评估能否替换资源管理器图标。"""
import builtins
import io
import pathlib
import struct
import sys

_buf = io.StringIO()
_rp = builtins.print


def print(*a, **k):          # noqa: A001
    k["file"] = _buf
    return _rp(*a, **k)


raw = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "iTunes助手.exe").read_bytes()
pe = struct.unpack_from("<I", raw, 0x3C)[0]
ns = struct.unpack_from("<H", raw, pe + 6)[0]
opt = struct.unpack_from("<H", raw, pe + 20)[0]
sec = pe + 24 + opt
sections = []
rva_rsrc = size_rsrc = None
dd = pe + 24 + (112 if struct.unpack_from("<H", raw, pe + 24)[0] == 0x20B else 96)
rva_rsrc, size_rsrc = struct.unpack_from("<II", raw, dd + 2 * 8)
for i in range(ns):
    o = sec + i * 40
    name = raw[o:o + 8].rstrip(b"\x00").decode("latin1")
    vs, va, rs, rp = struct.unpack_from("<IIII", raw, o + 8)
    sections.append((name, va, vs, rp, rs))


def rva_to_off(rva):
    for name, va, vs, rp, rs in sections:
        if va <= rva < va + max(vs, rs):
            return rp + (rva - va)
    return None


base = rva_to_off(rva_rsrc)
print(f"资源目录: RVA=0x{rva_rsrc:X} size={size_rsrc} 文件偏移=0x{base:X}")
print(f".rsrc 节: rawptr=0x{sections[5][3]:X} rawsize={sections[5][4]}")
print()

entries = []


def walk(off, depth, path):
    # IMAGE_RESOURCE_DIRECTORY: 4+4+2+2+2+2 = 16 字节头，
    # NumberOfNamedEntries 在 +12，NumberOfIdEntries 在 +14，条目从 +16 开始
    nname, nid = struct.unpack_from("<HH", raw, base + off + 12)
    for i in range(nname + nid):
        e = base + off + 16 + i * 8
        nm, sub = struct.unpack_from("<II", raw, e)
        if nm & 0x80000000:
            noff = base + (nm & 0x7FFFFFFF)
            ln = struct.unpack_from("<H", raw, noff)[0]
            label = raw[noff + 2:noff + 2 + ln * 2].decode("utf-16le", "replace")
        else:
            label = str(nm)
        if sub & 0x80000000:
            walk(sub & 0x7FFFFFFF, depth + 1, path + "/" + label)
        else:
            d = base + sub
            drva, dsize = struct.unpack_from("<II", raw, d)
            doff = rva_to_off(drva)
            entries.append((path + "/" + label, drva, dsize, doff))
            print(f"  {path}/{label:<24} RVA=0x{drva:08X} size={dsize:<8} off=0x{doff:X}")


walk(0, 0, "")

print()
icons = [e for e in entries if e[0].startswith("/3/")]
groups = [e for e in entries if e[0].startswith("/14/")]
print(f"RT_ICON 条目: {len(icons)} 个, 总 {sum(e[2] for e in icons)} 字节")
print(f"RT_GROUP_ICON 条目: {len(groups)} 个")
for g in groups:
    data = raw[g[3]:g[3] + g[2]]
    cnt = struct.unpack_from("<H", data, 4)[0]
    print(f"  组 {g[0]}: {cnt} 个尺寸")
    for i in range(cnt):
        w, h, cc, r8, planes, bits, size, iid = struct.unpack_from("<BBBBHHIH", data, 6 + i * 14)
        print(f"     {w or 256}x{h or 256} {bits}bpp {size} 字节  id={iid}")

print()
print("资源段总占用:", size_rsrc, "字节; .rsrc 原始大小:", sections[5][4],
      "→ 剩余空间:", sections[5][4] - (max(e[1] for e in [(0,0,0,0)] + []) or 0))

# 计算资源数据区里已用到的最远偏移
if entries:
    end = max(e[3] + e[2] for e in entries)
    print(f"资源数据最远结束于 0x{end:X}，.rsrc 结束于 0x{sections[5][3]+sections[5][4]:X}"
          f"，剩余 {sections[5][3]+sections[5][4]-end} 字节")

pathlib.Path("pe-icons.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp("报告 -> pe-icons.txt")
