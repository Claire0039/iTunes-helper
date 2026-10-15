#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_launcher.py —— 校验生成的批处理脚本（编码 / 换行 / 关键逻辑）"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
BAD = 0


def check(name, cond, detail=""):
    global BAD
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if not cond else ""))
    if not cond:
        BAD += 1


for fname in ("首次运行-安装到桌面.cmd", "首次运行-安装到桌面.说明.txt"):
    p = HERE / fname
    check(f"{fname} 存在", p.exists())
    if not p.exists():
        continue
    raw = p.read_bytes()
    try:
        text = raw.decode("gbk")
        ok = True
    except Exception as exc:
        text = ""
        ok = False
        check(f"{fname} GBK 解码", False, str(exc))
    if ok:
        check(f"{fname} GBK 解码", True)

    if fname.endswith(".cmd"):
        check("使用 CRLF 换行", raw.count(b"\r\n") > 20, str(raw.count(b"\r\n")))
        check("没有裸 LF", raw.replace(b"\r\n", b"").count(b"\n") == 0)
        for kw in ("DESTDIR=%LOCALAPPDATA%\\Programs",
                   "Low Mandatory Level",
                   "icacls \"%DEST%\" /setintegritylevel Medium",
                   "Start-Process -FilePath '%~f0' -Verb RunAs",
                   "CreateShortcut",
                   "start \"\" \"%DEST%\""):
            check(f"包含 {kw[:44]}", kw in text)
        # 不允许出现可能被 cmd 误解析的字符
        check("没有管道重定向被误用", "&&" not in text or "&& set" in text)
        check("以 @echo off 开头", text.startswith("@echo off"))
        check("有 setlocal", "setlocal EnableExtensions" in text)

print()
print("=" * 60)
print(f"校验{'通过' if BAD == 0 else f'失败（{BAD} 项）'}")
sys.exit(1 if BAD else 0)
