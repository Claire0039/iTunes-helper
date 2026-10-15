#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_app.py —— 从 iTunes助手.exe 里取出应用自身模块并做静态分析

输出：
  disasm/<module>.dis.txt      完整反汇编
  disasm/<module>.strings.txt  所有字符串常量（按嵌套代码对象分组）
  app-summary.txt              模块结构总览
"""
import dis
import io
import marshal
import pathlib
import sys
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pyi_tool import PyiArchive, read_pyz

EXE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "iTunes助手.exe")
OUT = pathlib.Path("disasm")
OUT.mkdir(exist_ok=True)

# 标准库 / 第三方库的顶层包名，用来把「应用自身代码」筛出来
KNOWN_LIBS = {
    "encodings", "collections", "importlib", "zipfile", "struct", "ctypes",
    "PySide6", "shiboken6", "os", "sys", "io", "abc", "json", "re", "enum",
    "typing", "functools", "pathlib", "subprocess", "threading", "logging",
    "urllib", "http", "email", "xml", "unittest", "sqlite3", "decimal",
    "multiprocessing", "concurrent", "asyncio", "dataclasses", "inspect",
    "warnings", "traceback", "tempfile", "shutil", "glob", "time", "datetime",
    "random", "hashlib", "base64", "binascii", "codecs", "string", "textwrap",
    "pickle", "copyreg", "copy", "operator", "keyword", "token", "tokenize",
    "linecache", "ast", "dis", "opcode", "site", "posixpath", "ntpath",
    "annotationlib", "argparse", "bisect", "bz2", "calendar", "codeop",
    "compression", "contextlib", "contextvars", "csv", "difflib", "fnmatch",
    "fractions", "ftplib", "getopt", "gettext", "gzip", "ipaddress", "lzma",
    "mimetypes", "mutagen", "netrc", "numbers", "optparse", "pprint",
    "py_compile", "quopri", "selectors", "signal", "socket", "ssl",
    "statistics", "stringprep", "sysconfig", "tarfile", "tracemalloc",
}


def walk_code(code, prefix=""):
    """深度优先遍历所有嵌套 code object"""
    yield prefix + code.co_name, code
    for c in code.co_consts:
        if hasattr(c, "co_name"):
            yield from walk_code(c, prefix + code.co_name + ".")


def strings_of(code):
    out = []
    for c in code.co_consts:
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, (int, float)) and not isinstance(c, bool):
            out.append(repr(c))
    return out


def load_module(pyz_data, typ, pos, length):
    blob = pyz_data[pos:pos + length]
    # PYZ 里的模块数据是 zlib 压缩的
    for candidate in (lambda b: zlib.decompress(b), lambda b: b):
        try:
            return marshal.loads(candidate(blob))
        except Exception:
            continue
    return None


def main():
    ar = PyiArchive(EXE)
    pyz_entry = next(e for e in ar.entries if e["kind"] == "z")
    pyz_data = ar.read_entry(pyz_entry)
    pyc_magic, items = read_pyz(pyz_data)
    print(f"PYZ 内含 {len(items)} 个条目; pyc magic = {pyc_magic.hex()}")
    if pyc_magic != pathlib.sys.implementation.cache_tag.encode()[:0] + pyc_magic:
        pass
    import importlib.util
    print(f"本机 Python pyc magic = {importlib.util.MAGIC_NUMBER.hex()}")

    by_name = {name: (typ, pos, length) for name, typ, pos, length in items}

    app_modules = []
    for name in sorted(by_name):
        top = name.split(".")[0]
        if top not in KNOWN_LIBS and not top.startswith("_"):
            app_modules.append(name)

    print("\n非标准库模块（应用自身代码）:")
    for m in app_modules:
        typ, pos, length = by_name[m]
        print(f"   {m:<40} 压缩 {length:>8} 字节")

    summary = io.StringIO()
    summary.write(f"可执行文件: {EXE}\n")
    summary.write(f"Python: 3.{ar.pyver % 100}\n")
    summary.write(f"CArchive 条目: {len(ar.entries)}\n")
    summary.write(f"PYZ 条目: {len(items)}\n\n")
    summary.write("应用自身模块:\n")
    for m in app_modules:
        summary.write(f"  {m}\n")
    summary.write("\n")

    for mod in app_modules:
        typ, pos, length = by_name[mod]
        code = load_module(pyz_data, typ, pos, length)
        if code is None:
            print(f"  ! {mod} 反序列化失败")
            continue

        safe = mod.replace(".", "_")
        buf = io.StringIO()
        dis.dis(code, file=buf)
        (OUT / f"{safe}.dis.txt").write_text(buf.getvalue(), encoding="utf-8")

        sbuf = io.StringIO()
        for path, c in walk_code(code):
            sbuf.write(f"\n===== {path} =====\n")
            sbuf.write(f"  参数 {c.co_argcount}, 局部变量 {list(c.co_varnames)}\n")
            sbuf.write(f"  引用名字 {list(c.co_names)}\n")
            for s in strings_of(c):
                sbuf.write(f"    {s!r}\n")
        (OUT / f"{safe}.strings.txt").write_text(sbuf.getvalue(), encoding="utf-8")

        summary.write("=" * 70 + "\n")
        summary.write(f"模块 {mod}  (file={code.co_filename!r})\n")
        summary.write("=" * 70 + "\n")
        summary.write(f"顶层引用名字: {list(code.co_names)}\n\n")
        summary.write("代码对象树:\n")
        for path, c in walk_code(code):
            summary.write(f"  {path:<52} 参数 {c.co_argcount:<3} 行 {c.co_firstlineno}\n")
        summary.write("\n")

    pathlib.Path("app-summary.txt").write_text(summary.getvalue(), encoding="utf-8")
    print(f"\n总览 -> app-summary.txt")
    print(f"反汇编 -> {OUT}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
