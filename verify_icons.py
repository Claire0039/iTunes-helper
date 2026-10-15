#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_icons.py —— 验证播放器图标：深色主题染色 / 暂停态 / 单曲循环角标"""
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

WORK = HERE / "verifyicons"
shutil.rmtree(WORK, ignore_errors=True)
(WORK / "source").mkdir(parents=True)
os.environ["ITUNES_ASSISTANT_NCM_CACHE"] = str(WORK / "cache")
os.environ["ITUNES_ASSISTANT_PLAY_CACHE"] = str(WORK / "playcache")
sys.path.insert(0, str(HERE))

MUSIC = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload")
for p in sorted(MUSIC.glob("*.mp3"))[:3]:
    shutil.copy2(p, WORK / "source" / p.name)

import ncm_patch   # noqa: E402

ncm_patch.install()

from PySide6.QtCore import QRect, Qt          # noqa: E402
from PySide6.QtWidgets import QApplication    # noqa: E402
import app                                    # noqa: E402

qapp = QApplication.instance() or QApplication([])
window = app.MainWindow()
window.show()


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


def shot(name, rect=None):
    pump(0.5)
    img = window.grab().toImage()
    if rect:
        img = img.copy(QRect(*rect))
        img = img.scaled(img.width() * 2, img.height() * 2,
                         Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    img.save(str(HERE / name))
    print(f"  已保存 {name}")


# 1. 浅色主题
window.apply_theme("light")
window.source_edit.setText(str(WORK / "source"))
window.check_recursive.setChecked(False)
window.start_scan()
end = time.time() + 60
while time.time() < end:
    pump(0.2)
    if not window._running and window.model.rowCount() > 0:
        break
pump(0.5)
print(f"列表 {window.model.rowCount()} 行")

# 键位几何
for btn, tag in ((bar.prev_btn, "prev"), (bar.play_btn, "play"),
                 (bar.next_btn, "next"), (bar.shuffle_btn, "shuffle"),
                 (bar.repeat_btn, "repeat")):
    pm = btn.icon().pixmap(btn.iconSize())
    print(f"  {tag:<8} 尺寸={pm.width()}x{pm.height()}  图标为空={pm.isNull()}")

shot("v4-light-bar.png", (0, 78, 2560, 150))

# 2. 深色主题
window.apply_theme("dark")
shot("v4-dark-bar.png", (0, 78, 2560, 150))
pump(0.3)

# 3. 播放 -> 暂停图标
idx = window.model.index(0, 0)
window.table.doubleClicked.emit(idx)
pump(2.0)
pm = bar.play_btn.icon().pixmap(bar.play_btn.iconSize())
print(f"  播放中：播放键图标 {pm.width()}x{pm.height()}（应为暂停的两条竖条）")
shot("v4-dark-playing.png", (0, 78, 1500, 150))

# 4. 单曲循环角标
bar.repeat_btn.click()
pump(0.2)
bar.repeat_btn.click()
pump(0.2)
print(f"  循环状态 = {bar._controller.repeat}")
pm = bar.repeat_btn.icon().pixmap(bar.repeat_btn.iconSize())
print(f"  循环键图标 {pm.width()}x{pm.height()}（比 off 态宽出「1」的位置）")
shot("v4-dark-repeat-one.png", (2340, 90, 200, 120))

# 5. 回到浅色看播放态
bar._controller._player.close()
window.apply_theme("light")
pump(0.3)
pm = bar.play_btn.icon().pixmap(bar.play_btn.iconSize())
print(f"  停止后恢复播放三角：{pm.width()}x{pm.height()}")

shot("v4-light-toggles.png", (2340, 90, 200, 120))
window.apply_theme("dark")
bar.repeat_btn.click()
pump(0.3)
shot("v4-dark-toggles.png", (2300, 90, 260, 120))

pathlib.Path("verify-icons-report.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp("报告 -> verify-icons-report.txt")
sys.stdout.flush()
os._exit(0)
