# -*- coding: utf-8 -*-
"""
main_patched.py —— 集成 NCM 支持后的程序入口（源码形式）

原版 main.py 只做三件事：把 exe 旁边的 libs/ 、src/ 加进 sys.path，
从 app 导入 run，然后 sys.exit(run())。

这里保持完全相同的骨架，只在调用 run() 之前安装了 NCM 支持补丁。
它同时是「人类可读的源码」和「构建脚本的输入」——
build_patched_exe.py 会把本文件连同 ncm_core / ncm_tags / ncm_patch
一起编译成单个 code object，替换进 exe 的 PyInstaller 归档。
"""
from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_path():
    """与原版逐字一致：让 exe 旁边的 libs/ 和 src/ 可以被导入。"""
    base = Path(__file__).resolve().parent
    for candidate in (base / "libs", base / "src"):
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


_bootstrap_path()

import ncm_patch  # noqa: E402


def main() -> int:
    # 先装补丁再进界面：MainWindow 构造时就能看到 NCM 提示，
    # 扫描时 core.scan_folder 已经是打过补丁的版本。
    ncm_patch.install()
    from app import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
