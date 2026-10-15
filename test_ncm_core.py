#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ncm_core.py —— 验证 ncm_core.py

三层互相独立的验证：
  1. AES：用 Node/OpenSSL 生成的测试向量 + FIPS-197 标准向量校验纯 Python 实现
  2. 密钥流：与「照规范逐偏移计算、不打表」的参考实现比对（避免循环论证）
  3. 容器：用上一步做出来的、已被 ncm2mp3.com 线上代码交叉验证过的真实样本做往返
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ncm_core as N

HERE = pathlib.Path(__file__).parent
FIXTURES = HERE.parent / "testdata"          # 上一个任务里生成的、已被网站代码验证过的样本
EXPECTED = FIXTURES / "expected"

checks = 0
fails = []


def check(name, cond, detail=""):
    global checks
    checks += 1
    if cond:
        print(f"  OK   {name}")
    else:
        print(f"  FAIL {name}  {detail}")
        fails.append(f"{name} {detail}")


# ─────────────── 1. AES vs Node/OpenSSL ───────────────

print("\n[1] AES-128-ECB 解密 vs Node/OpenSSL\n")

vec_path = HERE / "aes_vectors.json"
if not vec_path.exists():
    print("  需要先运行 node gen_aes_vectors.js")
    sys.exit(2)

vectors = json.loads(vec_path.read_text(encoding="utf-8"))
ok = 0
for v in vectors:
    key = bytes.fromhex(v["key"])
    ct = bytes.fromhex(v["ciphertext"])
    want = bytes.fromhex(v["plaintext"])
    try:
        got = N.aes128_ecb_decrypt(ct, key)
    except Exception as exc:
        fails.append(f"{v['name']}: 抛异常 {exc}")
        continue
    if got == want:
        ok += 1
    else:
        fails.append(f"{v['name']}: 明文不符")
check(f"{len(vectors)} 条测试向量全部解密正确", ok == len(vectors), f"实际 {ok}/{len(vectors)}")

# FIPS-197 单分组（无填充）也要对
v = vectors[0]
got = N.aes128_ecb_decrypt(bytes.fromhex(v["ciphertext"]), bytes.fromhex(v["key"]))
check("FIPS-197 标准向量", got == bytes.fromhex(v["plaintext"]), f"得到 {got.hex()}")

# S 盒自检：SBOX[0] 必须是 0x63，INV_SBOX 必须是逆置换
check("S 盒自检 (SBOX[0]=0x63, 逆置换自洽)",
      N.SBOX[0] == 0x63 and all(N.INV_SBOX[N.SBOX[i]] == i for i in range(256)))

# ─────────────── 2. 密钥流 vs 规范参考实现 ───────────────

print("\n[2] 密钥流周期表 vs 逐偏移参考实现\n")


def ref_ksa(key_data):
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key_data[i % len(key_data)]) % 256
        s[i], s[j] = s[j], s[i]
    return s


def ref_keystream(s, off):
    j = (off + 1) % 256
    a = s[j]
    b = s[(a + j) % 256]
    return s[(a + b) % 256]


def ref_xor(data, key_data):
    s = ref_ksa(key_data)
    out = bytearray(data)
    for off in range(len(out)):
        out[off] ^= ref_keystream(s, off)
    return bytes(out)


import random
random.seed(20240607)

mismatch = 0
for trial in range(30):
    key = bytes(random.randrange(256) for _ in range(random.randint(1, 32)))
    box = N.build_key_box(key)
    s = ref_ksa(key)
    for off in range(256):
        if box[off] != ref_keystream(s, off):
            mismatch += 1
check("build_key_box 与逐偏移公式完全一致（30 组随机密钥 × 256 偏移）", mismatch == 0,
      f"{mismatch} 处不符")

# 非 256 对齐长度 + 分块场景
ok = True
for ln in (1, 17, 255, 256, 257, 4096, 100000):
    key = bytes(random.randrange(256) for _ in range(16))
    data = bytes(random.randrange(256) for _ in range(ln))
    a = N.xor_key_stream(bytearray(data), N.build_key_box(key))
    b = ref_xor(data, key)
    if bytes(a) != b:
        ok = False
check("xor_key_stream 与参考实现一致（含非 256 对齐长度）", ok)

# ─────────────── 3. 真实样本往返 ───────────────

print("\n[3] NCM 容器解析：用已被线上代码验证过的样本\n")

if not FIXTURES.exists():
    print(f"  找不到样本目录 {FIXTURES}（请先运行上一个任务的 selftest.js）")
else:
    cases = [
        ("A-old-layout.ncm", "mp3", "audio-mp3-expected.bin", "image/jpeg", "cover-jpeg-expected.bin"),
        ("B-padded-cover.ncm", "mp3", "audio-mp3-expected.bin", "image/jpeg", "cover-jpeg-expected.bin"),
        ("C-zero-cover-len.ncm", "mp3", "audio-mp3-expected.bin", None, None),
        ("D-no-cover-FLAC.ncm", "flac", "audio-flac-expected.bin", None, None),
        ("E-dj-format.ncm", "mp3", "audio-mp3-expected.bin", "image/png", "cover-png-expected.bin"),
        ("F-large-padding.ncm", "flac", "audio-flac-expected.bin", "image/png", "cover-png-expected.bin"),
    ]
    for name, want_ext, want_audio, want_mime, want_cover in cases:
        f = FIXTURES / name
        if not f.exists():
            check(f"{name} 存在", False, "文件缺失")
            continue
        try:
            audio, ext, meta, cover, mime = N.read_ncm(f)
        except Exception as exc:
            check(f"{name} 解密", False, f"抛异常 {exc}")
            continue

        want = (EXPECTED / want_audio).read_bytes()
        check(f"{name}: 音频逐字节一致 ({ext}, {len(audio)} 字节)", audio == want,
              f"长度 {len(audio)} vs {len(want)}")

        if want_mime:
            cov_want = (EXPECTED / want_cover).read_bytes()
            check(f"{name}: 封面逐字节一致 ({mime})", cover == cov_want,
                  f"长度 {len(cover) if cover else 0} vs {len(cov_want)}")
        else:
            check(f"{name}: 正确地没有封面", not cover)

    # 元数据
    audio, ext, meta, cover, mime = N.read_ncm(FIXTURES / "A-old-layout.ncm")
    check("标题解析正确", meta["title"] == "测试歌曲 · Test Song", repr(meta["title"]))
    check("艺术家列表展平正确", meta["artists"] == ["周杰伦", "费玉清"], repr(meta["artists"]))
    check("艺术家合并串", meta["artist"] == "周杰伦 / 费玉清", repr(meta["artist"]))
    check("专辑解析正确", meta["album"] == "哎呦，不错哦", repr(meta["album"]))
    check("音轨号解析正确", meta["track_no"] == 3, repr(meta["track_no"]))
    check("时长换算为秒", abs(meta["duration"] - 269.0) < 0.01, repr(meta["duration"]))

    # 非 NCM 文件必须被拒绝
    try:
        N.parse(b"\x00" * 200)
        check("非 NCM 文件被拒绝", False, "没有抛异常")
    except N.NcmError:
        check("非 NCM 文件被拒绝", True)

    # peek_ncm 不应解密音频
    m, cv, cm, ex = N.peek_ncm(FIXTURES / "A-old-layout.ncm")
    check("peek_ncm 能读出元数据与格式", m["title"] == "测试歌曲 · Test Song" and ex == "mp3")

# ─────────────── 4. 性能 ───────────────

print("\n[4] 性能\n")
key = bytes(range(16))
box = N.build_key_box(key)
big = bytearray(50 * 1024 * 1024)          # 50 MB，约等于一张无损专辑单曲
t0 = time.time()
N.xor_key_stream(big, box)
dt = time.time() - t0
check(f"50 MB 密钥流异或耗时 {dt:.2f}s（>{50/dt:.0f} MB/s）", dt < 5.0)

# ─────────────── 汇总 ───────────────

print("\n" + "─" * 60)
if not fails:
    print(f"全部通过：{checks} 项 ✓")
    sys.exit(0)
print(f"通过 {checks - len(fails)}，失败 {len(fails)} ✗")
for f in fails:
    print("  -", f)
sys.exit(1)
