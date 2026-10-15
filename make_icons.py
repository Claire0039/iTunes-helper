#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_icons.py —— 从用户提供的图片生成全套应用图标

要解决两件事：
  1. 源图是完全不透明的，背景是烘焙进去的浅色格子 —— 必须先抠出圆盘、
     做圆形 alpha 遮罩，否则图标会带一块白底；
  2. PE 资源段里 7 个尺寸的字节数是固定预算（数据区只剩 115 字节余量），
     所以每个尺寸都要用「量化 + 最大压缩」塞进预算内。

产出（icon-build/）：
  pe-16.png … pe-256.png   给 PE 资源段用（已按各尺寸预算压好）
  app.png                  256x256 RGBA，给 Qt（_resource('app.png')）
  app.ico                  多尺寸 ICO，给 Qt（_resource('app.ico')）
  preview.png              合成预览，方便肉眼检查
"""
import builtins
import io
import math
import os
import pathlib
import struct
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

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor   # noqa: E402

_app = QGuiApplication.instance() or QGuiApplication([])

SRC = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "icon-source.png")
OUT = HERE / "icon-build"
OUT.mkdir(exist_ok=True)

# PE 资源段里各尺寸的原始字节数（必须不超过）
BUDGET = {16: 380, 24: 527, 32: 743, 48: 1087, 64: 1543, 128: 3386, 256: 8214}
# PE 用 64 色（≈4 级/通道）刚好全部落在预算内
PE_LEVELS = 4


def is_background(c):
    """浅色中性底（源图里 239/255 两种灰白都算背景）"""
    r, g, b = c.red(), c.green(), c.blue()
    return min(r, g, b) > 200 and (max(r, g, b) - min(r, g, b)) < 24


def encode(im, level=0):
    # Qt 的 PNG quality 是反的：0 = 最大压缩，100 = 几乎不压缩
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    im.save(buf, "PNG", level)
    buf.close()
    return bytes(ba)


# ── 1. 抠出圆盘 ──

src = QImage(str(SRC)).convertToFormat(QImage.Format.Format_ARGB32)
print(f"源图 {src.width()}x{src.height()}")

margin = 10          # 源图最外圈有一圈深色细边框，必须忽略掉
left, top, right, bottom = src.width(), src.height(), -1, -1
for y in range(margin, src.height() - margin):
    for x in range(margin, src.width() - margin):
        if not is_background(src.pixelColor(x, y)):
            if x < left:
                left = x
            if x > right:
                right = x
            if y < top:
                top = y
            if y > bottom:
                bottom = y
print(f"  非背景包围盒: ({left},{top}) - ({right},{bottom})  "
      f"{right - left + 1}x{bottom - top + 1}")

cx = (left + right) / 2.0
cy = (top + bottom) / 2.0
# 用较小的那一边定直径，避免把边缘杂色算进来导致偏心/越界
diameter = min(right - left + 1, bottom - top + 1)
radius = diameter / 2.0
print(f"  圆心 ({cx:.1f},{cy:.1f}) 直径 {diameter}")

# 把圆盘外的一切变透明，并加 1 像素抗锯齿
disc = QImage(src.width(), src.height(), QImage.Format.Format_ARGB32)
disc.fill(Qt.GlobalColor.transparent)
aa = 1.2
for y in range(max(0, top - 4), min(src.height(), bottom + 5)):
    for x in range(max(0, left - 4), min(src.width(), right + 5)):
        d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
        if d <= radius - aa:
            a = 255
        elif d >= radius + aa:
            continue
        else:
            a = int(round(255 * (radius + aa - d) / (2 * aa)))
        c = src.pixelColor(x, y)
        c.setAlpha(max(0, min(255, a)))
        disc.setPixelColor(x, y, c)

# 裁成正方形
side = int(round(radius * 2))
square = QImage(side, side, QImage.Format.Format_ARGB32)
square.fill(Qt.GlobalColor.transparent)
p = QPainter(square)
p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
p.drawImage(0, 0, disc, int(round(cx - radius)), int(round(cy - radius)), side, side)
p.end()
print(f"  抠出圆盘 -> {side}x{side}")


def scaled(size, smooth=True):
    return square.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation if smooth
                         else Qt.TransformationMode.FastTransformation)


# ── 2. PE 用的 7 个尺寸 ──

def quantize(im, levels):
    step = 255 // (levels - 1) if levels > 1 else 255
    out = QImage(im.width(), im.height(), QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    for y in range(im.height()):
        for x in range(im.width()):
            c = im.pixelColor(x, y)
            if c.alpha() < 128:
                continue
            out.setPixelColor(x, y, QColor(
                min(255, round(c.red() / step) * step),
                min(255, round(c.green() / step) * step),
                min(255, round(c.blue() / step) * step),
                255))
    return out


print()
print("PE 图标（PE 资源段预算 vs 实际）：")
pe_files = {}
total = 0
for size, budget in BUDGET.items():
    s = scaled(size)
    data = None
    # 从小到大试色数，取满足预算里画质最好的
    for levels in (PE_LEVELS, 3, 2):
        cand = encode(quantize(s, levels), 0)
        if data is None or len(cand) < len(data):
            data = cand
        if len(cand) <= budget:
            data = cand
            break
    path = OUT / f"pe-{size}.png"
    path.write_bytes(data)
    pe_files[size] = data
    total += len(data)
    flag = "OK " if len(data) <= budget else "超!"
    print(f"  {size:>3}x{size:<3} 预算 {budget:>5}  实际 {len(data):>5}  {flag}")
print(f"  合计 {total} / {sum(BUDGET.values())}")

# ── 3. Qt 用的 app.png（不量化，PNG 无损） ──

app_png = encode(scaled(256), 0)
(OUT / "app.png").write_bytes(app_png)
print(f"\napp.png (256x256 RGBA): {len(app_png)} 字节")

# ── 4. app.ico（多尺寸，PNG 压缩条目） ──

ico_sizes = [16, 24, 32, 48, 64, 128, 256]
entries = []
for size in ico_sizes:
    entries.append((size, encode(scaled(size), 0)))

ico = bytearray()
ico += struct.pack("<HHH", 0, 1, len(entries))
offset = 6 + 16 * len(entries)
for size, data in entries:
    ico += struct.pack("<BBBBHHII",
                       size if size < 256 else 0,
                       size if size < 256 else 0,
                       0, 0, 1, 32, len(data), offset)
    offset += len(data)
for _, data in entries:
    ico += data
(OUT / "app.ico").write_bytes(bytes(ico))
print(f"app.ico ({len(entries)} 个尺寸): {len(ico)} 字节")

# ── 5. 预览图 ──

prev = QImage(16 + 24 + 32 + 48 + 64 + 128 + 256 + 8 * 10, 280,
              QImage.Format.Format_ARGB32)
prev.fill(QColor(245, 245, 248))
p = QPainter(prev)
p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
x = 10
for size in ico_sizes:
    img = scaled(size)
    p.drawImage(x, 10, img)
    x += size + 10
p.end()
prev.save(str(OUT / "preview.png"))
print("preview.png 已生成")

pathlib.Path("icon-report.txt").write_text(_buf.getvalue(), encoding="utf-8")
_rp("报告 -> icon-report.txt")
