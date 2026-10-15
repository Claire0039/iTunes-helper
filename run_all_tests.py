#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all_tests.py —— 一键跑完 NCM 集成的全部验证，并重建产物

用法（在 itunes-helper 目录下）：
    python -u -S run_all_tests.py

依赖：Python 3.14、Node.js 都在 PATH 里。

注意：这里用 subprocess 且**不捕获输出**（继承父进程的 stdio）。
沙箱环境下带管道的子进程创建会被拒绝，继承 stdio 则没问题；
而且实时输出也更容易看清每一步在做什么。
"""
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
os.chdir(HERE)

ENV = dict(os.environ)
ENV["PYTHONIOENCODING"] = "utf-8"
# 本机沙箱不允许往「运行时新建的临时子目录」写文件（PyInstaller 的 _MEI 解包
# 失败也是同一原因），所以把解密缓存指到工作区。
ENV["ITUNES_ASSISTANT_NCM_CACHE"] = str(HERE / "e2e" / "cache")

PY = [sys.executable, "-u", "-S"]

STEPS = [
    ("1/10  生成测试向量与样本", [
        ["node", "gen_aes_vectors.js"],
        [*PY, "make_flac_payload.py", "e2e-fixtures/payload.flac"],
        ["node", "make_e2e_fixtures.js"],
    ]),
    ("2/10  生成图标素材与安装脚本", [
        [*PY, "make_icons.py"],
        [*PY, "make_player_icons.py"],
        [*PY, "make_launcher.py"],
        [*PY, "verify_launcher.py"],
    ]),
    ("3/10  NCM 解码核心（AES / 密钥流 / 容器）", [
        [*PY, "test_ncm_core.py"],
    ]),
    ("4/10  端到端集成（解密 → 打标签 → 归档）", [
        [*PY, "test_integration.py"],
    ]),
    ("5/10  界面集成（提示 / 日志 / 拖放）", [
        [*PY, "test_ui_patch.py"],
    ]),
    ("6/10  拖放（真实 dragEnter → dragMove → drop 事件链）", [
        [*PY, "test_drag_drop.py"],
    ]),
    ("7/10  第二版功能（拖入追加 / 详情面板 / 播放器）", [
        [*PY, "test_v2_features.py"],
    ]),
    ("8/10  第三版功能（外观三态 / 播放器布局 / 进度文字 / 图标）", [
        [*PY, "test_v3_features.py"],
    ]),
    ("9/10  构建带 NCM 支持的 exe", [
        [*PY, "build_patched_exe.py", "iTunes助手.exe", "iTunes助手.NCM版.exe"],
    ]),
    ("10/10 用编译进 exe 的入口代码做冒烟测试", None),   # 特殊处理
]


def run(cmd):
    print(f"  $ {' '.join(cmd)}", flush=True)
    try:
        proc = subprocess.run(cmd, env=ENV)      # 不捕获输出，直接继承
    except FileNotFoundError as exc:
        print(f"  ! 命令不存在：{exc}", flush=True)
        return 127
    return proc.returncode


def smoke_test():
    env = dict(ENV)
    shot = HERE / "patched-shot.png"
    report = HERE / "patched-report.txt"
    env["ITUNES_ASSISTANT_SMOKE"] = "1"
    env["ITUNES_ASSISTANT_SHOT"] = str(shot)
    env["ITUNES_ASSISTANT_REPORT"] = str(report)
    for p in (shot, report):
        if p.exists():
            p.unlink()
    print(f"  $ {' '.join(PY)} run_patched_local.py   (ITUNES_ASSISTANT_SMOKE=1)", flush=True)
    proc = subprocess.run([*PY, "run_patched_local.py"], env=env)
    if proc.returncode != 0:
        print(f"  ! 退出码 {proc.returncode}")
        return proc.returncode
    if not shot.exists():
        print("  ! 没有生成冒烟截图")
        return 1
    print(f"  冒烟截图: {shot}")
    if report.exists():
        print("  冒烟报告:")
        for line in report.read_text(encoding="utf-8").splitlines():
            print(f"    {line}")
    return 0


def main():
    print()
    print("iTunes 助手 · NCM 集成 —— 完整验证")
    print(f"工作目录: {HERE}")
    print(f"Python  : {sys.version.split()[0]}  ({sys.executable})")
    try:
        node = subprocess.run(["node", "--version"], env=ENV, capture_output=True, text=True)
        print(f"Node    : {node.stdout.strip()}")
    except Exception:
        print("Node    : 未找到")

    results = []
    for title, commands in STEPS:
        print()
        print("=" * 72)
        print(f"  {title}")
        print("=" * 72)
        code = smoke_test() if commands is None else 0
        if commands is not None:
            for cmd in commands:
                code = run(cmd)
                if code != 0:
                    break
        results.append((title, code))

    print()
    print("=" * 72)
    print("  汇总")
    print("=" * 72)
    for title, code in results:
        print(f"  {'通过' if code == 0 else '失败'}  {title}" + ("" if code == 0 else f"  (退出码 {code})"))

    failed = [t for t, c in results if c != 0]
    print()
    if not failed:
        exe = HERE / "iTunes助手.NCM版.exe"
        print(f"全部 {len(results)} 个步骤通过 ✓")
        if exe.exists():
            print(f"产物: {exe}  ({exe.stat().st_size} 字节)")
        return 0
    print(f"{len(failed)} 个步骤失败 ✗")
    return 1


if __name__ == "__main__":
    sys.exit(main())
