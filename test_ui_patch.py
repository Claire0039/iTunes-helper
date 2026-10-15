#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ui_patch.py —— 验证界面层的三处改动

  1. 侧栏提示里出现了「支持 .ncm」
  2. 启动日志说明了 NCM 支持已启用
  3. 把 .ncm 文件直接拖进窗口能载入所在文件夹（原版只接受文件夹）
  4. 拖文件夹 / 拖非 ncm 文件时，原版行为不变
"""
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
sys.path.append(str(RUNTIME))
if hasattr(os, "add_dll_directory"):
    for d in (RUNTIME, RUNTIME / "PySide6", RUNTIME / "shiboken6"):
        if d.is_dir():
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass

NCM_CACHE = HERE / "e2e" / "cache"
os.environ["ITUNES_ASSISTANT_NCM_CACHE"] = str(NCM_CACHE)

checks = 0
fails = []


def check(name, cond, detail=""):
    global checks
    checks += 1
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if not cond else ""))
    if not cond:
        fails.append(f"{name} [{detail}]")


import ncm_patch  # noqa: E402

ncm_patch.install()

from PySide6.QtWidgets import (QApplication, QLabel, QPlainTextEdit,  # noqa: E402
                               QWidget)
import app  # noqa: E402

qapp = QApplication.instance() or QApplication([])
window = app.MainWindow()

print("\n[1] 侧栏提示\n")
labels = [lb.text() for lb in window.findChildren(QLabel)]
hit = [t for t in labels if "源文件夹" in t]
print(f"  源文件夹标签: {hit!r}")
check("标签里出现了「源文件夹」", len(hit) == 1, str(hit))
check("标签补充了「支持 .ncm」", hit and "支持 .ncm" in hit[0], str(hit))

print("\n[2] 启动日志\n")
log_text = ""
for te in window.findChildren(QPlainTextEdit):
    log_text += te.toPlainText()
print("  日志内容:")
for line in log_text.splitlines():
    print(f"    {line}")
check("日志里有 NCM 启用提示", "NCM 支持已启用" in log_text)

print("\n[3] 拖放 .ncm 文件\n")
FIX = HERE / "e2e-fixtures"
drag_files = [FIX / "jia-mp3.ncm", FIX / "yi-flac.ncm"]


def make_drop(paths):
    """
    轻量假事件。真正构造 QDropEvent 需要一次真实的拖放事务，
    在测试里构造会触发 Qt 的访问违例；而补丁只用到 mimeData().urls()
    和 acceptProposedAction()，一个假对象就够了，也更聚焦。
    """
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

    return _Event(paths)


window.source_edit.setText("")
window.output_edit.setText("")
window.dropEvent(make_drop(drag_files))
print(f"  拖入 2 个 .ncm -> source_edit = {window.source_edit.text()!r}")
print(f"                   output_edit = {window.output_edit.text()!r}")
check("拖 .ncm 文件会载入其所在文件夹",
      pathlib.Path(window.source_edit.text()).resolve() == FIX.resolve(),
      window.source_edit.text())
check("输出目录默认填了上级目录",
      pathlib.Path(window.output_edit.text()).resolve() == FIX.parent.resolve(),
      window.output_edit.text())

print("\n[4] 原有拖放行为不受影响\n")
folder = HERE / "e2e-fixtures"
window.source_edit.setText("")
window.output_edit.setText("")
window.dropEvent(make_drop([folder]))
print(f"  拖入文件夹 -> source_edit = {window.source_edit.text()!r}")
check("拖文件夹仍然走原逻辑", pathlib.Path(window.source_edit.text()).resolve() == folder.resolve(),
      window.source_edit.text())

# 拖入「不支持的文件」应回退到原逻辑（不接管、不设置覆盖）
plain = HERE / "e2e-fixtures" / "expected.json"
window.source_edit.setText("")
window.output_edit.setText("")
before = ncm_patch.has_scan_override()
ncm_patch.clear_scan_override()
window.dropEvent(make_drop([plain]))
print(f"  拖入不支持的 .json -> source_edit = {window.source_edit.text()!r}")
check("不支持的文件不被接管（保持原行为）", window.source_edit.text() == "",
      window.source_edit.text())
check("不支持的文件不会设置扫描覆盖", not ncm_patch.has_scan_override())
ncm_patch.clear_scan_override()

# 只有一个 .ncm 且 output_root 已有值时不覆盖用户输入
window.source_edit.setText("")
window.output_edit.setText("D:\\已有输出")
window.dropEvent(make_drop([FIX / "jia-mp3.ncm"]))
check("输出目录已填写时不覆盖用户输入", window.output_edit.text() == "D:\\已有输出",
      window.output_edit.text())
ncm_patch.clear_scan_override()

print("\n[5] 第二版新增控件已注入\n")
check("顶部播放器栏存在", any(type(c).__name__ == "PlayerBar"
                            for c in window.findChildren(QWidget)))
check("表格下方详情面板存在", any(type(c).__name__ == "DetailPanel"
                              for c in window.findChildren(QWidget)))
check("窗口 objectName 已修正为 Root", window.objectName() == "Root",
      window.objectName())

window.close()

print("\n" + "─" * 60)
if not fails:
    print(f"界面集成验证全部通过：{checks} 项 ✓")
    sys.exit(0)
print(f"通过 {checks - len(fails)}，失败 {len(fails)} ✗")
for x in fails:
    print("  -", x)
sys.exit(1)
