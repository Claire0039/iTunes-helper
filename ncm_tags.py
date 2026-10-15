# -*- coding: utf-8 -*-
"""
ncm_tags.py —— 把 NCM 容器里带的元数据和封面写进解密出来的音频文件

复用程序里已经打包的 mutagen。参照 core.read_metadata 的既有约定：
任何异常都退化为「无标签」，绝不因为写标签失败而中断整批任务。

支持 mp3 / flac / m4a / ogg / wav，其余格式静默跳过。
"""


def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def write_tags(path, ext, meta, cover=None, cover_mime=None):
    """
    把元数据（可选封面）写进音频文件。

    path        解密后的音频文件路径（会被就地修改）
    ext         扩展名，小写且不含点，如 "mp3"
    meta        ncm_core.normalize_metadata 的输出
    cover       封面图 bytes 或 None
    cover_mime  封面 MIME

    返回 True 表示写入了内容，False 表示没写（格式不支持或数据为空）。
    """
    artist = _clean(meta.get("artist"))
    title = _clean(meta.get("title"))
    album = _clean(meta.get("album"))
    track_no = int(meta.get("track_no") or 0)

    if not (artist or title or album or track_no or cover):
        return False

    try:
        if ext == "mp3":
            return _write_id3(path, artist, title, album, track_no, cover, cover_mime)
        if ext == "flac":
            return _write_flac(path, artist, title, album, track_no, cover, cover_mime)
        if ext in ("m4a", "m4b", "mp4", "alac"):
            return _write_mp4(path, artist, title, album, track_no, cover, cover_mime)
        if ext == "ogg":
            return _write_vorbis(path, artist, title, album, track_no, cover, cover_mime, "OggVorbis")
        if ext == "opus":
            return _write_vorbis(path, artist, title, album, track_no, cover, cover_mime, "OggOpus")
        if ext in ("wav", "aiff", "aif"):
            return _write_id3(path, artist, title, album, track_no, cover, cover_mime, wav_like=True)
    except Exception:
        # 写标签失败不影响音频本身，静默退化
        return False
    return False


def _write_id3(path, artist, title, album, track_no, cover, cover_mime, wav_like=False):
    from mutagen.id3 import (ID3, ID3NoHeaderError, TIT2, TPE1, TALB, TRCK, APIC)

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    if title:
        tags.add(TIT2(encoding=3, text=title))
    if artist:
        tags.add(TPE1(encoding=3, text=artist))
    if album:
        tags.add(TALB(encoding=3, text=album))
    if track_no:
        tags.add(TRCK(encoding=3, text=str(track_no)))
    if cover:
        tags.add(APIC(encoding=3, mime=cover_mime or "image/jpeg",
                      type=3, desc="Cover", data=cover))

    if wav_like:
        # WAVE / AIFF 用各自的容器类保存
        if path.lower().endswith((".aif", ".aiff")):
            from mutagen.aiff import AIFF
            f = AIFF(path)
        else:
            from mutagen.wave import WAVE
            f = WAVE(path)
        f.add_tags()
        for frame in tags.values():
            f.tags.add(frame)
        f.save()
    else:
        tags.save(path)
    return True


def _write_flac(path, artist, title, album, track_no, cover, cover_mime):
    from mutagen.flac import FLAC, Picture

    f = FLAC(path)
    if artist:
        f["artist"] = [artist]
    if title:
        f["title"] = [title]
    if album:
        f["album"] = [album]
    if track_no:
        f["tracknumber"] = [str(track_no)]
    if cover:
        pic = Picture()
        pic.type = 3
        pic.mime = cover_mime or "image/jpeg"
        pic.desc = "Cover"
        pic.data = cover
        f.clear_pictures()
        f.add_picture(pic)
    f.save()
    return True


def _write_vorbis(path, artist, title, album, track_no, cover, cover_mime, cls_name):
    import mutagen.oggvorbis
    import mutagen.oggopus

    cls = getattr(mutagen.oggvorbis, "OggVorbis")
    if cls_name == "OggOpus":
        cls = getattr(mutagen.oggopus, "OggOpus")
    f = cls(path)
    if artist:
        f["artist"] = [artist]
    if title:
        f["title"] = [title]
    if album:
        f["album"] = [album]
    if track_no:
        f["tracknumber"] = [str(track_no)]
    f.save()
    return True


def _write_mp4(path, artist, title, album, track_no, cover, cover_mime):
    from mutagen.mp4 import MP4, MP4Cover

    f = MP4(path)
    if artist:
        f["\xa9ART"] = [artist]
    if title:
        f["\xa9nam"] = [title]
    if album:
        f["\xa9alb"] = [album]
    if track_no:
        f["trkn"] = [(int(track_no), 0)]
    if cover:
        fmt = (MP4Cover.FORMAT_PNG if (cover_mime or "").endswith("png")
               else MP4Cover.FORMAT_JPEG)
        f["covr"] = [MP4Cover(cover, imageformat=fmt)]
    f.save()
    return True
