#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_patched_local.py —— 在本地运行时里执行「被编译进 exe 的那份入口代码」

它做的是 PyInstaller 引导器会做的事：把归档里的入口 code object 取出来，
以 __main__ 的身份执行。所以这里跑通了，就说明 exe 里的入口逻辑是对的。
"""
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"

sys.path.append(str(RUNTIME))
if hasattr(os, "add_dll_directory"):
    for d in (RUNTIME, RUNTIME / "PySide6", RUNTIME / "shiboken6"):
        if d.is_dir():
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass

os.environ.setdefault("QT_PLUGIN_PATH", str(RUNTIME / "PySide6" / "plugins"))
os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH",
                      str(RUNTIME / "PySide6" / "plugins" / "platforms"))

combined = HERE / "build" / "main_combined.py"
source = combined.read_text(encoding="utf-8")

# 与 PyInstaller 冻结环境一致：以 __main__ 执行，__file__ 指向解包目录里的 main.py
globals_dict = {
    "__name__": "__main__",
    "__file__": str(RUNTIME / "main.py"),
    "__builtins__": __builtins__,
}
exec(compile(source, "main.py", "exec"), globals_dict)
