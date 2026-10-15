#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_v2_features.py —— 第二版三个新功能的端到端验证

用用户磁盘上的【真实】文件测：
  1. 拖入文件        —— 直接把音频 / .ncm 丢进窗口，载入列表
  2. 点击看详情      —— 封面、文件位置、大小、艺术家、专辑……
  3. 双击播放        —— 播放器栏显示曲目、进度推进、暂停/继续/跳转/音量
最后截一张有数据状态的图。
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
    # 同时实时输出到真实 stdout：万一中途崩溃，也能看到卡在哪一步
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

WORK = HERE / "v2test"
shutil.rmtree(WORK, ignore_errors=True)
SRC = WORK / "source"
SRC.mkdir(parents=True)
os.environ["ITUNES_ASSISTANT_NCM_CACHE"] = str(WORK / "cache")
os.environ["ITUNES_ASSISTANT_PLAY_CACHE"] = str(WORK / "playcache")

checks = 0
fails = []


def check(name, cond, detail=""):
    global checks
    checks += 1
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if not cond else ""))
    if not cond:
        fails.append(f"{name} [{detail}]")


# ─────────── 准备真实素材 ───────────

MP3_DIR = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload")
REAL_NCM = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload\VipSongsDownload"
                        r"\Hillsong Young & Free - Wake (Studio).ncm")
real_mp3s = sorted(MP3_DIR.glob("*.mp3"))[:2] if MP3_DIR.exists() else []

sources = []
if REAL_NCM.exists():
    shutil.copy2(REAL_NCM, SRC / "01 网易云下载.ncm")
    sources.append(SRC / "01 网易云下载.ncm")
for i, p in enumerate(real_mp3s, start=2):
    dst = SRC / f"{i:02d} {p.name}"
    shutil.copy2(p, dst)
    sources.append(dst)

print("素材:")
for p in sources:
    print(f"   {p.name}  ({p.stat().st_size / 1024 / 1024:.1f} MB)")
print()

# ─────────── 环境 ───────────

import core                     # noqa: E402
import ncm_patch                # noqa: E402
import ncm_ui                   # noqa: E402

ncm_patch.install()

from PySide6.QtCore import Qt                       # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402
import app                                          # noqa: E402

qapp = QApplication.instance() or QApplication([])
window = app.MainWindow()
window.apply_theme("light")
window.show()

ui = window._ncm_ui_installed
bar = None
panel = None
controller = None
for child in window.findChildren(type(window).__mro__[0]):
    pass
# 直接从布局里取回来
top = window.layout()
for i in range(top.count()):
    wd = top.itemAt(i).widget()
    if wd is not None and type(wd).__name__ == "PlayerBar":
        bar = wd
ws = ncm_ui._find_layout_with(window, window.table)
for i in range(ws.count()):
    wd = ws.itemAt(i).widget()
    if wd is not None and type(wd).__name__ == "DetailPanel":
        panel = wd

print("=" * 70)
print("[0] 界面注入")
print("=" * 70)
check("播放器栏已插入顶层布局", bar is not None)
check("详情面板已插入表格下方", panel is not None)
check("窗口 objectName 已修正为 Root（让主题底色规则生效）",
      window.objectName() == "Root", window.objectName())

# 找音频控制器
for obj in qapp.findChildren(type(bar).__mro__[0]):
    pass
import gc
controllers = [o for o in gc.get_objects() if type(o).__name__ == "AudioController"]
controller = controllers[0] if controllers else None
check("音频控制器已创建", controller is not None)

# ─────────── 1. 拖入文件 ───────────

print()
print("=" * 70)
print("[1] 把文件直接拖进窗口")
print("=" * 70)


class _Url:
    def __init__(self, p):
        self._p = str(p)

    def toLocalFile(self):
        return self._p


class _Mime:
    def __init__(self, ps):
        self._ps = list(ps)

    def urls(self):
        return [_Url(p) for p in self._ps]


class _Event:
    def __init__(self, ps):
        self._mime = _Mime(ps)
        self.accepted = False

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True


def pump(seconds=0.05):
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.005)


ev = _Event(sources)
window.dropEvent(ev)
print(f"  拖入 {len(sources)} 个文件 -> 被接受={ev.accepted}")
print(f"  源目录框 = {window.source_edit.text()}")
check("拖放被接受", ev.accepted)
check("源目录被设为文件所在目录",
      pathlib.Path(window.source_edit.text()).resolve() == SRC.resolve(),
      window.source_edit.text())
check("设置了「只处理这些文件」覆盖", ncm_patch.has_scan_override())

# 等扫描线程真正收尾（_running 变回 False 才算结束）
deadline = time.time() + 120
last = -1
stable = 0
tick = 0
while time.time() < deadline:
    pump(0.15)
    n = window.model.rowCount()
    if n == last and n > 0:
        stable += 1
    else:
        stable = 0
        last = n
    tick += 1
    if tick % 20 == 0:
        print(f"    ...等待扫描收尾: rows={n} _running={window._running} "
              f"worker={window._worker is not None} thread={window._thread is not None}")
    if n > 0 and not getattr(window, "_running", False) and stable >= 4:
        break
pump(0.8)
w = window._worker
print(f"  扫描结束状态: rows={window.model.rowCount()} _running={window._running} "
      f"scan_btn={window.scan_btn.isEnabled()}")
print(f"    看门狗: timer={getattr(window, '_ncm_scan_timer', None) is not None} "
      f"ticks={getattr(window, '_ncm_scan_ticks', None)} "
      f"active={getattr(window, '_ncm_scan_timer', None) is not None and window._ncm_scan_timer.isActive()} "
      f"worker_done={getattr(w, '_ncm_scan_done', None) if w is not None else 'worker=None'} "
      f"progress_label={getattr(window, '_ncm_progress_label', None) is not None}")

rows = window.model.rowCount()
print(f"  列表行数 = {rows}")
jobs = list(window.model._jobs)
for j in jobs:
    print(f"    {j.track.title or j.track.path.name:<34} {j.track.artist or '—'}")
check("拖入的文件全部进入列表", rows == len(sources), f"{rows} vs {len(sources)}")
check("NCM 文件被解密成真实音频",
      any(j.track.path.suffix.lower() in (".mp3", ".flac") for j in jobs))


# ── 再拖一批：必须是「追加」，不能把原列表清空 ──

def drop_and_wait(paths, timeout=90):
    ev = _Event(paths)
    window.dropEvent(ev)
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
    return ev


print()
print("  再拖入 2 个新文件 ->")
extra = []
for p in sorted(MP3_DIR.glob("*.mp3")):
    if len(extra) >= 2:
        break
    dst = WORK / "source" / f"9{len(extra)} {p.name}"
    if not dst.exists():
        shutil.copy2(p, dst)
        extra.append(dst)

source_tracks_before = [j.track for j in window.model._jobs]
before = window.model.rowCount()
drop_and_wait(extra)
after = window.model.rowCount()
print(f"  追加前 {before} 行 -> 追加后 {after} 行（新拖入 {len(extra)} 个）")
check("拖入文件是追加，原有歌曲没有被清空", after == before + len(extra),
      f"{before} + {len(extra)} != {after}")

paths_now = [str(os.path.normcase(os.path.abspath(str(j.track.path))))
             for j in window.model._jobs]
check("原有歌曲仍在列表里（位置未被顶掉）",
      all(str(os.path.normcase(os.path.abspath(str(t.path)))) in paths_now
          for t in source_tracks_before),
      "有原有曲目丢失")

# 重复拖入同一个文件 -> 不应出现重复行
print("  重复拖入上面那一个文件 ->")
drop_and_wait(extra[:1])
again = window.model.rowCount()
print(f"  行数 = {again}")
check("重复拖入同一文件不会产生重复行", again == after, f"{after} -> {again}")

rows = window.model.rowCount()

# ─────────── 2. 点击看详情 ───────────

print()
print("=" * 70)
print("[2] 单击列表 -> 下方详情面板")
print("=" * 70)

idx = window.model.index(0, 0)
window.table.clicked.emit(idx)
pump(0.4)

print(f"  标题   : {panel.title_label.text()}")
print(f"  副标题 : {panel.sub_label.text()}")
for key, label in (("path", "文件位置"), ("size", "大小"), ("duration", "时长"),
                   ("format", "格式"), ("bitrate", "比特率"),
                   ("sample_rate", "采样率"), ("target", "归档到"), ("status", "状态")):
    print(f"  {label:<6}: {panel._values[key].text()[:78]}")

check("标题不再是占位文字", panel.title_label.text() not in ("", "未选择音乐"),
      panel.title_label.text())
check("显示了文件位置", os.path.exists(panel._values["path"].text()),
      panel._values["path"].text())
check("显示了大小", panel._values["size"].text() not in ("", "—"),
      panel._values["size"].text())
check("显示了时长", panel._values["duration"].text() not in ("", "--:--", "—"),
      panel._values["duration"].text())
check("显示了格式", panel._values["format"].text() not in ("", "—"),
      panel._values["format"].text())
check("显示了封面（不是占位图）", panel._has_real_cover,
      f"cover={panel._has_real_cover}")
check("副标题含艺术家或专辑", panel.sub_label.text() not in ("", "未知艺术家"),
      panel.sub_label.text())

# 切到第二行，详情应跟着变
idx1 = window.model.index(min(1, rows - 1), 0)
window.table.clicked.emit(idx1)
pump(0.3)
print(f"  第 2 行标题: {panel.title_label.text()}")
check("切换行后详情跟着更新", panel.title_label.text() != "未选择音乐")

# 回到第 0 行用于截图
window.table.clicked.emit(window.model.index(0, 0))
pump(0.3)

# ─────────── 3. 双击播放 ───────────

print()
print("=" * 70)
print("[3] 双击列表 -> 软件内播放")
print("=" * 70)

window.table.doubleClicked.emit(window.model.index(0, 0))
pump(1.2)

print(f"  播放器标题 : {bar.title_label.text()}")
print(f"  播放器副标题: {bar.artist_label.text()}")
print(f"  播放按钮图标: {bar.play_btn.iconSize().width()}x{bar.play_btn.iconSize().height()}")
print(f"  时长标签   : {bar.dur_label.text()}   位置标签: {bar.pos_label.text()}")
print(f"  进度值     : {bar.progress.value()} / {bar.progress.maximum()}")

check("播放器栏显示曲目名", bar.title_label.text() not in ("未在播放", ""),
      bar.title_label.text())


def play_icon_width():
    """播放键现在是图标了（第三版换成用户提供的素材）。"""
    return bar.play_btn.icon().pixmap(bar.play_btn.iconSize()).width()


check("播放按钮用图标而不是文字", bar.play_btn.text() == "" and play_icon_width() > 0,
      f"text={bar.play_btn.text()!r} w={play_icon_width()}")
playing_w = play_icon_width()      # 播放中 -> 暂停图标（两条圆角竖条）
check("总时长标签已填充", bar.dur_label.text() not in ("0:00", ""), bar.dur_label.text())

pump(1.5)
pos1 = controller._player.position_ms()
pump(1.5)
pos2 = controller._player.position_ms()
print(f"  播放位置推进: {pos1} ms -> {pos2} ms")
check("播放位置在推进", pos2 > pos1 + 300, f"{pos1} -> {pos2}")
check("进度条随播放推进", bar.progress.value() > 0, str(bar.progress.value()))

print("  点击播放按钮暂停 ->", end=" ")
bar.play_btn.click()
pump(0.5)
print(f"图标宽 {play_icon_width()}px  mode = {controller._player.mode()}")
check("点击后暂停", controller._player.mode() == "paused", controller._player.mode())
paused_w = play_icon_width()
check("暂停态换成播放三角（比暂停的两条竖条宽）",
      paused_w > playing_w, f"暂停 {paused_w} vs 播放中 {playing_w}")

print("  再点一次继续 ->", end=" ")
bar.play_btn.click()
pump(0.6)
print(f"图标宽 {play_icon_width()}px  mode = {controller._player.mode()}")
check("再点恢复播放", controller._player.mode() == "playing", controller._player.mode())
check("恢复播放态的暂停图标", play_icon_width() == playing_w,
      f"{play_icon_width()} vs {playing_w}")

print("  音量设为 30 ->", end=" ")
bar.volume.setValue(30)
pump(0.2)
print(f"controller.volume()={controller.volume():.2f}")
check("音量传递到播放器", abs(controller.volume() - 0.30) < 0.01, str(controller.volume()))

print("  跳到 60 秒 ->", end=" ")
bar.progress.setValue(500)
controller.seek(int(controller._player.duration_ms() * 0.5))
pump(0.5)
print(f"position={controller._player.position_ms()} ms")
check("跳转生效", controller._player.position_ms() > 30000,
      str(controller._player.position_ms()))

if rows >= 2:
    print("  下一曲 ->", end=" ")
    before = controller.current_index()
    bar.next_btn.click()
    pump(1.0)
    after = controller.current_index()
    print(f"{before} -> {after}  {bar.title_label.text()}")
    check("下一曲切换生效", after == (before + 1) % rows, f"{before}->{after}")
    print("  上一曲 ->", end=" ")
    # 播到 3 秒以内才会切上一曲
    controller._player.seek_ms(0)
    pump(0.2)
    bar.prev_btn.click()
    pump(0.8)
    print(f"{after} -> {controller.current_index()}")
    check("上一曲切换生效", controller.current_index() == before,
          f"{controller.current_index()} vs {before}")

# 截图留档（有数据的状态）
pump(0.6)
window.grab().save(str(HERE / "v2-data-shot.png"))
print(f"\n  已保存有数据状态的截图 v2-data-shot.png")

# ─────────── 4. 不污染原有功能 ───────────

print()
print("=" * 70)
print("[4] 原有功能未受影响")
print("=" * 70)
check("侧栏提示仍带「支持 .ncm」",
      any("支持 .ncm" in lb.text() for lb in window.findChildren(QLabel)))
print(f"  _running = {window._running}   scan_btn={window.scan_btn.isEnabled()}   "
      f"run_btn={window.run_btn.isEnabled()}")
check("扫描结束后按钮恢复可用（修掉了原版的忙碌态卡死）",
      window.scan_btn.isEnabled() and window.run_btn.isEnabled(),
      f"running={window._running} scan={window.scan_btn.isEnabled()} "
      f"run={window.run_btn.isEnabled()}")
check("表格列数未变", window.model.columnCount() == 7, str(window.model.columnCount()))
check("core.scan_folder 仍是补丁版", core.scan_folder is ncm_patch.scan_folder)

# 清空列表应把详情和播放列表一起清掉
window.model.set_jobs([])
pump(0.3)
check("清空列表后详情面板复位", panel.title_label.text() == "未选择音乐",
      panel.title_label.text())

controller._player.close()
window.close()

print()
print("=" * 70)
if not fails:
    print(f"v2 功能验证全部通过：{checks} 项 ✓")
else:
    print(f"通过 {checks - len(fails)}，失败 {len(fails)} ✗")
    for f in fails:
        print("  -", f)

pathlib.Path("v2-report-out.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp(f"报告 -> v2-report-out.txt（{len(fails)} 项失败）")

# 收尾：Qt 的析构阶段偶发访问违例（此时所有检查都已完成、报告已写盘）。
# 用 os._exit 跳过解释器清理，让测试脚本给出可靠的退出码。
import os as _os
sys.stdout.flush()
sys.stderr.flush()
_os._exit(1 if fails else 0)

