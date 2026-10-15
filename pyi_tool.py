#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pyi_tool.py —— PyInstaller onefile 归档的工具集（自研，无外部依赖）

支持：
  list    <exe>              列出 CArchive 条目
  extract <exe> <dir>        解出所有条目
  pyz     <exe> <dir>        解出 PYZ 里的所有 Python 模块
  main    <exe>              反汇编入口脚本，导出到 <exe>.main.dis.txt

CArchive 结构：
    [PE 头 + 节区][数据区][TOC][COOKIE 88 字节]

COOKIE:
    MAGIC[8] = 4D 45 49 0C 0B 0A 0B 0E
    lengthofPackage  !i   从归档起点到文件末尾的总长（含 cookie 自己）
    toc              !i   TOC 相对归档起点的偏移
    tocLen           !i   TOC 字节数
    pyver            !i   如 314 => 3.14
    pylibname[64]

TOC 条目（实测布局，entry_len 含它自己，整条 16 字节对齐）：
    +0   !i   entry_len
    +4   !i   数据偏移（相对归档起点）
    +8   !i   压缩后长度
    +12  !i   解压后长度
    +16  B    标志位（实测恒为 0x01）
    +17  ...  名字，以 \\0 结尾，名字首字符是类型前缀：
                m = Python 模块（marshal 后的 code object）
                s = 入口脚本（marshal 后的 code object）
                b = 二进制文件（DLL / pyd，原样存放）
                z = 内嵌的 PYZ 归档
                x = 数据文件
"""
import dis
import io
import marshal
import pathlib
import struct
import sys
import zlib

MAGIC = b"MEI\014\013\012\013\016"
PYZ_MAGIC = b"PYZ\0"

TYPE_NAMES = {
    "m": "模块",
    "s": "脚本",
    "b": "二进制",
    "z": "PYZ",
    "x": "数据",
    "e": "扩展",
    "d": "依赖",
}


# ───────────────────────────── CArchive ─────────────────────────────

class PyiArchive:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.raw = self.path.read_bytes()
        self._read_cookie()
        self._read_toc()

    def _read_cookie(self):
        if len(self.raw) < 88:
            raise ValueError("文件太小，不是 PyInstaller 归档")
        off = len(self.raw) - 88
        if self.raw[off:off + 8] != MAGIC:
            raise ValueError("文件末尾找不到 PyInstaller cookie 魔数")
        (self.pkg_len, self.toc_off, self.toc_len,
         self.pyver) = struct.unpack("!iiii", self.raw[off + 8:off + 24])
        self.pylib = self.raw[off + 24:off + 88].split(b"\0")[0].decode("latin1")
        self.cookie_off = off
        # lengthofPackage 含 88 字节 cookie，所以归档起点 = 文件尾 - pkg_len
        self.archive_start = len(self.raw) - self.pkg_len
        self.archive_end = off

    def _read_toc(self):
        self.entries = []
        p = self.archive_start + self.toc_off
        end = p + self.toc_len
        while p < end - 4:
            entry_len = struct.unpack("!i", self.raw[p:p + 4])[0]
            if entry_len <= 0 or p + entry_len > end:
                break
            offset, cmprs, uncmprs = struct.unpack("!iii", self.raw[p + 4:p + 16])
            flag = self.raw[p + 16]
            name_end = self.raw.index(b"\0", p + 17)
            name = self.raw[p + 17:name_end].decode("utf-8")
            self.entries.append({
                "name": name,
                "kind": name[0] if name else "?",
                "realname": name[1:] if len(name) > 1 else "",
                "offset": offset,
                "cmprs_len": cmprs,
                "uncmprs_len": uncmprs,
                "flag": flag,
                "entry_len": entry_len,
            })
            p += entry_len

    def read_entry(self, e):
        """取出条目数据（自动判断是否 zlib 压缩）"""
        start = self.archive_start + e["offset"]
        blob = self.raw[start:start + e["cmprs_len"]]
        if e["cmprs_len"] == e["uncmprs_len"]:
            return blob
        try:
            data = zlib.decompress(blob)
            if len(data) == e["uncmprs_len"]:
                return data
            return data
        except zlib.error:
            return blob


# ───────────────────────────── PYZ ─────────────────────────────

def read_pyz(data):
    """解析 PYZ 归档，返回 [(name, typecode, offset, length)]"""
    if data[:4] != PYZ_MAGIC:
        raise ValueError("不是 PYZ 归档")
    pyc_magic = data[4:8]
    (toc_off,) = struct.unpack("!i", data[8:12])
    toc = marshal.loads(data[toc_off:])
    out = []
    for name, entry in toc:
        typ, pos, length = entry
        out.append((name, typ, pos, length))
    return pyc_magic, out


def extract_pyz(data, out_dir):
    pyc_magic, items = read_pyz(data)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for name, typ, pos, length in items:
        blob = data[pos:pos + length]
        # typ: 0 = marshal 后的 code object，1 = 原样字节（罕见）
        safe = name.replace(".", "/")
        dest = out / (safe + ".pyc")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if typ == 0:
            try:
                code = marshal.loads(blob)
                blob = marshal.dumps(code)
            except Exception:
                pass
        dest.write_bytes(blob)
        n += 1
    return n, items


# ───────────────────────────── 命令 ─────────────────────────────

def cmd_list(exe):
    ar = PyiArchive(exe)
    w = print
    w(f"Python {ar.pyver // 100}.{ar.pyver % 100}, 运行时 {ar.pylib}")
    w(f"归档起点 0x{ar.archive_start:X}, 归档长度 {ar.pkg_len}, 条目 {len(ar.entries)} 个")
    w("")
    for e in ar.entries:
        kind = TYPE_NAMES.get(e["kind"], e["kind"])
        w(f"  [{e['kind']}] {kind:<5} {e['realname']:<56} "
          f"{e['cmprs_len']:>10} / {e['uncmprs_len']:>10}")


def cmd_extract(exe, out_dir):
    ar = PyiArchive(exe)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for e in ar.entries:
        data = ar.read_entry(e)
        if e["kind"] == "b":
            dest = out / "bin" / e["realname"].replace("\\", "/")
        elif e["kind"] in ("m", "s"):
            dest = out / "scripts" / (e["realname"] + ".marshal.bin")
        elif e["kind"] == "z":
            dest = out / (e["realname"] or "PYZ.pyz")
        else:
            dest = out / "data" / e["realname"].replace("\\", "/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        total += len(data)
        print(f"  {e['realname']:<58} {len(data):>10}")
    print(f"\n共 {len(ar.entries)} 个条目, {total} 字节 -> {out}")


def cmd_pyz(exe, out_dir):
    ar = PyiArchive(exe)
    pyz_entry = next((e for e in ar.entries if e["kind"] == "z"), None)
    if not pyz_entry:
        print("归档里没有 PYZ")
        return 1
    data = ar.read_entry(pyz_entry)
    print(f"PYZ: {pyz_entry['realname']}  {len(data)} 字节")
    n, items = extract_pyz(data, out_dir)
    print(f"解出 {n} 个模块 -> {out_dir}")
    return 0


def cmd_main(exe):
    ar = PyiArchive(exe)
    entry = next((e for e in ar.entries if e["kind"] == "s" and e["realname"] == "main"), None)
    if not entry:
        print("找不到入口脚本 main")
        print("现有脚本条目:", [e["realname"] for e in ar.entries if e["kind"] == "s"])
        return 1
    blob = ar.read_entry(entry)
    code = marshal.loads(blob)
    out = pathlib.Path(exe).with_suffix(".main.dis.txt")
    buf = io.StringIO()
    print("=== 入口脚本 main 的模块级反汇编 ===", file=buf)
    dis.dis(code, file=buf)
    out.write_text(buf.getvalue(), encoding="utf-8")
    print(f"已写出 {out}  ({len(buf.getvalue())} 字符)")
    print(f"常量数量 {len(code.co_consts)}, 名字数量 {len(code.co_names)}")
    print("co_names:", code.co_names)
    print("顶层常量里的嵌套代码对象:")
    for c in code.co_consts:
        if hasattr(c, "co_name"):
            print(f"   - {c.co_name}  (参数 {c.co_argcount}, 局部 {c.co_varnames[:12]})")
    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cmd, exe = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    if cmd == "list":
        cmd_list(exe); return 0
    if cmd == "extract":
        cmd_extract(exe, rest[0]); return 0
    if cmd == "pyz":
        return cmd_pyz(exe, rest[0])
    if cmd == "main":
        return cmd_main(exe)
    print(f"未知命令 {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
