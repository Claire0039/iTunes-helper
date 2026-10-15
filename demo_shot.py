#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_shot.py —— 用真实音乐截图：播放器在播、详情面板有封面、进度文字在走。"""
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

WORK = HERE / "demoshot"
shutil.rmtree(WORK, ignore_errors=True)
(WORK / "source").mkdir(parents=True)
os.environ["ITUNES_ASSISTANT_NCM_CACHE"] = str(WORK / "cache")
os.environ["ITUNES_ASSISTANT_PLAY_CACHE"] = str(WORK / "playcache")
sys.path.insert(0, str(HERE))

MUSIC = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload")
SRC = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload\VipSongsDownload")
copied = 0
for p in sorted(MUSIC.glob("*.mp3"))[:4]:
    shutil.copy2(p, WORK / "source" / p.name)
    copied += 1
for p in sorted(SRC.glob("*.ncm"))[:1]:
    shutil.copy2(p, WORK / "source" / p.name)
    copied += 1
print(f"素材 {copied} 个")

import ncm_patch   # noqa: E402

ncm_patch.install()

from PySide6.QtWidgets import QApplication   # noqa: E402
import app                                   # noqa: E402

qapp = QApplication.instance() or QApplication([])
window = app.MainWindow()

# 侧栏收起一点给表格让位（不影响功能）
window.apply_theme("light")
window.show()
window.source_edit.setText(str(WORK / "source"))
window.check_recursive.setChecked(False)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


# 1. 扫描
window.start_scan()
deadline = time.time() + 60
while time.time() < deadline:
    pump(0.15)
    if not window._running and window.model.rowCount() > 0:
        break
pump(0.5)
rows = window.model.rowCount()
print(f"扫描完成，列表 {rows} 行")

# 2. 选中第一行 -> 详情面板
idx = window.model.index(0, 0)
window.table.setCurrentIndex(idx)
window.table.clicked.emit(idx)
pump(0.8)

# 3. 双击播放
bar = None
top = window.layout()
for i in range(top.count()):
    wd = top.itemAt(i).widget()
    if wd is not None and type(wd).__name__ == "PlayerBar":
        bar = wd
print("播放器栏:", bar is not None)

window.table.doubleClicked.emit(idx)
pump(2.5)

if bar is not None:
    print(f"  标题={bar.title_label.text()!r}")
    print(f"  艺术家={bar.artist_label.text()!r}")
    print(f"  时间={bar.pos_label.text()} / {bar.dur_label.text()}")
    print(f"  封面有图={not bar.cover.pixmap().isNull()}")
    ctrl = bar._controller
    print(f"  播放中={ctrl.mode()!r} 位置={ctrl.position_ms()}ms")

# 4. 顺便演示一下转换进度文字
ncm_patch._note_progress("转换", 37, 213)
pump(0.6)
if window.progress is not None:
    print(f"  进度条文字={window.progress.format()!r}")

pump(0.5)
window.grab().save(str(HERE / "v3-playing.png"))
print("已保存 v3-playing.png")

if bar is not None:
    bar._controller._player.close()
pathlib.Path("demo-report.txt").write_text(_buf.getvalue(), encoding="utf-8")
sys.stdout.flush()
os._exit(0)
