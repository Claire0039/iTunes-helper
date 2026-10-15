#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_scan_busy.py —— 原版程序执行「扫描预览」后，界面是否一直停在忙碌态？

不打任何补丁，只调 app 自己的 start_scan，观察 _running 与按钮状态。
"""
import builtins
import io
import os
import pathlib
import sys
import time

_buf = io.StringIO()
_rp = builtins.print


def print(*a, **k):          # noqa: A001
    k["file"] = _buf
    return _rp(*a, **k)


HERE = pathlib.Path(__file__).resolve().parent
sys.path.append(str(HERE / "runtime"))
for d in (HERE / "runtime", HERE / "runtime" / "PySide6", HERE / "runtime" / "shiboken6"):
    if d.is_dir():
        try:
            os.add_dll_directory(str(d))
        except OSError:
            pass
sys.path.insert(0, str(HERE))

from PySide6.QtWidgets import QApplication   # noqa: E402
import app                                   # noqa: E402

qapp = QApplication.instance() or QApplication([])
w = app.MainWindow()
w.apply_theme("light")

# 源目录指向自带样本的目录（有真实的 .ncm 和 mp3）
SRC = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload")
w.source_edit.setText(str(SRC))
w.check_recursive.setChecked(False)

print(f"扫描前: _running={w._running}  scan_btn={w.scan_btn.isEnabled()}  "
      f"run_btn={w.run_btn.isEnabled()}")

w.start_scan()


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


for label, wait in (("1 秒后", 1.0), ("3 秒后", 2.0), ("8 秒后", 5.0), ("20 秒后", 12.0)):
    pump(wait)
    print(f"{label}: _running={w._running}  rows={w.model.rowCount()}  "
          f"scan_btn={w.scan_btn.isEnabled()}  run_btn={w.run_btn.isEnabled()}  "
          f"scan_btn.text={w.scan_btn.text()!r}  run_btn.text={w.run_btn.text()!r}")

print()
print(f"worker  = {w._worker!r}")
print(f"thread  = {w._thread!r}")
print(f"worker 类型 = {type(w._worker).__name__ if w._worker else None}")
print(f"worker 的 finished 信号有自定义吗 = "
      f"{'finished' in type(w._worker).__dict__ if w._worker else 'N/A'}")
if w._worker is not None:
    print(f"worker 基类 = {[c.__name__ for c in type(w._worker).__mro__[:4]]}")

pathlib.Path("scan-busy.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp("报告 -> scan-busy.txt")
