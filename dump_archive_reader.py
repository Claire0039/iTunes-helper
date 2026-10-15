#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反汇编 PyInstaller 自己的 archive 读取器，弄清 TOC 条目字段语义。"""
import dis
import io
import marshal
import pathlib
import sys

p = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "extracted/scripts/pyimod01_archive.marshal.bin")
code = marshal.loads(p.read_bytes())

buf = io.StringIO()
dis.dis(code, file=buf)
text = buf.getvalue()

out = pathlib.Path("pyimod01_archive.dis.txt")
out.write_text(text, encoding="utf-8")
print(f"写出 {out} ({len(text)} 字符)")

# 只看 extract / _read_toc 附近
import re
blocks = re.split(r"(?m)^Disassembly of <code object ", text)
for b in blocks[1:]:
    name = b.split(" ", 1)[0]
    if name in ("extract", "_read_toc", "toc", "_parse_cookie", "__init__", "open_embedded_archive"):
        print("=" * 70)
        print("code object:", name)
        print("=" * 70)
        print(b[:4200])
