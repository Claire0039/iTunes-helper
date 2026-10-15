#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_player_icons.py —— 把用户提供的播放器图标处理成可染色的剪影

源图是不透明背景的深灰图形（还带截图残留的整行黑边），处理步骤：
  1. 按亮度生成遮罩（深色=图形），去掉整行/整列都"实心"的边缘黑边；
  2. 裁到内容包围盒；
  3. 输出「白色图形 + alpha」的紧凑 PNG —— 运行期用 SourceIn 染成主题色，
     这样浅色/深色主题都能用同一份素材。

产出 ncm_glyphs.py（base64 常量），供 ncm_ui 使用。
"""
import base64
import builtins
import io
import os
import pathlib
import sys

_buf = io.StringIO()
_rp = builtins.print


def print(*a, **k):          # noqa: A001
    k["file"] = _buf
    return _rp(*a, **k)


HERE = pathlib.Path(__file__).resolve().parent
sys.path.append(str(HERE / "runtime"))
for d in (HERE / "runtime", HERE / "runtime" / "PySide6"):
    if d.is_dir():
        try:
            os.add_dll_directory(str(d))
        except OSError:
            pass

from PySide6.QtCore import QBuffer, QByteArray, QIODevice      # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QColor      # noqa: E402

_app = QGuiApplication.instance() or QGuiApplication([])

SRC_DIR = HERE / "icon-src"
OUT_DIR = HERE / "player-icons"
OUT_DIR.mkdir(exist_ok=True)

NAMES = ("prev", "play", "next", "shuffle", "repeat")
INK = 170          # 亮度低于它的算图形（用于找包围盒）
SOLID = 0.90       # 整行实心比例超过它 -> 视为截图残留边框
# alpha 映射：亮度 <= OPAQUE 完全不透明，>= CLEAR 完全透明，中间线性过渡
# 源图背景亮度在 225~241 之间，必须整段判为透明，否则会残留一层浅灰方块
OPAQUE = 140
CLEAR = 205


def encode(im, level=0):
    # Qt 的 PNG quality 是反的：0 = 最大压缩
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    im.save(buf, "PNG", level)
    buf.close()
    return bytes(ba)


def process(path):
    src = QImage(str(path)).convertToFormat(QImage.Format.Format_ARGB32)

    # 1. 亮度遮罩
    ink = [[False] * src.width() for _ in range(src.height())]
    for y in range(src.height()):
        for x in range(src.width()):
            c = src.pixelColor(x, y)
            lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
            ink[y][x] = lum < INK

    def row_solid(y):
        return sum(ink[y]) / max(1, src.width())

    def col_solid(x):
        return sum(ink[y][x] for y in range(src.height())) / max(1, src.height())

    top, bottom = 0, src.height() - 1
    while top < bottom and row_solid(top) > SOLID:
        top += 1
    while bottom > top and row_solid(bottom) > SOLID:
        bottom -= 1
    left, right = 0, src.width() - 1
    while left < right and col_solid(left) > SOLID:
        left += 1
    while right > left and col_solid(right) > SOLID:
        right -= 1

    # 2. 在裁掉的范围内再收紧到真实内容
    while top < bottom and not any(ink[top][left:right + 1]):
        top += 1
    while bottom > top and not any(ink[bottom][left:right + 1]):
        bottom -= 1

    def col_has_ink(x):
        return any(ink[y][x] for y in range(top, bottom + 1))

    while left < right and not col_has_ink(left):
        left += 1
    while right > left and not col_has_ink(right):
        right -= 1

    w, h = right - left + 1, bottom - top + 1

    # 3. 画成白色剪影 + alpha（alpha 由暗度决定，保留抗锯齿边缘）
    out = QImage(w, h, QImage.Format.Format_ARGB32)
    out.fill(QColor(0, 0, 0, 0))
    for y in range(h):
        for x in range(w):
            c = src.pixelColor(left + x, top + y)
            lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
            if lum <= OPAQUE:
                a = 255
            elif lum >= CLEAR:
                a = 0
            else:
                a = int(round(255 * (CLEAR - lum) / (CLEAR - OPAQUE)))
            if a > 0:
                out.setPixelColor(x, y, QColor(255, 255, 255, a))
    return out


print("处理播放器图标:")
results = {}
for name in NAMES:
    p = SRC_DIR / f"{name}.png"
    if not p.exists():
        print(f"  ! 缺少 {p.name}")
        continue
    im = process(p)
    data = encode(im, 0)
    (OUT_DIR / f"{name}.png").write_bytes(data)
    results[name] = data
    print(f"  {name:<8} -> {im.width():>3}x{im.height():<3}  {len(data):>5} 字节  "
          f"宽高比 {im.width()/im.height():.2f}")

# 顺手合成几个尺寸的预览（放在一起比对）
if results:
    pad = 10
    total_w = sum(QImage(str(OUT_DIR / f"{n}.png")).width() + pad * 2 for n in results)
    max_h = max(QImage(str(OUT_DIR / f"{n}.png")).height() for n in results)
    prev = QImage(total_w + pad, max_h + pad * 2, QImage.Format.Format_ARGB32)
    prev.fill(QColor(240, 240, 244))
    x = pad
    for n in results:
        im = QImage(str(OUT_DIR / f"{n}.png"))
        for yy in range(im.height()):
            for xx in range(im.width()):
                c = im.pixelColor(xx, yy)
                if c.alpha() > 0:
                    # 预览时染成深色，才看得出来
                    prev.setPixelColor(x + xx, pad + yy, QColor(60, 60, 60, c.alpha()))
        x += im.width() + pad * 2
    prev.save(str(OUT_DIR / "preview.png"))
    print("  预览 -> player-icons/preview.png")

# 4. 生成 ncm_glyphs.py
lines = [
    "# -*- coding: utf-8 -*-",
    '"""',
    "ncm_glyphs.py —— 播放器控件图标（自动生成，勿手改）",
    "",
    "由 make_player_icons.py 从 icon-src/*.png 生成。",
    "每个图标都是「白色图形 + alpha」的 PNG，运行期按主题色染色，",
    "所以浅色 / 深色主题共用同一份素材。",
    '"""',
    "",
    "import base64",
    "",
    "GLYPHS = {",
]
for name in NAMES:
    if name not in results:
        continue
    b64 = base64.b64encode(results[name]).decode("ascii")
    chunks = [b64[i:i + 96] for i in range(0, len(b64), 96)]
    lines.append(f'    "{name}": (')
    for ch in chunks:
        lines.append(f'        "{ch}"')
    lines.append("    ),")
lines += [
    "}",
    "",
    "",
    "def glyph_bytes(name):",
    '    """返回图标的 PNG 原始字节；没有这个图标时返回 None。"""',
    "    data = GLYPHS.get(name)",
    "    if not data:",
    "        return None",
    "    if isinstance(data, (tuple, list)):",
    '        data = "".join(data)',
    "    try:",
    "        return base64.b64decode(data)",
    "    except Exception:",
    "        return None",
    "",
]
(HERE / "ncm_glyphs.py").write_text("\n".join(lines), encoding="utf-8")
print(f"\n已生成 ncm_glyphs.py（{len(results)} 个图标，"
      f"{(HERE / 'ncm_glyphs.py').stat().st_size} 字节）")

pathlib.Path("player-icon-report.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp("报告 -> player-icon-report.txt")
