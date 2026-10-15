# -*- coding: utf-8 -*-
"""
ncm_audio.py —— 基于 Windows MCI 的音频播放后端（零依赖）

为什么用 MCI 而不是 QtMultimedia：
    这个程序打包时只带了 QtCore / QtGui / QtNetwork / QtSvg / QtWidgets，
    没有 QtMultimedia，也没有对应的 DLL，无法补装。
    MCI（winmm.dll）是 Windows 自带的媒体控制接口，通过 ctypes 直接调用即可，
    底层走 DirectShow / Media Foundation，因此 MP3 / WMA / WAV 开箱即用，
    Windows 10 及以上还带 AAC(M4A) 与 FLAC 解码器。

MCI 是「全局别名 + 字符串命令」式的老 API，这里把它包成一个干净的类。
注意：MCI 不是线程安全的，所有调用都必须在同一个线程（Qt 主线程）里做。
"""

import ctypes
import hashlib
import os
import shutil
import tempfile
import threading
from ctypes import wintypes

_winmm = ctypes.WinDLL("winmm", use_last_error=True)

_mciSendStringW = _winmm.mciSendStringW
_mciSendStringW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, wintypes.HWND]
_mciSendStringW.restype = wintypes.DWORD

_mciGetErrorStringW = _winmm.mciGetErrorStringW
_mciGetErrorStringW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.UINT]
_mciGetErrorStringW.restype = wintypes.BOOL

# MCI 能打开的扩展名（按 Windows 自带解码器判断）
SUPPORTED_EXTS = {".mp3", ".wav", ".wma", ".m4a", ".aac", ".mp4", ".flac", ".aif", ".aiff"}

# 打开时尝试的设备类型顺序：先让 MCI 按扩展名自动判断，再逐个显式指定
_OPEN_TYPES = (None, "mpegvideo", "waveaudio", "MPEGVideo")

_alias_lock = threading.Lock()
_alias_counter = [0]


def _next_alias():
    with _alias_lock:
        _alias_counter[0] += 1
        return f"ncmplay{_alias_counter[0]}"


def _err_text(code):
    buf = ctypes.create_unicode_buffer(512)
    if _mciGetErrorStringW(code, buf, 512):
        return buf.value
    return f"MCI 错误 {code}"


def _send(command, want_reply=False):
    """发送一条 MCI 命令，返回 (成功?, 返回值或错误文本)"""
    buf = ctypes.create_unicode_buffer(1024) if want_reply else None
    code = _mciSendStringW(command, buf, 1024 if buf else 0, None)
    if code != 0:
        return False, _err_text(code)
    if want_reply and buf is not None:
        return True, buf.value.strip()
    return True, ""


class MciPlayer:
    """
    单实例播放器。所有方法都应在同一个线程调用（Qt 主线程）。

    典型用法：
        p = MciPlayer()
        p.open(path)
        p.play()
        p.position_ms()      # 轮询进度
        p.set_volume(0.6)
        p.close()
    """

    def __init__(self):
        self._alias = None
        self._path = None          # 用户看到的原始路径
        self._play_path = None     # 实际交给 MCI 的文件（可能是去标签副本）
        self._duration_ms = 0
        self.last_error = ""
        self._volume = 0.8
        self.used_stripped_copy = False

    # ── 状态 ──

    @property
    def is_open(self):
        return self._alias is not None

    @property
    def path(self):
        return self._path

    # ── 打开 / 关闭 ──

    def _try_open(self, path):
        alias = _next_alias()
        quoted = f'"{path}"'
        last = ""
        for dev_type in _OPEN_TYPES:
            cmd = f"open {quoted} alias {alias}"
            if dev_type:
                cmd += f" type {dev_type}"
            ok, info = _send(cmd)
            if ok:
                self._alias = alias
                _send(f"set {alias} time format milliseconds")
                ok_len, value = _send(f"status {alias} length", want_reply=True)
                try:
                    self._duration_ms = int(value) if ok_len else 0
                except ValueError:
                    self._duration_ms = 0
                self.set_volume(self._volume)
                return True, ""
            last = info
            _send(f"close {alias}")
        return False, last

    def open(self, path):
        """
        打开一个音频文件。成功返回 True。

        先直接打开；失败且文件是带 ID3v2 标签的 MP3 时，改用去标签的临时副本
        （见文件末尾关于「大 ID3 标签」的说明）。原文件始终不被修改。
        """
        path = os.fspath(path)
        if not os.path.isfile(path):
            self.last_error = f"文件不存在：{path}"
            return False

        self.close()
        self._path = path
        self.used_stripped_copy = False

        ok, err = self._try_open(path)
        if ok:
            self._play_path = path
            self.last_error = ""
            return True

        stripped = strip_id3_to_temp(path)
        if stripped != path:
            ok2, err2 = self._try_open(stripped)
            if ok2:
                self._play_path = stripped
                self.used_stripped_copy = True
                self.last_error = ""
                return True
            err = err2 or err

        self._play_path = None
        self.last_error = f"无法打开音频：{err}"
        return False

    def close(self):
        if self._alias:
            _send(f"stop {self._alias}")
            _send(f"close {self._alias}")
            self._alias = None
        self._path = None
        self._play_path = None
        self._duration_ms = 0

    # ── 传输控制 ──

    def play(self):
        if not self._alias:
            return False
        mode = self.mode()
        cmd = f"resume {self._alias}" if mode == "paused" else f"play {self._alias}"
        ok, info = _send(cmd)
        if not ok:
            self.last_error = info
        return ok

    def pause(self):
        if not self._alias:
            return False
        ok, info = _send(f"pause {self._alias}")
        if not ok:
            self.last_error = info
        return ok

    def stop(self):
        if not self._alias:
            return False
        _send(f"stop {self._alias}")
        _send(f"seek {self._alias} to 0")
        return True

    def seek_ms(self, ms):
        if not self._alias:
            return False
        ms = max(0, int(ms))
        ok, info = _send(f"seek {self._alias} to {ms}")
        if not ok:
            self.last_error = info
        return ok

    # ── 查询 ──

    def mode(self):
        """返回 'playing' / 'paused' / 'stopped' / ''"""
        if not self._alias:
            return ""
        ok, value = _send(f"status {self._alias} mode", want_reply=True)
        return value.lower() if ok else ""

    def is_playing(self):
        return self.mode() == "playing"

    def position_ms(self):
        if not self._alias:
            return 0
        ok, value = _send(f"status {self._alias} position", want_reply=True)
        if not ok:
            return 0
        try:
            return max(0, int(value))
        except ValueError:
            return 0

    def duration_ms(self):
        if not self._alias:
            return self._duration_ms
        ok, value = _send(f"status {self._alias} length", want_reply=True)
        if ok:
            try:
                self._duration_ms = int(value)
            except ValueError:
                pass
        return self._duration_ms

    # ── 音量 ──

    def set_volume(self, value):
        """
        value: 0.0 ~ 1.0

        注意：MCI 的 waveaudio 设备不支持 setaudio volume，会返回失败。
        这里刻意不把它当成错误——音量值仍然记住，切到支持它的格式（mp3 等）时生效。
        """
        self._volume = min(1.0, max(0.0, float(value)))
        if not self._alias:
            return False
        # MCI 的 setaudio 音量范围是 0~1000
        return _send(f"setaudio {self._alias} volume to {int(self._volume * 1000)}")[0]

    def get_volume(self):
        return self._volume


def can_play(path):
    """根据扩展名粗略判断 MCI 是否有机会播放（真正能否播放仍以 open 为准）"""
    return os.path.splitext(os.fspath(path))[1].lower() in SUPPORTED_EXTS


# ───────────────────────── 大 ID3 标签的绕行方案 ─────────────────────────
#
# 实测发现：MCI 的 MP3 解析器打不开带「大 ID3v2 标签」的文件。
# 典型场景是网易云下载的歌内嵌了 1~2 MB 的专辑封面 ——
# 同一首歌去掉 ID3 标签后立刻可以播放，带标签则报「初始化 MCI 时发生问题」。
#
# 绕行办法：打开失败时，把 MPEG 音频帧单独抽出来写成一个临时文件再播放。
# **绝不修改原文件**；副本按 (路径, 大小, mtime) 缓存，反复播放不会重复复制。

_strip_dir = None
# 必须是可重入锁：strip_id3_to_temp 会在持锁状态下再调用 _get_strip_dir()，
# 用普通 Lock 会自锁死（这个坑踩过一次，记在这里）。
_strip_lock = threading.RLock()

# 缓存上限，超过就整体清掉（播放副本通常一个几 MB）
_STRIP_CACHE_MAX = 24

_PLAY_CACHE_ENV = "ITUNES_ASSISTANT_PLAY_CACHE"


def _probe_writable(path):
    """
    真正建目录 + 写一个文件再删掉。只有这样才能确认目录可用。

    注意：这里刻意用**默认 mode** 调 mkdir。
    Python 3.13+ 在 Windows 上会把 os.mkdir 的 mode 参数翻译成 ACL，
    而 tempfile.mkdtemp() 用的是 mode=0o700（仅所有者），
    在受限令牌下会生成一个连创建者都写不进去的目录 —— 实测踩过。
    """
    try:
        os.makedirs(path, exist_ok=True)          # 不要传 mode！
        probe = os.path.join(path, ".ncm_write_probe")
        with open(probe, "wb") as fh:
            fh.write(b"ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _get_strip_dir():
    global _strip_dir
    with _strip_lock:
        if _strip_dir is not None and os.path.isdir(_strip_dir):
            return _strip_dir

        pid = os.getpid()
        candidates = []
        override = os.environ.get(_PLAY_CACHE_ENV)
        if override:
            candidates.append(os.path.join(override, f"play_{pid}"))
        candidates.append(os.path.join(tempfile.gettempdir(), f"itunes_assistant_play_{pid}"))
        candidates.append(os.path.join(os.path.expanduser("~"), ".itunes_assistant_play"))

        for cand in candidates:
            if _probe_writable(cand):
                _strip_dir = cand
                return _strip_dir
        raise OSError("找不到可写的临时目录用于播放缓存")


def _get_strip_dir_or_none():
    try:
        return _get_strip_dir()
    except OSError:
        return None


def cleanup_play_cache():
    """删除所有播放临时副本（退出时调用）"""
    global _strip_dir
    with _strip_lock:
        path, _strip_dir = _strip_dir, None
    if path:
        shutil.rmtree(path, ignore_errors=True)


def _id3v2_size(raw):
    """返回 ID3v2 标签的总字节数；没有标签返回 0。"""
    if len(raw) < 10 or raw[:3] != b"ID3":
        return 0
    size = ((raw[6] & 0x7F) << 21) | ((raw[7] & 0x7F) << 14) | \
           ((raw[8] & 0x7F) << 7) | (raw[9] & 0x7F)
    total = 10 + size
    if raw[5] & 0x10:          # footer 标志
        total += 10
    return total


def strip_id3_to_temp(path):
    """
    把 MP3 的音频帧抽出来写成临时文件，返回副本路径；不需要处理则返回原路径。
    """
    path = os.fspath(path)
    try:
        with open(path, "rb") as fh:
            head = fh.read(10)
            if len(head) < 10 or head[:3] != b"ID3":
                return path
            tag_bytes = _id3v2_size(head)
            if tag_bytes <= 0:
                return path
            st = os.stat(path)
            key = hashlib.sha1(
                f"{path}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8", "replace")
            ).hexdigest()[:20]
            cache = _get_strip_dir_or_none()
            if cache is None:
                return path
            dest = os.path.join(cache, key + ".mp3")
            if os.path.isfile(dest) and os.path.getsize(dest) == st.st_size - tag_bytes:
                return dest
            # 清一下过大的缓存
            with _strip_lock:
                try:
                    files = [os.path.join(cache, f) for f in os.listdir(cache)]
                except OSError:
                    files = []
                if len(files) > _STRIP_CACHE_MAX:
                    for f in files:
                        try:
                            os.remove(f)
                        except OSError:
                            pass
            fh.seek(tag_bytes)
            with open(dest, "wb") as out:
                shutil.copyfileobj(fh, out, 1024 * 512)
            return dest
    except OSError:
        return path

