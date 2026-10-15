#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_volume.py —— 生成音量滑杆在大/中/小三种音量下的对比图（浅色 / 深色）"""
import builtins
import io
import os
import pathlib
import sys
import time

_buf = io.StringIO()
_rp = builtins.print


def print(*a, **k):          # noqa: A001
    _rp(*a, **k)
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
os.environ["ITUNES_ASSISTANT_NCM_CACHE"] = str(HERE / "voltestcache")

import ncm_patch   # noqa: E402

ncm_patch.install()

from PySide6.QtCore import QRect, Qt          # noqa: E402
from PySide6.QtGui import QImage, QPainter    # noqa: E402
from PySide6.QtWidgets import QApplication    # noqa: E402
import app                                    # noqa: E402

qapp = QApplication.instance() or QApplication([])
window = app.MainWindow()
window.show()
window.setFixedSize(1463, 843)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


bar = None
top = window.layout()
for i in range(top.count()):
    wd = top.itemAt(i).widget()
    if wd is not None and type(wd).__name__ == "PlayerBar":
        bar = wd

print(f"音量滑杆: {bar.volume.width()}x{bar.volume.height()}  范围 {bar.volume.minimum()}..{bar.volume.maximum()}")

for theme in ("light", "dark"):
    window.apply_theme(theme)
    pump(0.4)
    tiles = []
    for value in (100, 50, 0):
        bar.volume.setValue(value)
        pump(0.25)
        img = window.grab().toImage()
        # grab() 出来的图带 devicePixelRatio，mapTo 给的是逻辑坐标，必须换算
        dpr = img.width() / max(1, window.width())
        rect = bar.volume.mapTo(window, bar.volume.rect().topLeft())
        tile = img.copy(QRect(int((rect.x() - 6) * dpr), int((rect.y() - 4) * dpr),
                              int((bar.volume.width() + 12) * dpr),
                              int((bar.volume.height() + 8) * dpr)))
        tiles.append(tile)
        print(f"  {theme} 音量={value:>3}  滑块位置 x={bar.volume.sliderPosition()}  "
              f"dpr={dpr:.2f}  图块 {tile.width()}x{tile.height()}")

    pad = 12
    width = max(t.width() for t in tiles)
    height = sum(t.height() for t in tiles) + pad * (len(tiles) + 1)
    sheet = QImage(width + pad * 2, height, QImage.Format.Format_ARGB32)
    bg = "#f2f4f7" if theme == "light" else "#101216"
    sheet.fill(Qt.GlobalColor.white if theme == "light" else Qt.GlobalColor.black)
    painter = QPainter(sheet)
    y = pad
    for t in tiles:
        painter.drawImage(pad, y, t)
        y += t.height() + pad
    painter.end()
    out = HERE / f"v5-volume-{theme}.png"
    sheet.save(str(out))
    print(f"  已保存 {out.name}")

window.apply_theme("light")
pathlib.Path("verify-volume-report.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp("报告 -> verify-volume-report.txt")
sys.stdout.flush()
os._exit(0)
