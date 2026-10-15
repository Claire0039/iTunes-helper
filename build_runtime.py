#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_runtime.py —— 用解包出来的内容搭一个「不依赖 PyInstaller 引导器」的运行环境

动机：原版 iTunes助手.exe 在本机沙箱里解包失败（_MEI 目录建了但写不进文件，
进程直接 -1 退出），没法做功能验证。既然它的 Python 部分和本机解释器版本
完全一致（pyc magic 2b0e0d0a = 3.14），就可以把 PYZ 里的模块还原成真实目录树，
配合本机 Python 3.14 直接运行，从而绕过引导器。

产出:
    runtime/            可运行的模块树（app / core / theme / mutagen / PySide6 ...）
    run_local.py        启动脚本

用法:
    python build_runtime.py <exe> <out_dir>
"""
import marshal
import pathlib
import shutil
import struct
import sys
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pyi_tool import PyiArchive, read_pyz

# PyInstaller 会把 stdlib 也打进 PYZ；这些交给本机 Python 自己的标准库即可，
# 避免两套同名模块互相干扰。
SKIP_STDLIB = {
    "encodings", "collections", "importlib", "zipfile", "struct", "ctypes",
    "os", "sys", "io", "abc", "json", "re", "enum", "typing", "functools",
    "pathlib", "subprocess", "threading", "logging", "urllib", "http", "email",
    "xml", "unittest", "sqlite3", "decimal", "multiprocessing", "concurrent",
    "asyncio", "dataclasses", "inspect", "warnings", "traceback", "tempfile",
    "shutil", "glob", "time", "datetime", "random", "hashlib", "base64",
    "binascii", "codecs", "string", "textwrap", "pickle", "copyreg", "copy",
    "operator", "keyword", "token", "tokenize", "linecache", "ast", "dis",
    "opcode", "site", "posixpath", "ntpath", "annotationlib", "argparse",
    "bisect", "bz2", "calendar", "codeop", "compression", "contextlib",
    "contextvars", "csv", "difflib", "fnmatch", "fractions", "ftplib",
    "getopt", "gettext", "gzip", "ipaddress", "lzma", "mimetypes", "netrc",
    "numbers", "optparse", "pprint", "py_compile", "quopri", "selectors",
    "signal", "socket", "ssl", "statistics", "stringprep", "sysconfig",
    "tarfile", "tracemalloc", "zlib", "marshal", "select", "unicodedata",
    "_bz2", "_ctypes", "_decimal", "_hashlib", "_lzma", "_socket", "_ssl",
}


def main():
    exe = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "iTunes助手.exe")
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "runtime")
    extracted = pathlib.Path("extracted")

    out.mkdir(parents=True, exist_ok=True)
    if out.exists():
        # 重新构建前清空，避免旧的 .pyc 与新的包目录互相干扰
        for child in out.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    ar = PyiArchive(exe)
    pyz_entry = next(e for e in ar.entries if e["kind"] == "z")
    pyz_data = ar.read_entry(pyz_entry)
    pyc_magic, items = read_pyz(pyz_data)

    # ── 0. 判定哪些名字是「包」 ──
    # 判据一：有别的模块以 "name." 开头
    # 判据二：bin/ 下存在同名目录（PySide6、shiboken6 就是这样）
    names = {n for n, _, _, _ in items}
    package_names = set()
    for n in names:
        parts = n.split(".")
        for i in range(1, len(parts)):
            package_names.add(".".join(parts[:i]))
    bin_root = extracted / "bin"
    if bin_root.is_dir():
        for d in bin_root.rglob("*"):
            if d.is_dir():
                package_names.add(d.relative_to(bin_root).as_posix().replace("/", "."))

    # ── 1. 把 PYZ 模块还原成真实目录树 ──
    written = 0
    skipped = 0
    for name, typ, pos, length in items:
        top = name.split(".")[0]
        if top in SKIP_STDLIB:
            skipped += 1
            continue
        blob = pyz_data[pos:pos + length]
        try:
            code = marshal.loads(zlib.decompress(blob))
        except Exception:
            try:
                code = marshal.loads(blob)
            except Exception:
                continue

        parts = name.split(".")
        if name in package_names:
            dest = out.joinpath(*parts) / "__init__.pyc"
        else:
            dest = out.joinpath(*parts).with_suffix(".pyc")
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 写成标准 pyc（16 字节头：magic + flags + mtime + source size）
        header = pyc_magic + struct.pack("<III", 0, 0, 0)
        dest.write_bytes(header + marshal.dumps(code))
        written += 1

    # 给没有对应 PYZ 模块的包目录补一个空 __init__.pyc
    for pkg in sorted(package_names):
        if pkg.split(".")[0] in SKIP_STDLIB:
            continue
        d = out.joinpath(*pkg.split("."))
        init = d / "__init__.pyc"
        if not init.exists() and d.is_dir():
            init.write_bytes(pyc_magic + struct.pack("<III", 0, 0, 0) +
                             marshal.dumps(compile("", "<empty>", "exec")))

    print(f"PYZ 模块: 写出 {written}, 跳过 stdlib {skipped}, 识别包 {len(package_names)}")

    # ── 2. 把 bin/ 下的 DLL 和扩展模块铺进来 ──
    bin_dir = extracted / "bin"
    copied = 0
    if bin_dir.is_dir():
        for src in bin_dir.rglob("*"):
            if src.is_file():
                rel = src.relative_to(bin_dir)
                dest = out / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                copied += 1
    print(f"复制 bin/ 文件: {copied}")

    # ── 3. 应用自己的资源目录 ──
    for sub in ("assets", "data"):
        src = extracted / sub
        if src.is_dir():
            dest = out / sub
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
            n = sum(1 for _ in dest.rglob("*") if _.is_file())
            print(f"复制 {sub}/: {n} 个文件")

    # ── 4. 启动脚本 ──
    launcher = pathlib.Path("run_local.py")
    launcher.write_text(
        '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用本机 Python 直接运行 iTunes助手（绕过 PyInstaller 引导器）。"""
import os
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"

# 把 runtime 追加到 sys.path 末尾，让本机标准库优先，
# 只有 app / core / theme / mutagen / PySide6 这些从 runtime 取。
sys.path.append(str(RUNTIME))

# 扩展模块（QtCore.pyd / Shiboken.pyd）依赖同目录及上级目录下的 DLL，
# Python 3.8+ 必须显式把这些目录加进 DLL 搜索路径。
if hasattr(os, "add_dll_directory"):
    for d in (RUNTIME, RUNTIME / "PySide6", RUNTIME / "shiboken6"):
        if d.is_dir():
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass

# Qt 插件目录
os.environ.setdefault("QT_PLUGIN_PATH", str(RUNTIME / "PySide6" / "plugins"))
os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    str(RUNTIME / "PySide6" / "plugins" / "platforms"),
)

# 让 app 以为自己是冻结环境（它会读 sys.frozen / _MEIPASS 决定资源路径）
sys.frozen = False


def main():
    from app import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
''',
        encoding="utf-8",
    )
    print(f"启动脚本 -> {launcher}")
    print(f"\n试运行:  python -S run_local.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
