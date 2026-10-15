#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_drag_drop.py —— 拖放的**真实 Qt 事件链**验证

之前的测试是直接调用 window.dropEvent(...)，绕过了 dragEnterEvent / dragMoveEvent，
因此没能发现「dragMoveEvent 没被 accept → 光标禁止 → 松手不派发 dropEvent」这个 bug。
这个文件改成走完整事件链：dragEnter -> dragMove -> drop。
"""
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
    # 同时实时输出：万一中途崩溃也能看到卡在哪一步
    _rp(*a, flush=True)
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

WORK = HERE / "droptest"
shutil.rmtree(WORK, ignore_errors=True)
(WORK / "source").mkdir(parents=True)
(WORK / "elsewhere").mkdir(parents=True)
os.environ["ITUNES_ASSISTANT_NCM_CACHE"] = str(WORK / "cache")
os.environ["ITUNES_ASSISTANT_PLAY_CACHE"] = str(WORK / "playcache")
sys.path.insert(0, str(HERE))

checks = 0
fails = []


def check(name, cond, detail=""):
    global checks
    checks += 1
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if not cond else ""))
    if not cond:
        fails.append(f"{name} [{detail}]")


# 素材：真实音乐 + 一个不支持的格式
MUSIC = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload")
batch_a = []
for p in sorted(MUSIC.glob("*.mp3"))[:2]:
    dst = WORK / "source" / p.name
    shutil.copy2(p, dst)
    batch_a.append(dst)
batch_b = []
for p in sorted(MUSIC.glob("*.mp3"))[2:4]:
    dst = WORK / "elsewhere" / p.name
    shutil.copy2(p, dst)
    batch_b.append(dst)
not_audio = WORK / "elsewhere" / "说明.txt"
not_audio.write_text("不是音频", encoding="utf-8")
folder = WORK / "source"

print(f"素材: A 批 {len(batch_a)} 个, B 批 {len(batch_b)} 个, 另加 1 个 .txt 和 1 个文件夹")

import ncm_patch   # noqa: E402

ncm_patch.install()

from PySide6.QtCore import (QMimeData, QPoint, Qt, QUrl)               # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication                             # noqa: E402
import app                                                             # noqa: E402

qapp = QApplication.instance() or QApplication([])
window = app.MainWindow()
window.show()
window.setFixedSize(1463, 843)
POS = QPoint(700, 400)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)


def mime_for(paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


# 说明：QApplication.sendEvent 对「合成的 DragMove 事件」只会派发一次，
# 之后 Qt 的拖放会话状态就不再把它转给控件（真实拖拽由系统驱动）。
# 所以判定 accept 的检查一律**直接调用处理器**——确定且可重复；
# 另外再用 sendEvent 走一次完整链路，证明真实拖放确实能到 dropEvent。
_keepalive = []


def make_event(cls, paths):
    # QMimeData 必须由我们持有引用：事件内部只存裸指针，临时对象被 GC 就是野指针
    mime = mime_for(paths)
    _keepalive.append(mime)
    return cls(POS, Qt.DropAction.CopyAction, mime,
               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def accepts(handler, event):
    """直接调用事件处理器，返回它是否接受了这个事件。"""
    handler(event)
    return event.isAccepted()


def drag_enter_ok(paths):
    return accepts(window.dragEnterEvent, make_event(QDragEnterEvent, paths))


def drag_move_ok(paths):
    return accepts(window.dragMoveEvent, make_event(QDragMoveEvent, paths))


def drop_via_send_event(paths):
    """
    真实链路：dragEnter -> dragMove -> drop，全部交给 Qt 派发。

    注意 drop 事件只有在前面的 dragEnter 建立过拖放会话之后才会被派发到控件，
    所以必须先发 dragEnter/dragMove，不能只发一个 drop。
    """
    mime = mime_for(paths)
    _keepalive.append(mime)
    for cls in (QDragEnterEvent, QDragMoveEvent):
        event = cls(POS, Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        _keepalive.append(event)
        QApplication.sendEvent(window, event)
        pump(0.05)
    event = QDropEvent(POS, Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    _keepalive.append(event)
    QApplication.sendEvent(window, event)
    return event.isAccepted()


def wait_scan(timeout=90):
    deadline = time.time() + timeout
    stable = 0
    last = -1
    while time.time() < deadline:
        pump(0.2)
        n = window.model.rowCount()
        if n == last:
            stable += 1
        else:
            stable = 0
            last = n
        if not getattr(window, "_running", False) and stable >= 3:
            break
    pump(0.6)


def full_drop(paths):
    accepted = drop_via_send_event(paths)
    pump(0.4)
    wait_scan()
    return accepted


pump(0.5)


# ─────────── 1. 事件链：dragEnter / dragMove / drop ───────────

print()
print("=" * 70)
print("[1] 拖放事件链")
print("=" * 70)

check("MainWindow.dropEvent 已被接管",
      "patched_drop" in app.MainWindow.dropEvent.__qualname__,
      app.MainWindow.dropEvent.__qualname__)
check("MainWindow.dragMoveEvent 已被接管（关键修复点）",
      "patched_drag_move" in app.MainWindow.dragMoveEvent.__qualname__,
      app.MainWindow.dragMoveEvent.__qualname__)
check("窗口接受拖放", window.acceptDrops())
print("  事件处理器（直接调用，确定可重复）:")
check("dragEnter 接受音频文件", drag_enter_ok(batch_a))
check("dragMove 接受音频文件（不接受的话松手不会触发 drop）", drag_move_ok(batch_a))
check("dragMove 接受另一个目录的音频文件", drag_move_ok(batch_b))
check("dragMove 接受文件夹（走原来的整目录扫描）", drag_move_ok([folder]))

print("  拖入 A 批（走完整 Qt 事件链）->")
accepted = full_drop(batch_a)
check("drop 被接受", accepted)
check("文件进入列表", window.model.rowCount() == len(batch_a),
      f"{window.model.rowCount()} vs {len(batch_a)}")
check("设置了「只处理这些文件」覆盖", ncm_patch.has_scan_override())
check("源目录被设为文件所在目录",
      pathlib.Path(window.source_edit.text()) == folder, window.source_edit.text())


# ─────────── 2. 追加而不是清空 ───────────

print()
print("=" * 70)
print("[2] 拖入是追加，不清空原列表")
print("=" * 70)

# 临时追踪已移除

before = window.model.rowCount()
before_paths = [os.path.normcase(os.path.abspath(str(j.track.path)))
                for j in window.model._jobs]
print(f"  拖入 B 批（{len(batch_b)} 个）->")
check("dragMove 仍被接受", drag_move_ok(batch_b))
full_drop(batch_b)
after = window.model.rowCount()
print(f"  行数 {before} -> {after}")
check("原有歌曲没有被清空，新文件追加在后面",
      after == before + len(batch_b), f"{before}+{len(batch_b)} != {after}")
now_paths = [os.path.normcase(os.path.abspath(str(j.track.path)))
             for j in window.model._jobs]
check("原有曲目全部还在（且顺序在前）", now_paths[:len(before_paths)] == before_paths,
      str(now_paths[:len(before_paths)])[:80])

print("  重复拖入 A 批第一个 ->")
check("dragMove 被接受", drag_move_ok(batch_a[:1]))
full_drop(batch_a[:1])
check("重复拖入同一文件不产生重复行", window.model.rowCount() == after,
      f"{after} -> {window.model.rowCount()}")


# ─────────── 3. 不支持的格式 / 文件夹 ───────────

print()
print("=" * 70)
print("[3] 不支持的格式与文件夹")
print("=" * 70)

rows_before = window.model.rowCount()
print("  拖入一个 .txt ->")
move_txt = drag_move_ok([not_audio])
print(f"    dragMove 被接受 = {move_txt}")
check("不支持的格式拖动时光标为禁止（dragMove 不接受）", not move_txt)
drop_via_send_event([not_audio])
pump(0.5)
check("拖入不支持的文件不会改变列表", window.model.rowCount() == rows_before,
      f"{rows_before} -> {window.model.rowCount()}")

print("  拖入文件夹 ->")
check("文件夹的 dragMove 被接受（走原来的整目录扫描）", drag_move_ok([folder]))

# ─────────── 4. 列表与播放器仍可用 ───────────

print()
print("=" * 70)
print("[4] 拖放之后功能仍正常")
print("=" * 70)
check("扫描结束后按钮可用",
      window.scan_btn.isEnabled() and window.run_btn.isEnabled())
check("表格列数未变", window.model.columnCount() == 7)
controller = None
top = window.layout()
for i in range(top.count()):
    wd = top.itemAt(i).widget()
    if wd is not None and type(wd).__name__ == "PlayerBar":
        controller = wd._controller
check("播放器仍能取到歌曲列表", controller is not None)

window.grab().save(str(HERE / "drop-shot.png"))
print("  已保存 drop-shot.png")

window.close()
print()
print("=" * 70)
if not fails:
    print(f"拖放验证全部通过：{checks} 项 ✓")
else:
    print(f"通过 {checks - len(fails)}，失败 {len(fails)} ✗")
    for f in fails:
        print("  -", f)

pathlib.Path("drop-report-out.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp(f"报告 -> drop-report-out.txt（{len(fails)} 项失败）")
sys.stdout.flush()
os._exit(1 if fails else 0)
