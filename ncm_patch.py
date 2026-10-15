# -*- coding: utf-8 -*-
"""
ncm_patch.py —— 把 NCM 支持接进 iTunes 助手的核心流程

接入点选在 core.scan_folder。理由：
  * app.Worker.do_scan / do_run 都是用 `core.scan_folder(...)` 这种属性访问调用的，
    替换模块属性即可生效，不需要改动已冻结的 app 模块；
  * 扫描之后的所有环节（命名模板、按专辑分组、批内去重、复制/移动、m3u8 播放列表）
    都只认「一个真实音频文件 + 一份标签」，所以只要在扫描阶段把 .ncm 变成
    「带着完整标签的真实 MP3/FLAC」，后面的流程一行都不用改。

工作方式：
  1. 扫完原有音频后，再找一遍 .ncm 文件；
  2. 逐个解密到系统临时目录下的缓存区（不是源目录，避免被再次扫到）；
  3. 用 NCM 容器里的元数据和封面通过 mutagen 写进解密文件；
  4. 用解出来的真实文件构造 core.Track，混进原有列表。

源 .ncm 文件永远只读，不会被删除或修改。
"""

import atexit
import os
import shutil
import tempfile
import threading
from pathlib import Path

import core
import ncm_audio
import ncm_core
import ncm_tags
import ncm_ui

_INSTALLED = False

_cache_path = None
_cache_lock = threading.Lock()

_orig_scan_folder = None
_orig_execute_jobs = None

# 当前活动窗口（只有一个），用于把转换进度写到底部进度条上
_active_window = None


def _note_progress(phase, done, total):
    """在 worker 线程里顺手更新进度文字 —— 和原版 setValue 同一个线程，不引入并发。"""
    window = _active_window
    if window is None:
        return
    bar = getattr(window, "progress", None)
    if bar is None:
        return
    try:
        total = int(total or 0)
        done = int(done or 0)
        if total <= 0:
            return
        pct = max(0.0, min(100.0, done * 100.0 / total))
        text = f"正在{phase}（{done}/{total}）{pct:.1f}%"
        if bar.format() != text:
            bar.setFormat(text)
            bar.setTextVisible(True)
    except Exception:
        pass


def _clear_progress():
    window = _active_window
    if window is None:
        return
    bar = getattr(window, "progress", None)
    if bar is None:
        return
    try:
        if bar.format():
            bar.setFormat("")
    except Exception:
        pass


def _existing_tracks():
    """取当前列表里已有的曲目（拖入文件时要追加，而不是把列表清空重建）。"""
    window = _active_window
    if window is None:
        return []
    try:
        jobs = list(window.model._jobs)
    except Exception:
        return []
    tracks = []
    for job in jobs:
        track = getattr(job, "track", None)
        if track is not None:
            tracks.append(track)
    return tracks


def _track_key(track):
    try:
        return os.path.normcase(os.path.abspath(os.fspath(track.path)))
    except Exception:
        return None


def _merge_tracks(existing, incoming, on_log=None):
    """
    把新扫描到的曲目并到已有列表后面，按绝对路径去重。

    去重是为了「同一个文件重复拖两次」不会在列表里出现两行；
    保留先出现的那个（也就是原来那一行，它的归档状态不会丢）。
    """
    merged = []
    seen = set()
    for track in list(existing) + list(incoming):
        key = _track_key(track)
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        merged.append(track)
    if on_log is not None and existing:
        added = len(merged) - len(existing)
        try:
            on_log("info",
                   f"列表中原有的 {len(existing)} 首已保留，本次追加 {max(0, added)} 首"
                   f"（重复的已自动跳过）。")
        except Exception:
            pass
    return merged


# 拖入文件时设置的「只处理这些文件」覆盖列表；None 表示按目录正常扫描
_scan_override = None
_override_lock = threading.Lock()

# 缓存目录的候选顺序：
#   1. 环境变量 ITUNES_ASSISTANT_NCM_CACHE 指定的目录（显式覆盖）
#   2. 系统临时目录（正常情况下的正确选择）
#   3. 用户主目录下的隐藏缓存（TEMP 不可写时兜底，例如受限的企业机器）
# 每个候选都会先做一次写探针，写不进去就换下一个。
_CACHE_ENV = "ITUNES_ASSISTANT_NCM_CACHE"


# ───────────────────────── 缓存目录 ─────────────────────────

def _probe_writable(path):
    """真正写一个文件再删掉——只有这样才能确认目录可用。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".ncm_write_probe"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _try_make_cache(base):
    try:
        if base is None:
            candidate = Path(tempfile.mkdtemp(prefix="itunes_assistant_ncm_"))
        else:
            candidate = Path(base) / f"itunes_assistant_ncm_{os.getpid()}"
            if not _probe_writable(candidate):
                return None
    except OSError:
        return None
    return candidate if _probe_writable(candidate) else None


def _cache_dir(anchor=None):
    global _cache_path
    with _cache_lock:
        if _cache_path is not None:
            return _cache_path

        candidates = []
        override = os.environ.get(_CACHE_ENV)
        if override:
            candidates.append(Path(override))
        candidates.append(None)                                  # 系统临时目录
        candidates.append(Path.home() / ".itunes_assistant_ncm")  # 兜底

        for base in candidates:
            path = _try_make_cache(base)
            if path is not None:
                _cache_path = path
                atexit.register(_purge_cache)
                return path

        raise RuntimeError(
            "找不到可写的临时目录来解密 NCM；"
            f"可以用环境变量 {_CACHE_ENV} 指定一个目录"
        )


def _purge_cache():
    global _cache_path
    with _cache_lock:
        path, _cache_path = _cache_path, None
    if path is not None:
        shutil.rmtree(path, ignore_errors=True)


def _unique_in_cache(cache, stem, ext):
    """避免同名（例如同名 .ncm 与 .mp3）在缓存里互相覆盖。"""
    safe = core.sanitize_filename(stem, "ncm")
    candidate = cache / f"{safe}.{ext}"
    counter = 2
    while candidate.exists():
        candidate = cache / f"{safe} ({counter}).{ext}"
        counter += 1
    return candidate


# ───────────────────────── NCM -> Track ─────────────────────────

def _find_ncm(root, recursive):
    try:
        if not root.is_dir():
            return []
        walker = root.rglob("*") if recursive else root.glob("*")
        return sorted(p for p in walker if p.is_file() and p.suffix.lower() == ".ncm")
    except OSError:
        return []


def _convert(src, cache):
    """解密一个 .ncm，写出带标签的真实音频文件，返回 core.Track。"""
    audio, ext, meta, cover, cover_mime = ncm_core.read_ncm(src)

    # 容器里没写标题时用文件名兜底，免得归档出来一堆「未命名」
    if not meta.get("title"):
        meta["title"] = src.stem

    dst = _unique_in_cache(cache, src.stem, ext)
    dst.write_bytes(audio)

    # 把元数据和封面写进音频，这样归档出去的 MP3/FLAC 自带完整信息
    ncm_tags.write_tags(str(dst), ext, meta, cover, cover_mime)

    # 时长以解密后的真实音频为准（NCM 元数据里的可能不准）
    real = core.read_metadata(dst) or {}
    duration = real.get("duration") or meta.get("duration") or 0.0

    stat = dst.stat()
    return core.Track(
        path=dst,
        artist=meta.get("artist") or real.get("artist") or "",
        title=meta.get("title") or real.get("title") or "",
        album=meta.get("album") or real.get("album") or "",
        track_no=meta.get("track_no") or real.get("track_no") or 0,
        duration=duration,
        size=stat.st_size,
        mtime=stat.st_mtime,
        tags_ok=True,
    )


# ───────────────────────── 扫描覆盖（拖入文件） ─────────────────────────

def set_scan_override(paths):
    """只处理给定的这些文件（用于「把文件拖进来」）。"""
    global _scan_override
    with _override_lock:
        _scan_override = [Path(p) for p in paths]


def clear_scan_override():
    global _scan_override
    with _override_lock:
        _scan_override = None


def has_scan_override():
    with _override_lock:
        return bool(_scan_override)


def _track_from_file(path, on_log):
    """按 core.scan_folder 原本的方式构造一个 Track。"""
    try:
        stat = path.stat()
    except OSError as exc:
        on_log("warn", f"无法读取 {path}：{exc}")
        return None
    meta = core.read_metadata(path) or {}
    title = meta.get("title") or ""
    artist = meta.get("artist") or ""
    return core.Track(
        path=path,
        artist=artist,
        title=title,
        album=meta.get("album") or "",
        track_no=meta.get("track_no") or 0,
        duration=meta.get("duration") or 0.0,
        size=stat.st_size,
        mtime=stat.st_mtime,
        tags_ok=bool(title or artist),
    )


def _scan_explicit(paths, on_log, on_progress):
    """只扫描明确给出的文件列表。"""
    ncm_paths = [p for p in paths if p.suffix.lower() == ".ncm"]
    others = [p for p in paths if p.suffix.lower() != ".ncm"]
    total = len(paths)
    tracks = []
    ignored = 0

    for index, p in enumerate(others, start=1):
        try:
            on_progress(index, total, p.name)
        except Exception:
            pass
        track = _track_from_file(p, on_log)
        if track is not None:
            tracks.append(track)
        else:
            ignored += 1

    if ncm_paths:
        on_log("info", f"发现 {len(ncm_paths)} 个网易云 NCM 文件，正在解密…")
        try:
            cache = _cache_dir(anchor=paths[0].parent)
        except RuntimeError as exc:
            on_log("error", str(exc))
            ignored += len(ncm_paths)
            cache = None
        if cache is not None:
            converted = 0
            for index, p in enumerate(ncm_paths, start=len(others) + 1):
                try:
                    on_progress(index, total, p.name)
                except Exception:
                    pass
                try:
                    tracks.append(_convert(p, cache))
                    converted += 1
                except Exception as exc:
                    on_log("error", f"NCM 解密失败 {p.name}：{exc}")
                    ignored += 1
            if converted:
                on_log("info",
                       f"已解密 {converted} 个 NCM 文件（音频未重新编码，标签与封面已写入）。")

    on_log("info", f"已载入 {len(tracks)} 个文件（来自拖入的 {total} 个），只处理这些文件。")
    return tracks, ignored


# ───────────────────────── 包装 scan_folder ─────────────────────────

def scan_folder(root, recursive=True, on_log=None, on_progress=None):
    on_log = on_log or core._noop_log
    raw_progress = on_progress or core._noop_progress
    # 进度回调是 Worker 传进来的（实际就是 self.progress.emit）。
    # 在这里包一层是安全的：Qt 信号到界面槽的连接没有被改动，
    # 我们只是在同一个线程里「先 emit，再顺手更新一下进度文字」。
    #
    # 反过来千万不要去包 MainWindow.on_progress 那个槽本身 ——
    # PySide6 从 worker 线程调用一个「非原始绑定方法」的槽会直接访问违例崩溃，
    # 连只做一次纯转发都会崩（这个坑排查了很久）。
    def on_progress(done, total, current=None):
        try:
            raw_progress(done, total, current)
        except Exception:
            pass
        _note_progress("扫描", done, total)

    with _override_lock:
        override = list(_scan_override) if _scan_override else None

    if override:
        # 拖入文件是「追加」语义：把新扫到的并到列表已有曲目后面，绝不清空原列表。
        tracks, ignored = _scan_explicit(override, on_log, on_progress)
        existing = _existing_tracks()
        if existing:
            tracks = _merge_tracks(existing, tracks, on_log)
        return tracks, ignored

    root = Path(root)

    ncm_files = _find_ncm(root, recursive)

    # 原有音频先按原样扫一遍
    tracks, ignored = _orig_scan_folder(root, recursive, on_log, on_progress)

    if not ncm_files:
        return tracks, ignored

    total = len(ncm_files)
    on_log("info", f"发现 {total} 个网易云 NCM 文件，正在解密…")

    try:
        cache = _cache_dir(anchor=root)
    except RuntimeError as exc:
        on_log("error", str(exc))
        return tracks, ignored - len(ncm_files)

    converted = 0
    for index, src in enumerate(ncm_files, start=1):
        try:
            on_progress(index, total, src.name)
        except Exception:
            pass
        try:
            tracks.append(_convert(src, cache))
            converted += 1
        except Exception as exc:
            on_log("error", f"NCM 解密失败 {src.name}：{exc}")

    # NCM 本来被算进「忽略的非音频文件」，现在它们被处理了，要把计数减回去
    ignored = max(0, ignored - converted)

    if converted:
        on_log("info", f"已解密 {converted} 个 NCM 文件（音频未重新编码，标签与封面已写入）。")
    return tracks, ignored


# ───────────────────────── 包装 execute_jobs ─────────────────────────

def execute_jobs(*args, **kwargs):
    # 同理：只包传送进来的 on_progress 回调，不动界面槽本身
    raw_progress = kwargs.get("on_progress")
    if raw_progress is not None:
        def on_progress(done, total, current=None):
            try:
                raw_progress(done, total, current)
            except Exception:
                pass
            _note_progress("转换", done, total)
        kwargs["on_progress"] = on_progress

    try:
        return _orig_execute_jobs(*args, **kwargs)
    finally:
        # 搬运完就把解密缓存清掉，避免整张专辑的副本一直占着临时目录
        _purge_cache()
        _clear_progress()


# ───────────────────────── 安装 ─────────────────────────

def install_core_patch():
    """替换 core 里的两个入口。幂等，重复调用无副作用。"""
    global _INSTALLED, _orig_scan_folder, _orig_execute_jobs
    if _INSTALLED:
        return
    _orig_scan_folder = core.scan_folder
    _orig_execute_jobs = core.execute_jobs
    core.scan_folder = scan_folder
    core.execute_jobs = execute_jobs
    _INSTALLED = True


def install_ui_patch():
    """
    界面层的改动：
      * 复用/升级 v1 的拖放处理：把音频或 .ncm 文件拖进来，直接载入列表；
      * 顶部 iTunes 风格播放器栏 + 列表下方详情面板（见 ncm_ui）；
      * 侧栏提示与启动日志。
    全部包在 try 里——界面改动失败也不该影响核心功能。
    """
    try:
        import app
    except Exception:
        return

    try:
        original_init = app.MainWindow.__init__

        def patched_init(self, *a, **kw):
            original_init(self, *a, **kw)
            _decorate_window(self)

        app.MainWindow.__init__ = patched_init
    except Exception:
        pass

    # ── 拖放：文件直接进列表 ──
    try:
        original_drop = app.MainWindow.dropEvent
        original_move = getattr(app.MainWindow, "dragMoveEvent", None)
        droppable = set(core.AUDIO_EXTS) | {".ncm"}

        def inspect_drop(mime):
            """
            解析拖进来的内容。

            返回 (可用的音频文件, 被忽略的数量, 文件夹列表)。
            可用的音频文件只在「全是文件、没有文件夹」时才给出，
            因为拖文件夹要走原来的整目录扫描逻辑。
            """
            try:
                urls = [u for u in mime.urls() if u.toLocalFile()]
            except Exception:
                return [], 0, []
            paths = [Path(u.toLocalFile()) for u in urls]
            files = [p for p in paths if p.is_file()]
            folders = [p for p in paths if p.is_dir()]
            if not files or folders:
                return [], 0, folders
            usable = [p for p in files if p.suffix.lower() in droppable]
            return usable, len(files) - len(usable), []

        def drag_ok(self, event):
            """这个拖放里有没有我们能处理的东西（音频文件或文件夹）。"""
            usable, _skipped, folders = inspect_drop(event.mimeData())
            return bool(usable or folders)

        def patched_drag_move(self, event):
            """
            拖动过程中 Qt 会不断派发 dragMoveEvent，**这里也必须 accept**。

            只覆盖 dragEnterEvent 是不够的：QWidget::dragMoveEvent 的默认实现
            不接受事件，Qt 于是把光标显示成禁止符号，松手时压根不会派发
            dropEvent —— 用户看到的现象就是「拖进去完全没反应」。
            程序自己的 dragEnterEvent 已经会接受，所以这里只要跟上即可。
            """
            if drag_ok(self, event):
                event.acceptProposedAction()
                return
            if original_move is not None:
                return original_move(self, event)
            event.ignore()

        def patched_drop(self, event):
            usable, skipped, _folders = inspect_drop(event.mimeData())
            if usable:
                try:
                    parents = []
                    for p in usable:
                        if p.parent not in parents:
                            parents.append(p.parent)
                    self.source_edit.setText(str(parents[0]))
                    if not self.output_edit.text().strip():
                        self.output_edit.setText(str(parents[0].parent))
                    set_scan_override(usable)
                    msg = f"已载入 {len(usable)} 个文件（拖入），只处理这些文件"
                    if skipped:
                        msg += f"，另有 {skipped} 个不支持的格式已忽略"
                    self.append_log("info", msg)
                    event.acceptProposedAction()
                    try:
                        self.start_scan()
                    except Exception:
                        pass
                    return
                except Exception:
                    pass
            return original_drop(self, event)

        # 程序自己的 dragEnterEvent 已经会接受，这里只补上缺失的 dragMoveEvent
        app.MainWindow.dropEvent = patched_drop
        app.MainWindow.dragMoveEvent = patched_drag_move
    except Exception:
        pass

    # ── 手动改源目录时取消「只处理拖入文件」的状态 ──
    try:
        original_pick = app.MainWindow.pick_source

        def patched_pick(self, *a, **kw):
            r = original_pick(self, *a, **kw)
            try:
                clear_scan_override()
            except Exception:
                pass
            return r

        app.MainWindow.pick_source = patched_pick
    except Exception:
        pass

    # ── 修掉原版「扫描后界面永久忙碌」的 bug ──
    _install_scan_watchdog(app)

    # 说明：转换进度文字**不**在这里挂钩 MainWindow.on_progress。
    # 那个槽是 Qt 直连的，从 worker 线程调用任何包装版本都会崩；
    # 改成在 scan_folder / execute_jobs 的回调里记录，见 _note_progress()。


def _scan_progress_reset(window):
    try:
        window._ncm_phase = "扫描"
        window._ncm_progress_done = 0
        window._ncm_progress_total = 0
        _clear_progress()
    except Exception:
        pass


def _install_scan_watchdog(app):
    """
    修掉原版的一个 bug：扫描之后界面永远停在忙碌态。

    app.Worker 是 QObject，自带一个 finished 信号；但 do_scan 只 emit preview，
    从不 emit finished（只有 do_run 会）。于是 on_finished / _teardown_worker
    永远不会被调用，_running 一直是 True —— 点过一次「扫描预览」以后，
    「扫描预览」和「开始整理」两个按钮就再也点不动了。

    补法：do_scan 结束时置个标志位（跨线程读安全），主线程的 QTimer 看门狗
    发现后调用 _teardown_worker() 收尾。全程在主线程，QThread.wait() 才能正常 join。
    """
    try:
        original_do_scan = app.Worker.do_scan
        original_start_scan = app.MainWindow.start_scan

        def patched_do_scan(self, *a, **kw):
            try:
                return original_do_scan(self, *a, **kw)
            finally:
                self._ncm_scan_done = True

        def patched_start_scan(self, *a, **kw):
            _scan_progress_reset(self)
            if os.environ.get("ITUNES_ASSISTANT_DEBUG") == "1":
                print("[dbg] start_scan 进入", flush=True)
            try:
                r = original_start_scan(self, *a, **kw)
            except BaseException:
                if os.environ.get("ITUNES_ASSISTANT_DEBUG") == "1":
                    import traceback
                    traceback.print_exc()
                raise
            if os.environ.get("ITUNES_ASSISTANT_DEBUG") == "1":
                print(f"[dbg] start_scan 返回 worker={getattr(self, '_worker', None)} "
                      f"thread={getattr(self, '_thread', None)} "
                      f"running={getattr(self, '_running', None)}", flush=True)
            worker = getattr(self, "_worker", None)
            if worker is not None:
                worker._ncm_scan_done = False
                _start_scan_watch(self)
            return r

        app.Worker.do_scan = patched_do_scan
        app.MainWindow.start_scan = patched_start_scan
    except Exception:
        pass


def _start_scan_watch(window):
    """
    启动主线程看门狗。

    注意要把 QTimer 挂成窗口的子对象并保存在窗口上：
    QTimer.singleShot(ms, lambda: ...) 里的 lambda 可能被 Python GC 掉，
    定时器就永远不会触发（这个坑踩过）。
    """
    from PySide6.QtCore import QTimer

    timer = getattr(window, "_ncm_scan_timer", None)
    if timer is None:
        timer = QTimer(window)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: _watch_scan(window, timer))
        window._ncm_scan_timer = timer
    window._ncm_scan_ticks = 0
    timer.start(150)


def _watch_scan(window, timer):
    """
    worker 线程跑完 do_scan 之后，替它把界面恢复成可用状态。

    全程在主线程，因此 _teardown_worker 里的 QThread.wait() 能正常 join，
    不会出现「线程等待自己」。
    """
    window._ncm_scan_ticks = getattr(window, "_ncm_scan_ticks", 0) + 1
    if window._ncm_scan_ticks > 800:          # 约两分钟上限
        return
    worker = getattr(window, "_worker", None)
    if worker is None or getattr(worker, "_ncm_scan_done", False):
        try:
            window._teardown_worker()
        except Exception:
            pass
        try:
            window._set_busy(False)
        except Exception:
            pass
        try:
            window._ncm_phase = ""
            window._ncm_progress_done = 0
            window._ncm_progress_total = 0
            _clear_progress()
        except Exception:
            pass
        return
    timer.start(150)


def _decorate_window(window):
    # 记下活动窗口，供 _note_progress / _clear_progress 写转换进度文字
    global _active_window
    _active_window = window

    # 侧栏提示
    try:
        from PySide6.QtWidgets import QLabel
        for label in window.findChildren(QLabel):
            text = label.text()
            if "源文件夹" in text and "ncm" not in text.lower():
                label.setText(f"{text}，支持 .ncm")
                break
    except Exception:
        pass

    # 未播放时的占位文案（播放器栏由 ncm_ui 建好）
    try:
        ncm_ui.install_ui(window)
    except Exception:
        pass

    # 源目录被手动编辑时，取消「只处理拖入文件」
    try:
        window.source_edit.textEdited.connect(lambda _t: clear_scan_override())
    except Exception:
        pass

    try:
        window.append_log(
            "info",
            "NCM 支持已启用：源文件夹里的网易云 .ncm 文件会在整理时自动解密为 MP3/FLAC，"
            "标签与封面一并写入；也可以直接把音频 / .ncm 文件拖进窗口。",
        )
    except Exception:
        pass


def install():
    install_core_patch()
    install_ui_patch()
