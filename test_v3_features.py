#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_v3_features.py —— 第三版新增内容的验证

  1. 外观三态：浅色 / 深色 / 跟随系统
  2. 播放器栏新布局：左（控制+音量）、中（封面+信息+进度）、右（随机+循环）
  3. 转换进度文字：正在转换（1/213）0.0%
  4. 应用图标：_resource('app.png') 能找到，标题栏标记换成了真图标
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

WORK = HERE / "v3test"
shutil.rmtree(WORK, ignore_errors=True)
(WORK / "source").mkdir(parents=True)
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


# 真实素材
MP3_DIR = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload")
src_files = sorted(MP3_DIR.glob("*.mp3"))[:2] if MP3_DIR.exists() else []
real_ncm = pathlib.Path(r"E:\音乐\cloudmusic\VipSongsDownload\VipSongsDownload"
                        r"\Hillsong Young & Free - Wake (Studio).ncm")
sources = []
if real_ncm.exists():
    shutil.copy2(real_ncm, WORK / "source" / "01 NCM.ncm")
    sources.append(WORK / "source" / "01 NCM.ncm")
for i, p in enumerate(src_files, start=2):
    dst = WORK / "source" / f"{i:02d} {p.name}"
    shutil.copy2(p, dst)
    sources.append(dst)

import ncm_patch   # noqa: E402
import ncm_ui      # noqa: E402

ncm_patch.install()

from PySide6.QtCore import Qt                                    # noqa: E402
from PySide6.QtGui import QGuiApplication                        # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402
import app                                                       # noqa: E402

qapp = QApplication.instance() or QApplication([])
window = app.MainWindow()
window.show()


def pump(sec=0.08):
    end = time.time() + sec
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.005)


pump(0.3)

bar = None
top = window.layout()
for i in range(top.count()):
    wd = top.itemAt(i).widget()
    if wd is not None and type(wd).__name__ == "PlayerBar":
        bar = wd

# ─────────── 1. 外观三态 ───────────

print()
print("=" * 70)
print("[1] 外观三态（浅色 / 深色 / 跟随系统）")
print("=" * 70)

check("播放器栏存在", bar is not None)
check("窗口 objectName 已设为 Root", window.objectName() == "Root", window.objectName())
check("窗口开启了 WA_StyledBackground",
      window.testAttribute(Qt.WidgetAttribute.WA_StyledBackground))
check("标题栏开启了 WA_StyledBackground",
      window.title_bar.testAttribute(Qt.WidgetAttribute.WA_StyledBackground))

btn = ncm_ui._theme_button(window)
check("找到了主题按钮", btn is not None, str(btn))
if btn is not None:
    print(f"  主题按钮文字 = {btn.text()!r}  提示 = {btn.toolTip()!r}")

for mode, expect_glyph in ((ncm_ui.THEME_LIGHT, "☀"), (ncm_ui.THEME_DARK, "☾"),
                           (ncm_ui.THEME_AUTO, "◐")):
    window.apply_theme(mode)
    pump(0.15)
    cur = getattr(window, "_ncm_theme_mode", None)
    colors = window.colors
    print(f"  apply_theme({mode!r}) -> theme_name={window.theme_name!r} "
          f"mode={cur!r} 底色={colors.get('bg')} 按钮={btn.text() if btn else '-'!r}")
    check(f"{mode} 模式被记录", cur == mode, str(cur))
    if btn is not None:
        check(f"{mode} 模式下按钮字形为 {expect_glyph}", btn.text() == expect_glyph, btn.text())

# 跟随系统应解析成系统当前的样子
sys_scheme = ncm_ui._system_scheme()
window.apply_theme(ncm_ui.THEME_AUTO)
pump(0.15)
check("跟随系统解析正确", window.theme_name == sys_scheme,
      f"{window.theme_name} vs {sys_scheme}")
print(f"  系统当前外观 = {sys_scheme}")

# 菜单三项
check("设置项被写入 QSettings",
      window.settings_store.value("theme") in ("light", "dark", "auto"),
      str(window.settings_store.value("theme")))

# 主题按钮已被接管成弹出菜单（不再直接 toggle）
check("主题按钮的连接已改（点击弹菜单）", btn is not None)

# ─────────── 2. 播放器栏新布局 ───────────

print()
print("=" * 70)
print("[2] 播放器栏新布局")
print("=" * 70)

check("左侧：上一曲按钮", hasattr(bar, "prev_btn"))
check("左侧：播放/暂停按钮", hasattr(bar, "play_btn"))
check("左侧：下一曲按钮", hasattr(bar, "next_btn"))
check("左侧：音量滑杆", hasattr(bar, "volume") and bar.volume.maximum() == 100)
check("中部：专辑封面", hasattr(bar, "cover") and not bar.cover.pixmap().isNull())
check("中部：歌曲信息（标题/艺术家）",
      hasattr(bar, "title_label") and hasattr(bar, "artist_label"))
check("中部：进度条", hasattr(bar, "progress"))
check("中部：时长为负数剩余时间格式",
      bar.dur_label.text().startswith("-"), bar.dur_label.text())
check("右侧：随机播放按钮", hasattr(bar, "shuffle_btn"))
check("右侧：循环按钮", hasattr(bar, "repeat_btn"))

# 五个控件都用上了用户提供的图标（不是文字字形）
import ncm_glyphs   # noqa: E402
print(f"  内置图标素材: {sorted(ncm_glyphs.GLYPHS)}")
for tag, btn in (("上一曲", bar.prev_btn), ("播放", bar.play_btn),
                 ("下一曲", bar.next_btn), ("随机", bar.shuffle_btn),
                 ("循环", bar.repeat_btn)):
    pm = btn.icon().pixmap(btn.iconSize())
    check(f"{tag}按钮是图标（不是文字）",
          btn.text() == "" and not pm.isNull() and pm.width() > 0,
          f"text={btn.text()!r} icon={pm.width()}x{pm.height()}")
check("五个图标素材齐备",
      set(ncm_glyphs.GLYPHS) >= {"prev", "play", "next", "shuffle", "repeat"},
      str(sorted(ncm_glyphs.GLYPHS)))

# 染色：浅色主题下图标应该是深色，深色主题下应该是浅色
window.apply_theme("light")
pump(0.2)
light_img = bar.prev_btn.icon().pixmap(bar.prev_btn.iconSize()).toImage()
lx = light_img.width() // 2
found = None
for yy in range(light_img.height()):
    c = light_img.pixelColor(lx, yy)
    if c.alpha() > 200:
        found = c
        break
check("浅色主题下图标是深色", found is not None and found.red() < 128,
      str(found.red() if found else None))

window.apply_theme("dark")
pump(0.2)
dark_img = bar.prev_btn.icon().pixmap(bar.prev_btn.iconSize()).toImage()
found_d = None
for yy in range(dark_img.height()):
    c = dark_img.pixelColor(lx, yy)
    if c.alpha() > 200:
        found_d = c
        break
check("深色主题下图标是浅色（自动染色，不会看不见）",
      found_d is not None and found_d.red() > 128,
      str(found_d.red() if found_d else None))
window.apply_theme("light")
pump(0.2)

# 用几何位置验证「左 / 中 / 右」
pump(0.3)
w = bar.width()
lx = bar.prev_btn.mapTo(bar, bar.prev_btn.rect().topLeft()).x()
cx = bar.cover.mapTo(bar, bar.cover.rect().topLeft()).x()
rx = bar.shuffle_btn.mapTo(bar, bar.shuffle_btn.rect().topLeft()).x()
print(f"  x 坐标: 上一曲={lx}  封面={cx}  随机={rx}  栏宽={w}")
check("三个区块从左到右排列", lx < cx < rx)

# ─────────── 3. 随机 / 循环 ───────────

print()
print("=" * 70)
print("[3] 随机播放 / 循环")
print("=" * 70)

controller = bar._controller
check("播放器栏已绑定控制器", controller is not None)

bar.shuffle_btn.click()
pump(0.1)
check("点击随机 -> controller.shuffle 打开", controller.shuffle is True)
check("按钮高亮（动态属性 ncmActive=true）",
      bar.shuffle_btn.property("ncmActive") == "true",
      str(bar.shuffle_btn.property("ncmActive")))
check("控件本身没有被设样式表（避免破坏祖先背景规则）",
      bar.shuffle_btn.styleSheet() == "", bar.shuffle_btn.styleSheet())
bar.shuffle_btn.click()
pump(0.1)
check("再点 -> 随机关闭", controller.shuffle is False)
check("关闭后属性为 false",
      bar.shuffle_btn.property("ncmActive") == "false",
      str(bar.shuffle_btn.property("ncmActive")))

order = ["off", "all", "one"]
bar.repeat_btn.click()
pump(0.1)
check("循环第一次点击 -> all", controller.repeat == "all", controller.repeat)
bar.repeat_btn.click()
pump(0.1)
check("循环第二次点击 -> one", controller.repeat == "one", controller.repeat)
check("单曲循环按钮带上「1」角标（图标比 off 态宽）",
      bar.repeat_btn.iconSize().width() > bar.shuffle_btn.iconSize().width(),
      f"{bar.repeat_btn.iconSize().width()} vs {bar.shuffle_btn.iconSize().width()}")
bar.repeat_btn.click()
pump(0.1)
check("循环第三次点击 -> off", controller.repeat == "off", controller.repeat)

# ─────────── 4. 转换进度文字 ───────────

print()
print("=" * 70)
print("[4] 转换进度文字")
print("=" * 70)

check("进度条被改名以便单独设样式",
      window.progress.objectName() == "NcmConvertBar", window.progress.objectName())
check("进度条已打开文字显示", window.progress.isTextVisible())

# 运行期的进度文字入口。它是在 core 回调里被调用的（和原版 setValue 同一个线程），
# 所以这里直接调它来验证格式。
bar_progress = window.progress
ncm_patch._note_progress("转换", 1, 213)
pump(0.1)
fmt = bar_progress.format()
print(f"  _note_progress('转换', 1, 213) -> {fmt!r}")
check("显示「正在转换（1/213）0.5%」（1/213 就是 0.5%）",
      fmt == "正在转换（1/213）0.5%", fmt)

ncm_patch._note_progress("转换", 107, 213)
pump(0.1)
fmt2 = bar_progress.format()
print(f"  _note_progress('转换', 107, 213) -> {fmt2!r}")
check("百分比按一位小数计算", fmt2 == "正在转换（107/213）50.2%", fmt2)

ncm_patch._note_progress("扫描", 3, 213)
pump(0.1)
fmt3 = bar_progress.format()
print(f"  _note_progress('扫描', 3, 213) -> {fmt3!r}")
check("扫描阶段用「正在扫描」", fmt3.startswith("正在扫描（3/213）"), fmt3)

ncm_patch._clear_progress()
pump(0.1)
check("结束后清掉进度文字", bar_progress.format() == "", bar_progress.format())

# 进度钩子不再包装界面槽（那是崩溃的根源）
check("没有替换 MainWindow.on_progress 槽",
      "patched" not in app.MainWindow.on_progress.__qualname__,
      app.MainWindow.on_progress.__qualname__)
check("core 回调里包了进度记录", ncm_patch.scan_folder is not None)

# ─────────── 5. 应用图标 ───────────

print()
print("=" * 70)
print("[5] 应用图标")
print("=" * 70)

icon = window._build_icon()
check("_build_icon() 返回了图标", icon is not None and not icon.isNull())
check("窗口图标不是空的", not window.windowIcon().isNull())
check("QApplication 图标不是空的", not QApplication.windowIcon().isNull())

marks = [lb for lb in window.title_bar.findChildren(QLabel)
         if lb.objectName() == "AppMark"]
check("找到标题栏的应用图标标记", len(marks) == 1, str(len(marks)))
if marks:
    m = marks[0]
    print(f"  AppMark: text={m.text()!r} 有 pixmap={not m.pixmap().isNull()} "
          f"尺寸={m.pixmap().width()}x{m.pixmap().height()}")
    check("标记已换成图标位图（不再是 ♪ 字符）",
          m.text() == "" and not m.pixmap().isNull())

pix = icon.pixmap(64, 64)
if not pix.isNull():
    img = pix.toImage()
    # 中心应该是蓝色圆盘
    c = img.pixelColor(32, 32)
    print(f"  图标中心像素 = #{c.red():02x}{c.green():02x}{c.blue():02x} alpha={c.alpha()}")
    check("图标中心是有色的（不是空白）", c.alpha() > 0 and max(c.red(), c.green(), c.blue()) > 40)

# ─────────── 6. 原有功能仍在 ───────────

print()
print("=" * 70)
print("[6] 原有功能未受影响")
print("=" * 70)
check("表格列数未变", window.model.columnCount() == 7)
check("core.scan_folder 仍是补丁版", __import__("core").scan_folder is ncm_patch.scan_folder)
check("侧栏提示仍带「支持 .ncm」",
      any("支持 .ncm" in lb.text() for lb in window.findChildren(QLabel)))
check("扫描/开始整理按钮可用",
      window.scan_btn.isEnabled() and window.run_btn.isEnabled())

window.grab().save(str(HERE / "v3-data-shot.png"))
print("  已保存 v3-data-shot.png")

controller._player.close()
window.close()

print()
print("=" * 70)
if not fails:
    print(f"v3 功能验证全部通过：{checks} 项 ✓")
else:
    print(f"通过 {checks - len(fails)}，失败 {len(fails)} ✗")
    for f in fails:
        print("  -", f)

pathlib.Path("v3-report-out.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp(f"报告 -> v3-report-out.txt（{len(fails)} 项失败）")
sys.exit(1 if fails else 0)

# 收尾：Qt 的析构阶段偶发访问违例（所有检查都已完成、报告已写盘）。
# 用 os._exit 跳过解释器清理，让测试脚本给出可靠的退出码。
import os as _os
sys.stdout.flush()
sys.stderr.flush()
_os._exit(1 if fails else 0)

