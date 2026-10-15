#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 GBK + CRLF 的 Windows 批处理脚本。"""
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def w(name, text):
    data = text.replace("\n", "\r\n").encode("gbk")
    (HERE / name).write_bytes(data)
    print(f"  {name}  {len(data)} 字节")


w("首次运行-安装到桌面.cmd", r"""@echo off
rem ============================================================
rem  首次运行：安装 iTunes 助手并创建桌面快捷方式
rem
rem  为什么双击会报「could not create temporary directory」：
rem    程序原本放在开发目录 D:\新建文件夹\ 下，这个目录被打上了
rem    「低完整性级别 (Low Mandatory Level)」标签，目录里的文件都
rem    **继承**了这个标签（icacls 显示为 (I) 就是继承来的）。
rem
rem    带低完整性标签的 exe 被双击时，进程也以「低完整性」运行。
rem    而 PyInstaller 单文件程序必须先往 %TEMP% 解包出 _MEI 目录，
rem    低完整性进程不能往更高完整性的位置写入（no-write-up），
rem    于是启动就失败了。以管理员身份运行 = 高完整性，可以降级写入，
rem    所以右键管理员运行反而正常。
rem
rem    「发送到桌面快捷方式」只是建了个 .lnk，指向的还是那个带标签的
rem    原件，所以照样报错。
rem
rem  本脚本做四件事：
rem    1. 把 exe 复制到 %LOCALAPPDATA%\Programs\iTunes助手\
rem       —— 继承来的标签不会随复制带走，副本会继承目标目录的
rem          Medium 级别，通常这一步就已经好了，不需要管理员；
rem    2. 校验副本的完整性级别，万一仍是 Low 才请求提权修正；
rem    3. 在桌面创建快捷方式（指向修好的副本）；
rem    4. 启动它。
rem
rem  之后直接双击桌面的「iTunes 助手」即可，不用再运行本脚本。
rem ============================================================

setlocal EnableExtensions EnableDelayedExpansion
chcp 936 >nul 2>&1
title iTunes 助手 - 首次运行

set "SRC=%~dp0iTunes助手.NCM版.exe"
set "DESTDIR=%LOCALAPPDATA%\Programs\iTunes助手"
set "DEST=%DESTDIR%\iTunes助手.exe"
set "LNK=%USERPROFILE%\Desktop\iTunes 助手.lnk"

echo.
echo ============================================================
echo   安装 iTunes 助手
echo ============================================================
echo.

if not exist "%SRC%" (
    echo   [X] 同目录下找不到  iTunes助手.NCM版.exe
    echo.
    echo       请把本脚本和它放在同一个文件夹里，再运行本脚本。
    echo.
    pause
    exit /b 1
)

echo   [1/4] 复制到普通目录
echo         源文件 : %SRC%
echo         目标   : %DEST%
if not exist "%DESTDIR%" mkdir "%DESTDIR%" >nul 2>&1
copy /y "%SRC%" "%DEST%" >nul
if errorlevel 1 (
    echo.
    echo   [X] 复制失败。请检查磁盘空间，或目标目录是否可写。
    echo.
    pause
    exit /b 1
)
echo         完成。
echo.

echo   [2/4] 校验完整性级别
set "LOW="
icacls "%DEST%" 2>nul | findstr /C:"Low Mandatory Level" >nul && set "LOW=1"

if defined LOW (
    echo         副本仍带低完整性标签，需要管理员权限移除。
    net session >nul 2>&1
    if errorlevel 1 (
        echo.
        echo         正在请求管理员权限（会弹出 UAC 确认框，请点「是」）...
        echo.
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
        exit /b
    )
    echo         正在移除标签...
    icacls "%DEST%" /reset >nul 2>&1
    icacls "%DEST%" /setintegritylevel Medium >nul 2>&1
    set "LOW="
    icacls "%DEST%" 2>nul | findstr /C:"Low Mandatory Level" >nul && set "LOW=1"
)

if defined LOW (
    echo.
    echo   [X] 仍然无法移除低完整性标签。
    echo       请右键本脚本，选择「以管理员身份运行」一次。
    echo.
    pause
    exit /b 1
)
echo         正常：副本不再是低完整性，双击可以直接运行。
echo.

echo   [3/4] 在桌面创建快捷方式
powershell -NoProfile -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut('%LNK%'); $s.TargetPath='%DEST%'; $s.WorkingDirectory='%DESTDIR%'; $s.IconLocation='%DEST%,0'; $s.Description='iTunes 助手 - 本地音乐归档'; $s.Save()" >nul 2>&1
if exist "%LNK%" (
    echo         已创建：%LNK%
) else (
    echo         [!] 快捷方式创建失败，可以直接使用：%DEST%
)
echo.

echo   [4/4] 启动
start "" "%DEST%"
echo         已启动。
echo.
echo ============================================================
echo   以后直接双击桌面的「iTunes 助手」图标即可。
echo   程序位置：%DESTDIR%
echo   本脚本只需要运行这一次。
echo ============================================================
echo.
pause
""")

# 带 BOM 的 UTF-8 版本，方便直接在编辑器里查看（cmd 仍然用上面那份 GBK 的）
w("首次运行-安装到桌面.说明.txt", r"""首次运行说明
============================================================

现象
    双击 iTunes助手.NCM版.exe 报错：
        could not create temporary directory
    右键「以管理员身份运行」却正常。

原因
    程序原本放在 D:\新建文件夹\ 下。这个目录被打上了
    「低完整性级别 (Low Mandatory Level)」标签，目录里的文件都
    继承了它 —— icacls 里显示的 (I) 就代表是继承来的。

    带低完整性标签的 exe 被双击时，进程也以「低完整性」运行。
    PyInstaller 单文件程序启动时必须先往 %TEMP% 解包出 _MEI 目录，
    而低完整性进程不能往更高完整性的位置写入（no-write-up），
    所以启动失败。管理员 = 高完整性，可以降级写入，因此反而正常。

    「发送到桌面快捷方式」只是创建了一个 .lnk，指向的仍然是那个
    带标签的原件，所以换成快捷方式也一样报错。

解决
    运行 首次运行-安装到桌面.cmd

    它会把 exe 复制到：
        %LOCALAPPDATA%\Programs\iTunes助手\
    继承来的标签不会随复制带走，副本会继承目标目录的 Medium 级别，
    通常这一步就已经修好了，不需要管理员权限。

    万一副本仍是 Low（比如标签被显式写过），脚本会自动请求提权并用
    icacls 移除标签。整个过程最多弹一次 UAC。

    最后它会在桌面创建「iTunes 助手」快捷方式并启动程序。

之后
    直接双击桌面的「iTunes 助手」即可，不需要管理员，也不需要再运行
    任何脚本。可以放心把原来那个带标签的 exe 删掉。
""")
