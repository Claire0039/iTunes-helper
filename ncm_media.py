# -*- coding: utf-8 -*-
"""
ncm_media.py —— 读取音频文件的详细信息与专辑封面（供详情面板 / 播放器使用）

复用程序里已经打包的 mutagen。所有函数都是「尽力而为」：
任何一个字段读不到就留空，绝不抛异常打断界面。
"""

import base64
import os

# 扩展名 -> 展示用的格式名
_FORMAT_NAMES = {
    ".mp3": "MP3", ".flac": "FLAC", ".m4a": "M4A (AAC)", ".m4b": "M4B",
    ".aac": "AAC", ".wav": "WAV", ".aif": "AIFF", ".aiff": "AIFF",
    ".ogg": "OGG Vorbis", ".oga": "OGG Vorbis", ".opus": "Opus",
    ".wma": "WMA", ".alac": "ALAC", ".ncm": "NCM（网易云加密容器）",
}

# 封面数据超过这个尺寸就不往界面里塞了（避免内存和绘制开销）
MAX_COVER_BYTES = 12 * 1024 * 1024


def format_name(path):
    return _FORMAT_NAMES.get(os.path.splitext(os.fspath(path))[1].lower(),
                             os.path.splitext(os.fspath(path))[1].lstrip(".").upper() or "未知")


def _first(value):
    if isinstance(value, (list, tuple)):
        return str(value[0]).strip() if value else ""
    return str(value).strip() if value is not None else ""


def read_cover(path):
    """
    返回 (图片字节, MIME) —— 读不到返回 (None, None)。
    """
    ext = os.path.splitext(os.fspath(path))[1].lower()
    try:
        if ext in (".mp3", ".wav", ".aif", ".aiff"):
            from mutagen.id3 import ID3
            try:
                tags = ID3(path)
            except Exception:
                return None, None
            pics = tags.getall("APIC")
            if pics:
                data = pics[0].data
                if data and len(data) <= MAX_COVER_BYTES:
                    return bytes(data), pics[0].mime or "image/jpeg"
            return None, None

        if ext == ".flac":
            from mutagen.flac import FLAC
            f = FLAC(path)
            if f.pictures:
                pic = f.pictures[0]
                if pic.data and len(pic.data) <= MAX_COVER_BYTES:
                    return bytes(pic.data), pic.mime or "image/jpeg"
            return None, None

        if ext in (".m4a", ".m4b", ".mp4", ".alac"):
            from mutagen.mp4 import MP4, MP4Cover
            f = MP4(path)
            covr = f.tags.get("covr") if f.tags else None
            if covr:
                item = covr[0]
                mime = "image/png" if item.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
                data = bytes(item)
                if len(data) <= MAX_COVER_BYTES:
                    return data, mime
            return None, None

        if ext in (".ogg", ".oga", ".opus"):
            # Vorbis 注释里的 METADATA_BLOCK_PICTURE 是 base64 的 FLAC Picture 结构
            import mutagen
            from mutagen.flac import Picture
            f = mutagen.File(path)
            if f and f.tags:
                raw = f.tags.get("metadata_block_picture")
                if raw:
                    pic = Picture(base64.b64decode(_first(raw)))
                    if pic.data and len(pic.data) <= MAX_COVER_BYTES:
                        return bytes(pic.data), pic.mime or "image/jpeg"
            return None, None
    except Exception:
        return None, None
    return None, None


def read_details(path):
    """
    汇总一个音频文件的详细信息，返回 dict。任何字段读不到就是空串 / 0。
    """
    path = os.fspath(path)
    info = {
        "path": path,
        "name": os.path.basename(path),
        "folder": os.path.dirname(path),
        "format": format_name(path),
        "title": "",
        "artist": "",
        "album": "",
        "track": "",
        "year": "",
        "genre": "",
        "duration": 0.0,
        "bitrate": 0,
        "sample_rate": 0,
        "channels": 0,
        "size": 0,
        "mtime": 0.0,
        "has_cover": False,
        "error": "",
    }
    try:
        st = os.stat(path)
        info["size"] = st.st_size
        info["mtime"] = st.st_mtime
    except OSError as exc:
        info["error"] = f"无法读取文件：{exc}"

    try:
        import mutagen
        audio = mutagen.File(path, easy=True)
        if audio is None:
            info["error"] = info["error"] or " mutagen 无法识别的格式"
            return info

        tags = audio.tags or {}
        info["title"] = _first(tags.get("title"))
        info["artist"] = _first(tags.get("artist"))
        info["album"] = _first(tags.get("album"))
        info["track"] = _first(tags.get("tracknumber"))
        info["year"] = _first(tags.get("date")) or _first(tags.get("year"))
        info["genre"] = _first(tags.get("genre"))

        a = audio.info
        info["duration"] = float(getattr(a, "length", 0.0) or 0.0)
        info["bitrate"] = int(getattr(a, "bitrate", 0) or 0)
        info["sample_rate"] = int(getattr(a, "sample_rate", 0) or 0)
        info["channels"] = int(getattr(a, "channels", 0) or 0)
    except Exception as exc:
        info["error"] = info["error"] or f"{type(exc).__name__}: {exc}"

    try:
        cover, mime = read_cover(path)
        info["has_cover"] = cover is not None
    except Exception:
        pass
    return info


def human_size(num_bytes):
    try:
        n = float(num_bytes)
    except (TypeError, ValueError):
        return "-"
    if n < 1024:
        return f"{int(n)} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 / 1024:.2f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def human_duration(seconds):
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "--:--"
    if s <= 0:
        return "--:--"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"
