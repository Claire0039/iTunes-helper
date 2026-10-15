#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trace_scan.py —— 追踪扫描收尾的每一步到底走到哪里。"""
import builtins
import io
import os
import pathlib
import shutil
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

WORK = HERE / "v2test"
SRC = WORK / "source"
os.environ["ITUNES_ASSISTANT_NCM_CACHE"] = str(WORK / "cache")
os.environ["ITUNES_ASSISTANT_PLAY_CACHE"] = str(WORK / "playcache")
sys.path.insert(0, str(HERE))

import ncm_patch          # noqa: E402
ncm_patch.install()

import app                # noqa: E402
from PySide6.QtCore import QThread, QCoreApplication   # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

print("install 后:")
print("  _scan_bridge =", ncm_patch._scan_bridge)
print("  Worker.do_scan 是补丁版 =",
      "patched_do_scan" in getattr(app.Worker.do_scan, "__qualname__", ""),
      getattr(app.Worker.do_scan, "__qualname__", None))
print("  MainWindow.on_finished 是补丁版 =",
      "patched_on_finished" in getattr(app.MainWindow.on_finished, "__qualname__", ""),
      getattr(app.MainWindow.on_finished, "__qualname__", None))

# 给两个补丁函数加追踪
_real_on_finished = app.MainWindow.on_finished


def traced_on_finished(self, summary=None, *a, **kw):
    main = QCoreApplication.instance().thread()
    cur = QThread.currentThread()
    print(f"    [on_finished] 收到 {type(summary).__name__} 值={summary!r} "
          f"主线程={cur is main}")
    r = _real_on_finished(self, summary, *a, **kw)
    return r


app.MainWindow.on_finished = traced_on_finished

if ncm_patch._scan_bridge is not None:
    _real_handle = ncm_patch._scan_bridge.handle

    def traced_handle(window):
        main = QCoreApplication.instance().thread()
        cur = QThread.currentThread()
        print(f"    [bridge.handle] 主线程={cur is main}")
        return _real_handle(window)

    ncm_patch._scan_bridge.handle = traced_handle

qapp = QApplication.instance() or QApplication([])
w = app.MainWindow()
w.apply_theme("light")
w.show()

# 用和测试里完全一样的方式：dropEvent
class _Url:
    def __init__(self, p): self._p = str(p)
    def toLocalFile(self): return self._p


class _Mime:
    def __init__(self, ps): self._ps = list(ps)
    def urls(self): return [_Url(p) for p in self._ps]


class _Event:
    def __init__(self, ps): self._mime = _Mime(ps)
    def mimeData(self): return self._mime
    def acceptProposedAction(self): pass


files = sorted(SRC.glob("*"))[:3]
print("拖入:", [f.name for f in files])
w.dropEvent(_Event(files))

end = time.time() + 20
while time.time() < end:
    qapp.processEvents()
    time.sleep(0.01)
    if not w._running:
        break
print("  _running =", w._running, " rows =", w.model.rowCount())
print("  worker =", w._worker, " thread =", w._thread)
if w._thread is not None:
    print("  thread.isRunning =", w._thread.isRunning(),
          " isFinished =", w._thread.isFinished())

pathlib.Path("trace-scan.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp("报告 -> trace-scan.txt")
