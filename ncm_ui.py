# -*- coding: utf-8 -*-
"""
ncm_ui.py —— 界面扩展：iTunes 风格播放器栏、音频详情面板、主题与进度增强

包含：
  PlayerBar        顶部播放器栏（左侧控制+音量 / 中部封面+信息+进度 / 右侧随机+循环）
  DetailPanel      列表下方的音频详情
  AudioController  把 MCI 后端接到 Qt 上

全部通过「在既有布局里插入控件」挂上去，不改动任何原有控件与逻辑。
"""

import os

from PySide6.QtCore import QObject, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QGuiApplication,
                           QIcon, QPainter, QPainterPath, QPixmap)
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QMenu, QPushButton, QSizePolicy,
                               QSlider, QVBoxLayout, QWidget)

import ncm_audio
import ncm_glyphs
import ncm_media


# ─────────────────────────── 小工具 ───────────────────────────

def _sep(parent, colors):
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFixedWidth(1)
    line.setStyleSheet(f"background:{colors['border']}; border:none;")
    return line


def rounded_pixmap(pixmap, size, radius):
    """把封面裁成圆角，模仿 iTunes 的专辑图样式。"""
    if pixmap is None or pixmap.isNull():
        return None
    scaled = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    x = max(0, (scaled.width() - size) // 2)
    y = max(0, (scaled.height() - size) // 2)
    scaled = scaled.copy(x, y, size, size)

    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return out


def _tint(pixmap, color):
    """把一张白色剪影按目标颜色染色（SourceIn 保留 alpha）。"""
    out = QPixmap(pixmap.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), QColor(color))
    painter.end()
    return out


def glyph_pixmap(name, height, color):
    """
    取内置的播放器图标剪影，缩放到指定高度并按主题色染色。

    素材是「白色图形 + alpha」的 PNG，所以浅色/深色主题共用同一份，
    只用改颜色就行 —— 不会在深色主题下变成看不见的黑图标。
    """
    data = ncm_glyphs.glyph_bytes(name)
    if not data:
        return None
    source = QPixmap()
    if not source.loadFromData(data) or source.isNull():
        return None
    scaled = source.scaledToHeight(max(1, int(height)),
                                   Qt.TransformationMode.SmoothTransformation)
    return _tint(scaled, color)


def pause_pixmap(height, color):
    """
    暂停图标。

    用户提供的是「播放/暂停」那一个播放三角形；暂停态用同样风格的两条圆角竖条
    现画一个，保证粗细和圆角和其余图标一致。
    """
    width = max(9, int(round(height * 0.84)))
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255))
    bar = max(3, int(round(width * 0.34)))
    gap = max(2, width - bar * 2)
    radius = bar / 2.0
    for index in range(2):
        x = index * (bar + gap)
        painter.drawRoundedRect(QRectF(x, 0, bar, height), radius, radius)
    painter.end()
    return _tint(pixmap, color)


def repeat_pixmap(mode, height, color):
    """
    循环图标。用户只给了一个图标，三种状态这样区分：
      off  -> 灰色
      all  -> 主题色
      one  -> 主题色 + 右侧一个小小的「1」
    """
    base = glyph_pixmap("repeat", height, color)
    if base is None or mode != "one":
        return base
    from PySide6.QtGui import QFont
    badge_w = max(6, int(round(height * 0.5)))
    out = QPixmap(base.width() + badge_w, height)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.drawPixmap(0, 0, base)
    font = QFont("Segoe UI")
    font.setPixelSize(max(7, int(round(height * 0.72))))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(QRectF(base.width() - 1, -1, badge_w + 2, height + 2),
                     Qt.AlignmentFlag.AlignCenter, "1")
    painter.end()
    return out


def cover_placeholder(size, colors, radius=6):
    """没有封面时画一个占位方块（圆角 + 音符）。"""
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, radius, radius)
    painter.setClipPath(path)
    painter.fillRect(0, 0, size, size, QColor(colors["input_bg"]))
    painter.setPen(QColor(colors["text_muted"]))
    from PySide6.QtGui import QFont
    font = QFont("Microsoft YaHei UI")
    font.setPointSize(max(6, int(size * 0.36)))
    painter.setFont(font)
    painter.drawText(out.rect(), Qt.AlignmentFlag.AlignCenter, "♪")
    painter.end()
    return out


# ─────────────────────────── 播放控制器 ───────────────────────────

class AudioController(QObject):
    """把 MCI 播放器接进 Qt 事件循环。"""

    positionChanged = Signal(int, int)     # 当前位置 ms, 总时长 ms
    stateChanged = Signal(str)             # playing / paused / stopped / ended / error
    trackChanged = Signal(dict)            # 当前曲目信息

    SHUFFLE_OFF = "off"
    REPEAT_OFF = "off"
    REPEAT_ALL = "all"
    REPEAT_ONE = "one"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = ncm_audio.MciPlayer()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)
        self._playlist = []                # [(path, info_dict), ...]
        self._index = -1
        self._volume = 0.8
        self._last_state = "stopped"
        self._ended_guard = False
        self.shuffle = False
        self.repeat = self.REPEAT_OFF
        self._random = None

    # ── 列表 ──

    def set_playlist(self, items):
        self._playlist = list(items)

    # ── 播放 ──

    def play_index(self, index):
        if not self._playlist:
            return False
        index = max(0, min(index, len(self._playlist) - 1))
        path, info = self._playlist[index]
        self._index = index

        if not self._player.open(path):
            self._timer.stop()
            self._last_state = "error"
            self.stateChanged.emit("error")
            self.trackChanged.emit(dict(info, error=self._player.last_error))
            return False

        self._player.set_volume(self._volume)
        self._player.play()
        self._ended_guard = False
        self._timer.start()
        self._last_state = "playing"
        self.stateChanged.emit("playing")
        self.trackChanged.emit(dict(info))
        self.positionChanged.emit(0, self._player.duration_ms())
        return True

    def play_path(self, path):
        for i, (p, _) in enumerate(self._playlist):
            if os.path.normcase(p) == os.path.normcase(os.fspath(path)):
                return self.play_index(i)
        self._playlist.append((os.fspath(path), {}))
        return self.play_index(len(self._playlist) - 1)

    def toggle(self):
        if not self._player.is_open:
            if self._playlist:
                return self.play_index(max(0, self._index))
            return False
        if self._player.mode() == "playing":
            self._player.pause()
            self._last_state = "paused"
            self.stateChanged.emit("paused")
        else:
            self._player.play()
            self._last_state = "playing"
            self.stateChanged.emit("playing")
            self._timer.start()
        return True

    def stop(self):
        self._player.stop()
        self._timer.stop()
        self._last_state = "stopped"
        self.stateChanged.emit("stopped")
        self.positionChanged.emit(0, self._player.duration_ms())

    def _shuffle_target(self):
        import random
        n = len(self._playlist)
        if n <= 1:
            return 0
        if self._random is None:
            self._random = random.Random()
        pick = self._index
        while pick == self._index:
            pick = self._random.randrange(n)
        return pick

    def next_track(self, auto=False):
        if not self._playlist:
            return False
        if self.shuffle:
            return self.play_index(self._shuffle_target())
        nxt = self._index + 1
        if nxt >= len(self._playlist):
            if self.repeat == self.REPEAT_ALL or not auto:
                nxt = 0
            else:
                return False
        return self.play_index(nxt)

    def prev_track(self):
        if not self._playlist:
            return False
        # 播过 3 秒以上先回到本曲开头，符合播放器习惯
        if self._player.is_open and self._player.position_ms() > 3000:
            self._player.seek_ms(0)
            self.positionChanged.emit(0, self._player.duration_ms())
            return True
        if self.shuffle:
            return self.play_index(self._shuffle_target())
        return self.play_index((self._index - 1) % len(self._playlist))

    def seek(self, ms):
        if self._player.is_open:
            self._player.seek_ms(ms)
            self.positionChanged.emit(self._player.position_ms(),
                                      self._player.duration_ms())

    def set_volume(self, value):
        self._volume = min(1.0, max(0.0, float(value)))
        self._player.set_volume(self._volume)

    def volume(self):
        return self._volume

    def current_index(self):
        return self._index

    def is_open(self):
        return self._player.is_open

    def mode(self):
        return self._player.mode()

    def position_ms(self):
        return self._player.position_ms()

    def duration_ms(self):
        return self._player.duration_ms()

    # ── 轮询 ──

    def _tick(self):
        if not self._player.is_open:
            self._timer.stop()
            return
        mode = self._player.mode()
        pos = self._player.position_ms()
        dur = self._player.duration_ms()
        self.positionChanged.emit(pos, dur)

        if mode == "stopped" and dur > 0 and pos >= dur - 1200 and not self._ended_guard:
            self._ended_guard = True
            self._timer.stop()
            self.stateChanged.emit("ended")
            QTimer.singleShot(120, self._auto_next)
            return
        if mode == "playing":
            self._last_state = "playing"

    def _auto_next(self):
        if self.repeat == self.REPEAT_ONE:
            self.play_index(self._index)
            return
        if not self.next_track(auto=True):
            self.stateChanged.emit("stopped")


# ─────────────────────────── 播放器栏 ───────────────────────────

class PlayerBar(QFrame):
    """
    iTunes 风格的顶部播放器栏。

    布局（按需求）：
      左：上一曲 / 播放暂停 / 下一曲 / 音量
      中：专辑封面 + 歌曲信息（上），进度条（下）
      右：随机播放 / 循环
    """

    COVER = 46

    def __init__(self, parent, colors):
        super().__init__(parent)
        self.setObjectName("PlayerBar")
        self.colors = colors
        self._duration = 0
        self._seeking = False
        self._controller = None

        self.setFixedHeight(88)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(14)

        # ── 左：传输控制 + 音量（图标用用户提供的素材） ──
        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        self.prev_btn = self._button("prev", "NcmBtn", 34, "上一曲", 15)
        self.play_btn = self._button("play", "NcmPlay", 38, "播放 / 暂停", 18)
        self.next_btn = self._button("next", "NcmBtn", 34, "下一曲", 15)
        left.addWidget(self.prev_btn)
        left.addWidget(self.play_btn)
        left.addWidget(self.next_btn)
        left.addSpacing(8)

        self.vol_icon = QLabel("♪")
        self.vol_icon.setObjectName("NcmVolIcon")
        self.vol_icon.setFixedWidth(16)
        self.vol_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.vol_icon)
        self.volume = QSlider(Qt.Orientation.Horizontal, self)
        self.volume.setObjectName("NcmVolume")
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedWidth(112)
        self.volume.setFixedHeight(24)
        self.volume.setCursor(Qt.CursorShape.PointingHandCursor)
        left.addWidget(self.volume)

        left_holder = QWidget(self)
        left_holder.setLayout(left)
        outer.addWidget(left_holder)

        outer.addWidget(_sep(self, colors))

        # ── 中：封面 + 信息 / 进度 ──
        centre = QVBoxLayout()
        centre.setContentsMargins(0, 0, 0, 0)
        centre.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        self.cover = QLabel(self)
        self.cover.setObjectName("NcmBarCover")
        self.cover.setFixedSize(self.COVER, self.COVER)
        self.cover.setPixmap(cover_placeholder(self.COVER, colors, 5))
        top.addWidget(self.cover)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(0)
        self.title_label = QLabel("未在播放")
        self.title_label.setObjectName("NcmNowTitle")
        self.artist_label = QLabel("双击列表中的音乐即可播放")
        self.artist_label.setObjectName("NcmNowArtist")
        info.addStretch(1)
        info.addWidget(self.title_label)
        info.addWidget(self.artist_label)
        info.addStretch(1)
        top.addLayout(info, 1)
        centre.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)
        self.pos_label = QLabel("0:00")
        self.pos_label.setObjectName("NcmTime")
        self.pos_label.setFixedWidth(40)
        self.pos_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.progress = QSlider(Qt.Orientation.Horizontal, self)
        self.progress.setObjectName("NcmProgress")
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setPageStep(10)
        self.progress.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.progress.sliderPressed.connect(self._on_seek_start)
        self.progress.sliderMoved.connect(self._on_seek_move)
        self.progress.sliderReleased.connect(self._on_seek_end)

        self.dur_label = QLabel("-0:00")
        self.dur_label.setObjectName("NcmTime")
        self.dur_label.setFixedWidth(40)

        bottom.addWidget(self.pos_label)
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.dur_label)
        centre.addLayout(bottom)

        centre_holder = QWidget(self)
        centre_holder.setLayout(centre)
        outer.addWidget(centre_holder, 1)

        outer.addWidget(_sep(self, colors))

        # ── 右：随机 / 循环 ──
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(4)
        self.shuffle_btn = self._button("shuffle", "NcmToggle", 30, "随机播放", 14)
        self.repeat_btn = self._button("repeat", "NcmToggle", 32, "循环播放：关", 14)
        right.addWidget(self.shuffle_btn)
        right.addWidget(self.repeat_btn)
        right_holder = QWidget(self)
        right_holder.setLayout(right)
        outer.addWidget(right_holder)

        self._apply_style(colors)

    # ── 构造辅助 ──

    def _button(self, glyph, name, size, tip, glyph_height=14):
        """建一个只用图标的按钮（图标来自用户提供的素材，按主题色染色）。"""
        btn = QPushButton(self)
        btn.setObjectName(name)
        btn.setFixedSize(QSize(size, size))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tip)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setProperty("ncmGlyph", glyph)
        btn.setProperty("ncmGlyphHeight", int(glyph_height))
        return btn

    def _paint_glyphs(self):
        """按当前主题色把所有图标重画一遍（主题切换 / 状态变化时调用）。"""
        c = self.colors
        text = c.get("text", "#e6e8ee")
        muted = c.get("text_muted", "#8a8f98")
        accent = c.get("accent", "#2f6feb")
        controller = self._controller

        self._put_icon(self.prev_btn, glyph_pixmap("prev", 15, text))
        self._put_icon(self.next_btn, glyph_pixmap("next", 15, text))
        self._paint_play_icon()

        self._put_icon(self.shuffle_btn, glyph_pixmap(
            "shuffle", 14,
            accent if (controller is not None and controller.shuffle) else muted))
        repeat = controller.repeat if controller is not None else "off"
        self._put_icon(self.repeat_btn, repeat_pixmap(
            repeat, 14, accent if repeat != "off" else muted))

    def _paint_play_icon(self):
        c = self.colors
        color = c.get("text", "#e6e8ee")
        playing = (self._controller is not None
                   and self._controller.mode() == "playing")
        pixmap = pause_pixmap(18, color) if playing else glyph_pixmap("play", 18, color)
        self._put_icon(self.play_btn, pixmap)

    @staticmethod
    def _put_icon(btn, pixmap):
        if btn is None or pixmap is None or pixmap.isNull():
            return
        btn.setText("")
        btn.setIcon(QIcon(pixmap))
        btn.setIconSize(pixmap.size())

    # ── 对外接口 ──

    def attach(self, controller):
        self._controller = controller
        self.prev_btn.clicked.connect(controller.prev_track)
        self.play_btn.clicked.connect(controller.toggle)
        self.next_btn.clicked.connect(lambda: controller.next_track(auto=False))
        self.volume.valueChanged.connect(lambda v: controller.set_volume(v / 100.0))
        self.shuffle_btn.clicked.connect(self._toggle_shuffle)
        self.repeat_btn.clicked.connect(self._cycle_repeat)
        controller.positionChanged.connect(self._on_position)
        controller.stateChanged.connect(self._on_state)
        controller.trackChanged.connect(self._on_track)
        self._paint_glyphs()

    def _toggle_shuffle(self):
        if self._controller is None:
            return
        self._controller.shuffle = not self._controller.shuffle
        self._sync_toggles()

    def _cycle_repeat(self):
        if self._controller is None:
            return
        order = [AudioController.REPEAT_OFF, AudioController.REPEAT_ALL,
                 AudioController.REPEAT_ONE]
        cur = self._controller.repeat
        self._controller.repeat = order[(order.index(cur) + 1) % len(order)]
        self._sync_toggles()

    def _sync_toggles(self):
        """
        高亮用「动态属性 + QSS 选择器」，不要对控件 setStyleSheet ——
        在子控件上设样式表会破坏祖先控件（QWidget#Root / #TitleBar）的背景规则，
        之前窗口背景变黑就是这么来的。
        """
        if self._controller is None:
            return
        repeat = self._controller.repeat
        pairs = (
            (self.shuffle_btn, bool(self._controller.shuffle)),
            (self.repeat_btn, repeat != AudioController.REPEAT_OFF),
        )
        for btn, active in pairs:
            try:
                btn.setProperty("ncmActive", "true" if active else "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()
            except Exception:
                pass
        self.repeat_btn.setToolTip(
            {"off": "循环播放：关", "all": "循环播放：列表循环", "one": "循环播放：单曲循环"}[repeat])
        try:
            self._paint_glyphs()
        except Exception:
            pass

    # ── 槽 ──

    def _on_seek_start(self):
        self._seeking = True

    def _on_seek_move(self, value):
        if self._duration > 0:
            self.pos_label.setText(ncm_media.human_duration(self._duration * value / 1000.0))

    def _on_seek_end(self):
        self._seeking = False
        if self._controller and self._duration > 0:
            self._controller.seek(int(self._duration * self.progress.value() / 1000))

    def _on_position(self, pos_ms, dur_ms):
        if dur_ms > 0:
            self._duration = dur_ms
            remaining = max(0, dur_ms - pos_ms)
            # iTunes 风格：右侧显示负数剩余时间
            self.dur_label.setText("-" + ncm_media.human_duration(remaining / 1000.0))
        if not self._seeking:
            self.pos_label.setText(ncm_media.human_duration(pos_ms / 1000.0))
            if self._duration > 0:
                self.progress.setValue(int(pos_ms * 1000 / self._duration))

    def _on_state(self, state):
        self._paint_play_icon()
        if state in ("stopped", "error"):
            self.progress.setValue(0)
            self.pos_label.setText("0:00")
            self.dur_label.setText("-0:00")

    def _on_track(self, info):
        title = info.get("title") or info.get("name") or "未知曲目"
        artist = info.get("artist") or ""
        album = info.get("album") or ""
        second = " — ".join(x for x in (artist, album) if x) or "未知艺术家"
        self.title_label.setText(self._elide(title, 40))
        self.title_label.setToolTip(title)
        self.artist_label.setText(self._elide(second, 60))
        self.artist_label.setToolTip(second)
        if info.get("error"):
            self.artist_label.setText("无法播放：" + str(info["error"])[:60])
        self._set_cover(info.get("cover_path") or info.get("path"))

    def _set_cover(self, path):
        data = None
        if path and os.path.isfile(path):
            data, _mime = ncm_media.read_cover(path)
        if not data:
            self.cover.setPixmap(cover_placeholder(self.COVER, self.colors, 5))
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            self.cover.setPixmap(rounded_pixmap(pix, self.COVER, 5)
                                 or cover_placeholder(self.COVER, self.colors, 5))
        else:
            self.cover.setPixmap(cover_placeholder(self.COVER, self.colors, 5))

    @staticmethod
    def _elide(text, limit):
        text = str(text)
        return text if len(text) <= limit else text[: limit - 1] + "…"

    # ── 样式 ──

    def _apply_style(self, c):
        self.colors = c
        try:
            self._paint_glyphs()
        except Exception:
            pass
        self.update()


# ─────────────────────────── 扩展样式表 ───────────────────────────

_QSS_MARK = "\n/* ================= NCM 扩展样式 ================= */\n"


def _is_dark(colors):
    """按底色亮度判断当前是深色还是浅色主题。"""
    try:
        return QColor(colors.get("bg", "#ffffff")).lightness() < 128
    except Exception:
        return False


def build_extra_qss(c):
    """播放器栏 + 详情面板 + 进度条 + 音量滑杆的样式规则。"""
    dark = _is_dark(c)
    # 音量滑杆按参考图的取色：未填充 #ababab / 已填充 #676767 / 白色圆滑块。
    # 深色主题下换成白色系，否则滑杆会糊在背景里。
    vol_off = "rgba(255,255,255,0.30)" if dark else "#ababab"
    vol_on = "rgba(255,255,255,0.80)" if dark else "#676767"
    vol_knob = "#ffffff"
    vol_ring = "rgba(255,255,255,0.55)" if dark else "rgba(0,0,0,0.22)"
    return f"""
/* ---- 播放器栏 ---- */
QFrame#PlayerBar {{
    background: {c['bg_alt']};
    border: none;
    border-bottom: 1px solid {c['border']};
}}
QLabel#NcmBarCover {{ background: transparent; border: none; }}
QPushButton#NcmBtn {{
    border: none; background: transparent; color: {c['text']};
    border-radius: 17px;
}}
QPushButton#NcmBtn:hover   {{ background: {c['hover']}; }}
QPushButton#NcmBtn:pressed {{ background: {c['pressed']}; }}
/* 播放键原本是主题色圆底；换成用户提供的深色图标后改成和其它键一致的透明底 */
QPushButton#NcmPlay {{
    border: none; background: transparent; color: {c['text']};
    border-radius: 19px;
}}
QPushButton#NcmPlay:hover   {{ background: {c['hover']}; }}
QPushButton#NcmPlay:pressed {{ background: {c['pressed']}; }}
QPushButton#NcmToggle {{
    border: none; background: transparent; color: {c['text_muted']};
    border-radius: 15px;
}}
QPushButton#NcmToggle:hover {{ background: {c['hover']}; }}
QPushButton#NcmToggle[ncmActive="true"] {{ color: {c['accent']}; }}
QLabel#NcmNowTitle  {{ color: {c['text']}; font-size: 13px; font-weight: 600; }}
QLabel#NcmNowArtist {{ color: {c['text_muted']}; font-size: 11px; }}
QLabel#NcmTime      {{ color: {c['text_muted']}; font-size: 11px; }}
QLabel#NcmVolIcon   {{ color: {c['text_muted']}; font-size: 13px; }}

QSlider#NcmProgress::groove:horizontal {{
    height: 4px; background: {c['border']}; border-radius: 2px;
}}
QSlider#NcmProgress::sub-page:horizontal {{
    background: {c['accent']}; border-radius: 2px;
}}
QSlider#NcmProgress::handle:horizontal {{
    width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
    background: {c['accent']};
}}
QSlider#NcmProgress::handle:horizontal:hover {{ background: {c['accent_hover']}; }}
/* ---- 音量滑杆：细灰轨道 + 大白色圆滑块（按参考图的比例：
        轨道 7px、滑块约为控件宽度的 16%）---- */
QSlider#NcmVolume {{ background: transparent; }}
QSlider#NcmVolume::groove:horizontal {{
    height: 7px; margin: 0 9px;
    background: {vol_off};
    border-radius: 3.5px;
}}
QSlider#NcmVolume::sub-page:horizontal {{
    height: 7px; margin: 0 9px;
    background: {vol_on};
    border-radius: 3.5px;
}}
QSlider#NcmVolume::add-page:horizontal {{
    height: 7px; margin: 0 9px;
    background: {vol_off};
    border-radius: 3.5px;
}}
QSlider#NcmVolume::handle:horizontal {{
    width: 18px; height: 18px;
    margin: -5.5px -9px;
    border-radius: 9px;
    background: {vol_knob};
    border: 1px solid {vol_ring};
}}
QSlider#NcmVolume::handle:horizontal:hover {{
    background: {vol_knob};
    border: 1px solid {c['accent']};
}}

/* ---- 详情面板 ---- */
QFrame#DetailPanel {{
    background: {c['card']};
    border: 1px solid {c['border']};
    border-radius: 10px;
}}
QLabel#NcmDetailTitle {{ color: {c['text']}; font-size: 15px; font-weight: 600; }}
QLabel#NcmDetailSub   {{ color: {c['text_muted']}; font-size: 12px; }}
QLabel#NcmDetailKey   {{ color: {c['text_muted']}; font-size: 11px; }}
QLabel#NcmDetailValue {{ color: {c['text']}; font-size: 11px; }}

/* ---- 转换进度：加高的进度条，文字直接写在条上 ---- */
QProgressBar#NcmConvertBar {{
    background: {c['input_bg']};
    border: 1px solid {c['border']};
    border-radius: 9px;
    height: 18px; min-height: 18px; max-height: 18px;
    text-align: center;
    color: {c['text']};
    font-size: 11px;
}}
QProgressBar#NcmConvertBar::chunk {{
    background: {c['accent']};
    border-radius: 8px;
}}

/* ---- 标题栏左侧的应用图标标记（原来是蓝色方块 + ♪ 字符）---- */
QLabel#AppMark {{ background: transparent; border: none; border-radius: 0; padding: 0; }}
"""


def apply_extra_qss(colors):
    """
    把扩展规则追加到 QApplication 的应用级样式表末尾。
    程序本身就是用 QApplication.setStyleSheet 做主题的，跟着它走最稳妥：
    不会干扰祖先控件的 QWidget#Root / #TitleBar 背景规则。
    """
    app = QApplication.instance()
    if app is None:
        return
    base = app.styleSheet() or ""
    if _QSS_MARK in base:
        base = base.split(_QSS_MARK)[0]
    app.setStyleSheet(base + _QSS_MARK + build_extra_qss(colors))


# ─────────────────────────── 详情面板 ───────────────────────────

_FIELDS = (
    ("文件位置", "path"),
    ("大小", "size"),
    ("时长", "duration"),
    ("格式", "format"),
    ("比特率", "bitrate"),
    ("采样率", "sample_rate"),
    ("归档到", "target"),
    ("状态", "status"),
)


class DetailPanel(QFrame):
    """列表下方的音频详情。"""

    COVER = 132

    def __init__(self, parent, colors):
        super().__init__(parent)
        self.setObjectName("DetailPanel")
        self.colors = colors
        self._has_real_cover = False
        self.setFixedHeight(180)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(18)

        self.cover = QLabel(self)
        self.cover.setFixedSize(self.COVER, self.COVER)
        self.cover.setPixmap(cover_placeholder(self.COVER, colors, 10))
        lay.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(2)

        self.title_label = QLabel("未选择音乐")
        self.title_label.setObjectName("NcmDetailTitle")
        self.sub_label = QLabel("在上方列表中单击一首音乐即可查看详情")
        self.sub_label.setObjectName("NcmDetailSub")
        right.addWidget(self.title_label)
        right.addWidget(self.sub_label)
        right.addSpacing(8)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(4, 1)
        self._values = {}
        self._keys = {}
        for index, (label, key) in enumerate(_FIELDS):
            col = 0 if index % 2 == 0 else 3
            row = index // 2
            k = QLabel(label)
            k.setObjectName("NcmDetailKey")
            k.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            k.setFixedWidth(58)
            v = QLabel("—")
            v.setObjectName("NcmDetailValue")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setWordWrap(False)
            grid.addWidget(k, row, col)
            grid.addWidget(v, row, col + 1)
            self._values[key] = v
            self._keys[key] = k
        right.addLayout(grid)
        right.addStretch(1)

        lay.addLayout(right, 1)
        self._apply_style(colors)

    # ── 展示 ──

    def clear(self):
        self.title_label.setText("未选择音乐")
        self.sub_label.setText("在上方列表中单击一首音乐即可查看详情")
        self._has_real_cover = False
        self.cover.setPixmap(cover_placeholder(self.COVER, self.colors, 10))
        for v in self._values.values():
            v.setText("—")

    def show_job(self, job):
        """优先展示归档后的文件（如果已经存在），否则展示源文件。"""
        if job is None:
            self.clear()
            return
        track = getattr(job, "track", None)
        src = getattr(track, "path", None) if track else None
        target = getattr(job, "target", None)

        path = None
        if target is not None and os.path.isfile(target):
            path = os.fspath(target)
        elif src is not None and os.path.isfile(src):
            path = os.fspath(src)
        elif target is not None:
            path = os.fspath(target)
        elif src is not None:
            path = os.fspath(src)
        if not path:
            self.clear()
            return

        info = ncm_media.read_details(path)

        title = (getattr(track, "title", "") if track else "") or info["title"] \
            or os.path.splitext(os.path.basename(path))[0]
        artist = (getattr(track, "artist", "") if track else "") or info["artist"] or "未知艺术家"
        album = (getattr(track, "album", "") if track else "") or info["album"] or ""
        duration = (getattr(track, "duration", 0.0) if track else 0.0) or info["duration"]

        self.title_label.setText(title)
        self.title_label.setToolTip(title)
        self.sub_label.setText(" · ".join(x for x in (artist, album) if x) or "未知艺术家")
        self.sub_label.setToolTip(artist)
        self._set_cover(path)

        self._values["path"].setText(path)
        self._values["path"].setToolTip(path)
        self._values["size"].setText(ncm_media.human_size(info["size"]))
        self._values["duration"].setText(ncm_media.human_duration(duration))
        self._values["format"].setText(info["format"])
        self._values["bitrate"].setText(
            f"{info['bitrate'] // 1000} kbps" if info["bitrate"] else "—")
        self._values["sample_rate"].setText(
            f"{info['sample_rate']} Hz" if info["sample_rate"] else "—")
        self._values["target"].setText(
            os.fspath(target) if target is not None else "（未归档）")
        self._values["target"].setToolTip(
            os.fspath(target) if target is not None else "")
        self._values["status"].setText(getattr(job, "status", "") or "—")
        if info.get("error"):
            self._values["status"].setText(f"{getattr(job, 'status', '')}  ({info['error']})")

    def _set_cover(self, path):
        data, mime = ncm_media.read_cover(path)
        if not data:
            self._has_real_cover = False
            self.cover.setPixmap(cover_placeholder(self.COVER, self.colors, 10))
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            rounded = rounded_pixmap(pix, self.COVER, 10)
            self.cover.setPixmap(rounded or cover_placeholder(self.COVER, self.colors, 10))
            self._has_real_cover = rounded is not None
        else:
            self._has_real_cover = False
            self.cover.setPixmap(cover_placeholder(self.COVER, self.colors, 10))

    def _apply_style(self, c):
        self.colors = c
        if not self._has_real_cover:
            self.cover.setPixmap(cover_placeholder(self.COVER, c, 10))
        self.update()


# ─────────────────────────── 主题模式 ───────────────────────────

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_AUTO = "auto"

_THEME_GLYPH = {THEME_LIGHT: "☀", THEME_DARK: "☾", THEME_AUTO: "◐"}
_THEME_LABEL = {THEME_LIGHT: "浅色", THEME_DARK: "深色", THEME_AUTO: "跟随系统"}


def _system_scheme():
    """判断系统当前是深色还是浅色。优先用 Qt 6.5+ 的 colorScheme。"""
    try:
        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return THEME_DARK
        if scheme == Qt.ColorScheme.Light:
            return THEME_LIGHT
    except Exception:
        pass
    # 退化方案：读注册表
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        try:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return THEME_LIGHT if value else THEME_DARK
        finally:
            winreg.CloseKey(key)
    except Exception:
        return THEME_LIGHT


def resolve_theme(mode):
    return _system_scheme() if mode == THEME_AUTO else mode


def _theme_button(window):
    bar = getattr(window, "title_bar", None)
    if bar is None:
        return None
    for btn in bar.findChildren(QPushButton):
        if btn.objectName() == "WinBtn" and btn.text() in ("☾", "☀", "◐", "◑"):
            return btn
    return None


def _sync_theme_button(window):
    btn = _theme_button(window)
    if btn is None:
        return
    mode = getattr(window, "_ncm_theme_mode", THEME_LIGHT)
    btn.setText(_THEME_GLYPH.get(mode, "☾"))
    btn.setToolTip(f"外观：{_THEME_LABEL.get(mode, mode)}（点击切换）")


def set_theme_mode(window, mode):
    if mode not in (THEME_LIGHT, THEME_DARK, THEME_AUTO):
        mode = THEME_LIGHT
    try:
        window.settings_store.setValue("theme", mode)
    except Exception:
        pass
    window.apply_theme(mode)          # 由包装后的 apply_theme 负责解析 auto


def _show_theme_menu(window, anchor):
    menu = QMenu(anchor)
    group = QActionGroup(menu)
    group.setExclusive(True)
    current = getattr(window, "_ncm_theme_mode", THEME_LIGHT)
    for mode in (THEME_LIGHT, THEME_DARK, THEME_AUTO):
        text = _THEME_LABEL[mode]
        if mode == THEME_AUTO:
            text += f"（当前：{_THEME_LABEL[_system_scheme()]}）"
        act = QAction(text, menu)
        act.setCheckable(True)
        act.setChecked(mode == current)
        act.triggered.connect(lambda _checked=False, m=mode: set_theme_mode(window, m))
        group.addAction(act)
        menu.addAction(act)
    menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))


# ─────────────────────────── 图标 ───────────────────────────

def apply_icon(window):
    """
    把标题栏左侧的 ♪ 标记换成真正的应用图标。

    窗口/任务栏图标由 app 自己的 MainWindow._build_icon() 提供，它读的是
    _resource('app.png')；构建脚本已经把归档里的 assets/app.png 和 app.ico
    换成了新图标，所以那部分不用在这里管。
    """
    try:
        import app
        icon = window._build_icon()
    except Exception:
        icon = None
    if icon is None or icon.isNull():
        return
    try:
        QApplication.setWindowIcon(icon)
        window.setWindowIcon(icon)
    except Exception:
        pass

    bar = getattr(window, "title_bar", None)
    if bar is None:
        return
    for label in bar.findChildren(QLabel):
        if label.objectName() == "AppMark":
            pix = icon.pixmap(24, 24)
            if not pix.isNull():
                label.setText("")
                label.setPixmap(pix)
                label.setFixedSize(24, 24)
            break


# ─────────────────────────── 注入 ───────────────────────────

def _find_layout_with(root, target):
    """找到直接包含 target 控件的那个布局。"""
    from PySide6.QtWidgets import QLayout
    for lay in root.findChildren(QLayout):
        try:
            for i in range(lay.count()):
                it = lay.itemAt(i)
                if it is not None and it.widget() is target:
                    return lay
        except Exception:
            continue
    return None


def _index_of(lay, widget):
    for i in range(lay.count()):
        it = lay.itemAt(i)
        if it is not None and it.widget() is widget:
            return i
    return -1


def install_ui(window):
    """在既有界面上插入播放器栏与详情面板，并接好交互。幂等。"""
    if getattr(window, "_ncm_ui_installed", False):
        return None
    window._ncm_ui_installed = True

    colors = dict(getattr(window, "colors", {}) or {})
    if not colors:
        return None

    result = {"bar": None, "panel": None, "controller": None}

    # ── 1. 顶部播放器栏 ──
    bar = None
    try:
        bar = PlayerBar(window, colors)
        top = window.layout()
        if top is not None:
            top.insertWidget(1, bar)
            result["bar"] = bar
    except Exception:
        bar = None

    # ── 2. 列表下方的详情面板 ──
    panel = None
    try:
        ws = _find_layout_with(window, window.table)
        if ws is not None:
            panel = DetailPanel(window, colors)
            ws.insertWidget(_index_of(ws, window.table) + 1, panel)
            result["panel"] = panel
    except Exception:
        panel = None

    # ── 3. 播放控制器 ──
    controller = AudioController(window)
    result["controller"] = controller
    if bar is not None:
        try:
            bar.attach(controller)
        except Exception:
            pass

    # ── 4. 交互接线 ──

    def current_jobs():
        try:
            return list(window.model._jobs)
        except Exception:
            return []

    def build_playlist():
        items = []
        for job in current_jobs():
            track = getattr(job, "track", None)
            if track is None:
                continue
            target = getattr(job, "target", None)
            path = None
            if target is not None and os.path.isfile(target):
                path = os.fspath(target)
            elif os.path.isfile(os.fspath(track.path)):
                path = os.fspath(track.path)
            if not path:
                continue
            items.append((path, {
                "title": getattr(track, "title", "") or "",
                "artist": getattr(track, "artist", "") or "",
                "album": getattr(track, "album", "") or "",
                "name": os.path.basename(path),
                "path": path,
            }))
        return items

    def row_of_index(index):
        try:
            return index.row()
        except Exception:
            return -1

    def on_clicked(index):
        if panel is None:
            return
        row = row_of_index(index)
        jobs = current_jobs()
        if 0 <= row < len(jobs):
            try:
                panel.show_job(jobs[row])
            except Exception:
                pass

    def on_double_clicked(index):
        row = row_of_index(index)
        if row < 0:
            return
        controller.set_playlist(build_playlist())
        if controller.play_index(row) and bar is not None:
            bar._sync_toggles()
            try:
                window.append_log(
                    "info",
                    f"正在播放：{os.path.basename(controller._playlist[row][0])}")
            except Exception:
                pass

    try:
        window.table.clicked.connect(on_clicked)
        window.table.doubleClicked.connect(on_double_clicked)
        window.table.selectionModel().currentRowChanged.connect(
            lambda cur, _prev: on_clicked(cur))
    except Exception:
        pass

    # 列表清空时同步清掉详情与播放列表
    try:
        original_set_jobs = window.model.set_jobs

        def patched_set_jobs(jobs, *a, **kw):
            r = original_set_jobs(jobs, *a, **kw)
            try:
                if panel is not None:
                    panel.clear()
                controller.set_playlist([])
            except Exception:
                pass
            return r

        window.model.set_jobs = patched_set_jobs
    except Exception:
        pass

    # ── 5. 主题：支持「跟随系统」 ──
    try:
        original_apply = window.apply_theme

        def patched_apply(name, *a, **kw):
            mode = name if name in (THEME_LIGHT, THEME_DARK, THEME_AUTO) else THEME_LIGHT
            # 把 auto 解析成具体的 light/dark 再交给原实现（它只认这两个）
            r = original_apply(resolve_theme(mode), *a, **kw)
            window._ncm_theme_mode = mode
            try:
                colors_now = dict(getattr(window, "colors", {}) or {})
                apply_extra_qss(colors_now)
                if bar is not None:
                    bar._apply_style(colors_now)
                if panel is not None:
                    panel._apply_style(colors_now)
                _sync_theme_button(window)
            except Exception:
                pass
            return r

        window.apply_theme = patched_apply
    except Exception:
        pass

    # 系统主题变化时，若处于「跟随系统」就跟着切
    try:
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda _s: (window.apply_theme(THEME_AUTO)
                        if getattr(window, "_ncm_theme_mode", "") == THEME_AUTO else None))
    except Exception:
        pass

    # 把标题栏那个 ☾ 按钮改成「弹出外观菜单」
    try:
        btn = _theme_button(window)
        if btn is not None:
            try:
                btn.clicked.disconnect()
            except Exception:
                pass
            btn.clicked.connect(lambda: _show_theme_menu(window, btn))
    except Exception:
        pass

    # ── 6. 进度条：加高 + 文字可见（文字内容由 ncm_patch 的进度钩子写入）──
    #
    # 注意：这里只在安装时（主线程）打开文字可见性并改一次格式，
    # 运行期由 on_progress 在它自己的线程里只改字符串 —— 不新增跨线程控件访问。
    try:
        if window.progress is not None:
            window.progress.setObjectName("NcmConvertBar")
            window.progress.setTextVisible(True)
            window.progress.setFormat("")
    except Exception:
        pass

    # ── 7. 应用图标 ──
    try:
        apply_icon(window)
    except Exception:
        pass

    # ── 8. 让程序自己的主题规则真正生效 ──
    #
    # 程序 QSS 里写着 `QWidget#Root { background: <主题底色>; }`，
    # 但窗口的 objectName 是空的 —— 没有任何控件叫 Root，这条规则从来没生效过。
    # 标题栏同理：它是自定义控件，不显式打开 WA_StyledBackground 就不会绘制
    # 样式表背景。结果就是「窗口底色和标题栏跟随 Windows 的深/浅色模式」，
    # 其余控件却由 QSS 固定成浅色，系统一进深色模式界面就花掉。
    try:
        if not window.objectName():
            window.setObjectName("Root")
        window.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tb = getattr(window, "title_bar", None)
        if tb is not None:
            tb.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    except Exception:
        pass

    # 立即把扩展样式挂上去并同步一次主题
    try:
        apply_extra_qss(colors)
    except Exception:
        pass
    try:
        mode = window.settings_store.value("theme", THEME_DARK)
        if mode not in (THEME_LIGHT, THEME_DARK, THEME_AUTO):
            mode = THEME_DARK
        window._ncm_theme_mode = mode
        window.apply_theme(mode)
    except Exception:
        window._ncm_theme_mode = THEME_LIGHT
        _sync_theme_button(window)

    return result
