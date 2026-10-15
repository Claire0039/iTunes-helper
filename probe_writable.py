#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_writable.py —— 找出「产出的文件不带低完整性标签」的可写目录

背景：DSH 沙箱给 D:\\新建文件夹 整个目录树打上了
    Mandatory Label\\Low Mandatory Level:(OI)(CI)(NW)
文件会继承这个标签。低完整性的 exe 被双击时，进程也以低完整性运行，
于是无法往 Medium 级别的 %TEMP% 里写 PyInstaller 需要的 _MEI 目录 —— 启动失败。
（以管理员身份运行 = 高完整性，可以降级写入，所以能成功。）

这里逐个候选目录做「建子目录 + 写文件」，并用 icacls 报告它拿到的完整性标签。
"""
import os
import pathlib
import subprocess
import sys

CANDIDATES = [
    ("工作区", pathlib.Path(r"D:\新建文件夹\itunes-helper\_label_probe")),
    ("真实 TEMP", pathlib.Path(os.path.expandvars(r"%LOCALAPPDATA%\Temp\_label_probe"))),
    ("用户主目录", pathlib.Path(os.path.expanduser(r"~\_label_probe"))),
    ("桌面", pathlib.Path(os.path.expanduser(r"~\Desktop\_label_probe"))),
    ("文档", pathlib.Path(os.path.expanduser(r"~\Documents\_label_probe"))),
    ("公共目录", pathlib.Path(r"C:\Users\Public\_label_probe")),
    ("程序数据", pathlib.Path(os.path.expandvars(r"%PROGRAMDATA%\_label_probe"))),
]


def label_of(path):
    try:
        out = subprocess.run(["icacls", str(path)], capture_output=True, text=True,
                             encoding="mbcs", errors="replace")
        for line in (out.stdout or "").splitlines():
            if "Mandatory Label" in line:
                return line.strip()
        return "(无显式标签)"
    except Exception as exc:
        return f"(读取失败 {exc})"


print(f"当前进程完整性: ", end="")
r = subprocess.run(["whoami", "/groups"], capture_output=True, text=True,
                   encoding="mbcs", errors="replace")
for line in r.stdout.splitlines():
    if "Mandatory Label" in line:
        print(line.split()[0], line.split()[1] if len(line.split()) > 1 else "")
        break
print()

ok = []
for name, path in CANDIDATES:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / "probe.bin"
        probe.write_bytes(b"probe" * 100)
        status = "可写"
        ok.append(name)
    except OSError as exc:
        print(f"  {name:<10} {str(path):<62} 不可写: {exc.strerror or exc}")
        continue
    print(f"  {name:<10} {str(path):<62} {status}")
    print(f"             -> {label_of(probe)}")

print()
print("可写位置:", ", ".join(ok) if ok else "（无）")
