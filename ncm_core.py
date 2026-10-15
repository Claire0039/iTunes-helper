# -*- coding: utf-8 -*-
"""
ncm_core.py —— 网易云音乐 NCM 容器的解码核心（纯标准库实现）

程序里没有打包任何加密库（只有 stdlib + mutagen + PySide6），所以这里自带一份
AES-128-ECB 解密实现。AES 只用来解两小段数据（约几十字节），性能无关紧要。

NCM 容器格式（全部小端）：

    偏移  长度      字段
    0     8         magic = "CTENFDAM"
    8     2         gap（无意义）
    10    4         key_len
           key_len   加密的 RC4 密钥块
           4         meta_len（可为 0）
           meta_len  加密的 JSON 元数据
           4         crc32（各实现都不校验）
           1         image version
           4         cover_frame_len   封面帧总长（含尾部 padding）
           4         cover_len         封面图实际长度
           cover_len 封面图（裸 JPEG/PNG，未加密）
           frame-cover padding
           到文件尾  音频（流密码加密）

三段密码学变换：
  1) 密钥块：异或 0x64 → AES-128-ECB 解密（密钥 "hzHRAmso5kInbaxW"）→ 去掉前缀
     "neteasecloudmusic"（17 字节），剩下的是流密码密钥材料。
  2) 元数据：异或 0x63 → 去掉前缀 "163 key(Don't modify):"（22 字节）→ Base64 解码
     → AES-128-ECB 解密（密钥 "#14ljk_!\\]&0U<'("）→ 去掉 "music:"/"dj:" 前缀 → JSON。
  3) 音频：标准 RC4 的 KSA 得到置换表 S，但 PRGA 被改成只依赖绝对偏移的形式：
         j  = (off + 1) mod 256
         a  = S[j]
         b  = S[(a + j) mod 256]
         ks = S[(a + b) mod 256]
     正因为只跟 off 有关，密钥流以 256 为周期，可以直接摊成一张表反复使用。
"""

import base64
import json
import struct

# ───────────────────────── 常量 ─────────────────────────

NCM_MAGIC = b"CTENFDAM"
CORE_KEY = bytes.fromhex("687a4852416d736f356b496e62617857")  # b"hzHRAmso5kInbaxW"
META_KEY = bytes.fromhex("2331346c6a6b5f215c5d2630553c2728")  # b"#14ljk_!\\]&0U<'("
KEY_PREFIX = b"neteasecloudmusic"
META_PREFIX = "163 key(Don't modify):"

# 音频正文魔数嗅探：不信任元数据里的 format（可能是过期的）
_AUDIO_SNIFFERS = (
    ("mp3", "audio/mpeg", lambda b: len(b) >= 3 and b[:3] == b"ID3"),
    ("mp3", "audio/mpeg", lambda b: len(b) >= 2 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0),
    ("flac", "audio/flac", lambda b: len(b) >= 4 and b[:4] == b"fLaC"),
    ("m4a", "audio/mp4", lambda b: len(b) >= 8 and b[4:8] == b"ftyp"),
    ("wav", "audio/wav", lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE"),
    ("ogg", "audio/ogg", lambda b: len(b) >= 4 and b[:4] == b"OggS"),
)

_FORMAT_HINT = {"mp3": "mp3", "flac": "flac", "m4a": "m4a", "mp4": "m4a",
                "aac": "m4a", "wav": "wav", "ogg": "ogg"}


# ───────────────────────── AES-128-ECB ─────────────────────────

def _gf_mul(a, b):
    """GF(2^8) 乘法，模 x^8+x^4+x^3+x+1。"""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _build_tables():
    """现算 S 盒与逆 S 盒，比手抄 256 字节的表更不容易出错。"""
    # 注意：GF(2^8) 乘法群的生成元是 3（即 x+1），不是 2！
    # 2 只能生成 51 阶的子群，用它建表会得到完全错误的 S 盒。
    exp = [0] * 510
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x = _gf_mul(x, 3)
    for i in range(255, 510):
        exp[i] = exp[i - 255]

    inv = [0] * 256
    for i in range(255):
        inv[exp[i]] = exp[(255 - i) % 255]

    sbox = [0] * 256
    for i in range(256):
        v = inv[i]
        y = v
        for _ in range(4):
            v = ((v << 1) | (v >> 7)) & 0xFF     # 循环左移 1 位
            y ^= v
        sbox[i] = y ^ 0x63

    inv_sbox = [0] * 256
    for i, v in enumerate(sbox):
        inv_sbox[v] = i
    return sbox, inv_sbox


SBOX, INV_SBOX = _build_tables()
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _expand_key(key):
    """AES-128 密钥扩展，返回 44 个 4 字节字。"""
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]                      # RotWord
            t = [SBOX[b] for b in t]               # SubWord
            t[0] ^= _RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def _add_round_key(state, w, rnd):
    for c in range(4):
        for r in range(4):
            state[r + 4 * c] ^= w[rnd * 4 + c][r]


def _inv_shift_rows(s):
    # 第 r 行循环右移 r 位；state 里顺序是 s[r + 4c]
    for r in range(1, 4):
        vals = [s[r + 4 * c] for c in range(4)]
        vals = vals[-r:] + vals[:-r]
        for c in range(4):
            s[r + 4 * c] = vals[c]


def _inv_mix_columns(s):
    for c in range(4):
        i = 4 * c
        a0, a1, a2, a3 = s[i], s[i + 1], s[i + 2], s[i + 3]
        s[i] = _gf_mul(a0, 14) ^ _gf_mul(a1, 11) ^ _gf_mul(a2, 13) ^ _gf_mul(a3, 9)
        s[i + 1] = _gf_mul(a0, 9) ^ _gf_mul(a1, 14) ^ _gf_mul(a2, 11) ^ _gf_mul(a3, 13)
        s[i + 2] = _gf_mul(a0, 13) ^ _gf_mul(a1, 9) ^ _gf_mul(a2, 14) ^ _gf_mul(a3, 11)
        s[i + 3] = _gf_mul(a0, 11) ^ _gf_mul(a1, 13) ^ _gf_mul(a2, 9) ^ _gf_mul(a3, 14)


def aes128_ecb_decrypt_block(block, w):
    s = list(block)
    _add_round_key(s, w, 10)
    for rnd in range(9, 0, -1):
        _inv_shift_rows(s)
        s = [INV_SBOX[b] for b in s]
        _add_round_key(s, w, rnd)
        _inv_mix_columns(s)
    _inv_shift_rows(s)
    s = [INV_SBOX[b] for b in s]
    _add_round_key(s, w, 0)
    return bytes(s)


def aes128_ecb_decrypt(data, key):
    """AES-128-ECB 解密并去掉 PKCS#7 填充。"""
    if len(data) % 16:
        raise ValueError("AES 密文长度不是 16 的倍数")
    w = _expand_key(key)
    out = bytearray()
    for i in range(0, len(data), 16):
        out += aes128_ecb_decrypt_block(data[i:i + 16], w)
    if out:
        pad = out[-1]
        if 1 <= pad <= 16 and out[-pad:] == bytes([pad]) * pad:
            del out[-pad:]
    return bytes(out)


# ───────────────────────── 密钥流 ─────────────────────────

def build_key_box(key_data):
    """
    由密钥材料生成 256 字节的密钥流周期表。
    前半段是标准 RC4 的 KSA，后半段是 NCM 改造过的 PRGA 展开。
    """
    s = list(range(256))
    j = 0
    klen = len(key_data)
    if klen == 0:
        raise ValueError("NCM 密钥材料为空")
    for i in range(256):
        j = (j + s[i] + key_data[i % klen]) & 0xFF
        s[i], s[j] = s[j], s[i]

    box = bytearray(256)
    for off in range(256):
        jj = (off + 1) & 0xFF
        a = s[jj]
        b = s[(a + jj) & 0xFF]
        box[off] = s[(a + b) & 0xFF]
    return bytes(box)


def xor_key_stream(data, box):
    """
    用 256 周期的密钥流就地异或。异或自逆，加密/解密是同一个操作。

    用大整数异或来跑，比逐字节 Python 循环快一个数量级。
    """
    n = len(data)
    step = (8 << 20) & ~0xFF          # 8 MiB，且保证是 256 的整数倍，便于取密钥流
    pos = 0
    while pos < n:
        end = min(pos + step, n)
        ln = end - pos
        ks = (box * ((ln + 255) // 256))[:ln]
        mixed = int.from_bytes(data[pos:end], "big") ^ int.from_bytes(ks, "big")
        data[pos:end] = mixed.to_bytes(ln, "big")
        pos = end
    return data


# ───────────────────────── 容器解析 ─────────────────────────

class NcmError(Exception):
    """NCM 文件损坏或不是 NCM。"""


def is_ncm(head: bytes) -> bool:
    return head[:8] == NCM_MAGIC


def parse(buf: bytes):
    """
    解析 NCM 头部，返回一个 dict：
        key       流密码密钥材料
        metadata  元数据 dict（可能为空）
        cover     封面图 bytes 或 None
        cover_mime
        audio_off 音频在文件中的起始偏移
    """
    if not is_ncm(buf):
        raise NcmError("不是 NCM 文件：文件头魔数不匹配（期望 CTENFDAM）")

    off = 10  # 跳过 magic(8) + gap(2)

    # ── 1. RC4 密钥块 ──
    if off + 4 > len(buf):
        raise NcmError("文件损坏：读不到密钥段长度")
    key_len = struct.unpack_from("<I", buf, off)[0]
    off += 4
    if off + key_len > len(buf):
        raise NcmError("文件损坏：密钥段长度越界")
    key_blob = bytearray(buf[off:off + key_len])
    off += key_len
    for i in range(len(key_blob)):
        key_blob[i] ^= 0x64
    key_plain = aes128_ecb_decrypt(bytes(key_blob), CORE_KEY)
    if not key_plain.startswith(KEY_PREFIX):
        raise NcmError("文件损坏或并非真正的 NCM：密钥明文前缀不匹配")
    key_data = key_plain[len(KEY_PREFIX):]
    if not key_data:
        raise NcmError("文件损坏：流密码密钥为空")

    # ── 2. 元数据 ──
    if off + 4 > len(buf):
        raise NcmError("文件损坏：读不到元数据长度")
    meta_len = struct.unpack_from("<I", buf, off)[0]
    off += 4
    if off + meta_len > len(buf):
        raise NcmError("文件损坏：元数据段长度越界")

    metadata = {}
    if meta_len > 0:
        meta_blob = bytearray(buf[off:off + meta_len])
        off += meta_len
        for i in range(len(meta_blob)):
            meta_blob[i] ^= 0x63
        text = bytes(meta_blob)
        if text[:22].decode("latin1") == META_PREFIX:
            text = text[22:]
        else:
            raise NcmError("文件损坏：元数据缺少 '163 key(Don't modify):' 前缀")
        plain = aes128_ecb_decrypt(base64.b64decode(text), META_KEY).decode("utf-8", "replace")
        colon = plain.find(":")
        if colon < 0:
            raise NcmError("文件损坏：元数据缺少分隔符")
        kind = plain[:colon]
        parsed = json.loads(plain[colon + 1:])
        if kind == "dj" and isinstance(parsed, dict) and "mainMusic" in parsed:
            parsed = parsed["mainMusic"]
        metadata = parsed if isinstance(parsed, dict) else {}

    # ── 3. 跳过 CRC32 + 版本号，读封面帧 ──
    if off + 13 > len(buf):
        raise NcmError("文件损坏：头部不完整")
    off += 4  # crc32
    off += 1  # image version
    cover_frame_len = struct.unpack_from("<I", buf, off)[0]
    off += 4
    cover_len = struct.unpack_from("<I", buf, off)[0]
    off += 4

    cover = None
    if cover_len > 0 and off + cover_len <= len(buf):
        cover = bytes(buf[off:off + cover_len])

    # 关键：必须按 cover_frame_len 前进，而不是 cover_len。
    # 新版客户端会预留更大的封面帧（甚至 cover_len = 0），少跳这段 padding
    # 会把 padding 当成音频解密，密钥流整体错位，输出全是噪声。
    off += max(cover_frame_len, cover_len)

    if off >= len(buf):
        raise NcmError("文件损坏：没有音频数据")

    return {
        "key": key_data,
        "metadata": metadata,
        "cover": cover,
        "cover_mime": sniff_image(cover) if cover else None,
        "audio_off": off,
    }


def sniff_image(data):
    if not data:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def sniff_audio(head, hint=None):
    """从音频开头魔数判断真实格式，失败时退回元数据里的 format 提示。"""
    for ext, mime, test in _AUDIO_SNIFFERS:
        try:
            if test(head):
                return ext, mime, True
        except Exception:
            pass
    ext = _FORMAT_HINT.get((hint or "").lower())
    return (ext or "bin"), "application/octet-stream", False


def normalize_metadata(raw):
    """把 NCM 的元数据整理成好用的扁平结构。"""
    artists = []
    a = raw.get("artist")
    if isinstance(a, list):
        for item in a:
            if isinstance(item, (list, tuple)) and item:
                artists.append(str(item[0]))
            elif isinstance(item, dict) and item.get("name"):
                artists.append(str(item["name"]))
            elif isinstance(item, str):
                artists.append(item)
    elif isinstance(a, str) and a:
        artists = [x.strip() for x in a.split(",") if x.strip()]

    def _num(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    return {
        "title": raw.get("musicName") or raw.get("songName") or "",
        "artists": artists,
        "artist": " / ".join(artists),
        "album": raw.get("album") if isinstance(raw.get("album"), str) else "",
        "track_no": _num(raw.get("track")),
        "duration": _num(raw.get("duration")) / 1000.0,
        "bitrate": _num(raw.get("bitrate")),
        "format_hint": (raw.get("format") or "").lower(),
    }


def read_ncm(path):
    """
    读取并解密一个 NCM 文件，返回 (解密后的音频 bytes, 扩展名, 元数据 dict, 封面 bytes, 封面 mime)。
    整套操作在内存里完成；典型单曲 10~50 MB，可以接受。
    """
    with open(path, "rb") as fh:
        buf = fh.read()

    info = parse(buf)
    meta = normalize_metadata(info["metadata"])

    audio = bytearray(buf[info["audio_off"]:])
    xor_key_stream(audio, build_key_box(info["key"]))

    ext, _mime, sniffed = sniff_audio(bytes(audio[:16]), meta["format_hint"])
    if not sniffed:
        raise NcmError(
            "音频头无法识别（解密失败或容器布局异常）；元数据自述格式为 "
            f"{meta['format_hint'] or '未知'}"
        )

    return bytes(audio), ext, meta, info["cover"], info["cover_mime"]


def peek_ncm(path):
    """只读地看一眼 NCM 的元数据，不解密音频。用于快速扫描。"""
    with open(path, "rb") as fh:
        head = fh.read()
    info = parse(head)
    meta = normalize_metadata(info["metadata"])
    ext, _mime, sniffed = sniff_audio(b"", meta["format_hint"])
    return meta, info["cover"], info["cover_mime"], ext
