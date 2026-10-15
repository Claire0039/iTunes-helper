#!/usr/bin/env python3
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
