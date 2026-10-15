#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_integration.py —— NCM 集成的端到端验证

跑的补丁代码就是 build/main_combined.py 里那一份（也就是被编译进 exe 的），
所以这里通过就说明 exe 里的逻辑是对的。

验证链：装补丁 -> 扫描解密 -> 归档 -> 逐个产物与 expected.json 精确比对
"""
import hashlib
import json
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
sys.path.append(str(RUNTIME))
if hasattr(os, "add_dll_directory"):
    for d in (RUNTIME, RUNTIME / "PySide6", RUNTIME / "shiboken6"):
        if d.is_dir():
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass

checks = 0
fails = []


def check(name, cond, detail=""):
    global checks
    checks += 1
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if not cond else ""))
    if not cond:
        fails.append(f"{name} [{detail}]")


def sha(data):
    return hashlib.sha256(data).hexdigest()


# ───────────── 环境与素材 ─────────────

WORK = HERE / "e2e"
if WORK.exists():
    shutil.rmtree(WORK)
SRC = WORK / "source"
OUT = WORK / "output"
SRC.mkdir(parents=True)

# 本机沙箱不允许往「运行时新建的临时子目录」里写文件（原版 exe 的 _MEI 解包失败
# 也是同一个原因），所以测试时把解密缓存显式指到工作区。
NCM_CACHE = WORK / "cache"
os.environ["ITUNES_ASSISTANT_NCM_CACHE"] = str(NCM_CACHE)

FIX = HERE / "e2e-fixtures"
expected = json.loads((FIX / "expected.json").read_text(encoding="utf-8"))["fixtures"]
by_ncm = {e["ncm"]: e for e in expected}

sources = {
    "jia-mp3.ncm": "甲.ncm",
    "yi-flac.ncm": "乙.ncm",
    "bing-mp3.ncm": "丙.ncm",
    "ding-dup.ncm": "丁副本.ncm",
}
for src, dst in sources.items():
    shutil.copy2(FIX / src, SRC / dst)

# 一个普通 mp3，确认原有流程没被破坏
plain = b"\xff\xfb\x90\x64" + bytes((i * 31 + 7) & 0xFF for i in range(120000))
(SRC / "戊-普通文件.mp3").write_bytes(plain)

print(f"源目录 {SRC}")
for p in sorted(SRC.iterdir()):
    print(f"   {p.name:<20} {p.stat().st_size:>8} 字节")
print()

# ───────────── 装补丁 ─────────────

import core       # noqa: E402
import ncm_patch  # noqa: E402

ncm_patch.install()

check("core.scan_folder 已被替换", core.scan_folder is ncm_patch.scan_folder)
check("core.execute_jobs 已被替换", core.execute_jobs is ncm_patch.execute_jobs)

print("\n[1] 扫描与解密\n")

logs = []
tracks, ignored = core.scan_folder(SRC, recursive=True, on_log=lambda lv, m: logs.append((lv, m)))
print("  识别到的音轨:")
for t in sorted(tracks, key=lambda x: x.title):
    dur = f"{int(t.duration // 60)}:{int(t.duration % 60):02d}"
    print(f"    {t.path.name:<22} {t.artist or '—':<16} {t.title or '—':<10} {dur:>6}  {core.human_size(t.size)}")
print("\n  日志:")
for lv, m in logs:
    print(f"    [{lv}] {m}")

check("扫到 5 个音轨（4 个 NCM + 1 个原生 mp3）", len(tracks) == 5, f"实际 {len(tracks)}")
check("忽略计数已扣掉被处理的 NCM", ignored == 0, f"ignored={ignored}")
wrong = [t.title for t in tracks if t.title not in ("甲曲", "乙曲", "丙曲", "甲曲", "") and t.title]
check("标题全部来自 NCM 容器且解析正确",
      {t.title for t in tracks} == {"甲曲", "乙曲", "丙曲", ""}, str(sorted({t.title for t in tracks})))
check("艺术家数组被正确展平",
      any(t.artist == "歌手甲 / 歌手乙" for t in tracks),
      str(sorted({t.artist for t in tracks})))
check("NCM 扩展名按真实音频格式判定（mp3/flac 混排）",
      any(t.path.suffix == ".flac" for t in tracks) and any(t.path.suffix == ".mp3" for t in tracks))
check("时长从解密后的真实音频读出（乙曲=10 秒）",
      any(abs(t.duration - 10.0) < 0.1 for t in tracks),
      str([round(t.duration, 2) for t in tracks]))

print("\n[2] 归档执行\n")

settings = core.Settings(
    source=SRC, output_root=OUT, date_mode="today", group_by_album=False,
    name_pattern="{artist} - {title}", action="copy", recursive=True,
    skip_duplicates=True, make_playlist=True, playlist_name="导入 iTunes.m3u8",
    add_track_prefix=False,
)
jobs, summary = core.run_pipeline(settings, on_log=lambda lv, m: logs.append((lv, m)))

print(f"  复制 {summary.copied}，移动 {summary.moved}，跳过 {summary.skipped}，失败 {summary.failed}")
print(f"  播放列表 {summary.playlist}")
print("\n  输出树:")
for p in sorted(OUT.rglob("*")):
    rel = p.relative_to(OUT)
    print(f"    {rel}" + ("" if p.is_dir() else f"   {p.stat().st_size} 字节"))

check("4 个文件成功归档（3 个 NCM + 1 个 mp3）", summary.copied == 4, f"copied={summary.copied}")
check("重复的 NCM 被跳过", summary.skipped == 1, f"skipped={summary.skipped}")
check("没有失败", summary.failed == 0, f"failed={summary.failed}")
check("生成了 m3u8 播放列表",
      summary.playlist is not None and summary.playlist.exists()
      and summary.playlist.read_text(encoding="utf-8").startswith("#EXTM3U"))

# ───────────── 精确比对产物 ─────────────

print("\n[3] 产物逐项校验\n")

from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp3 import MP3

produced = [p for p in OUT.rglob("*") if p.is_file() and p.suffix.lower() in (".mp3", ".flac")]


def strip_id3(data):
    if data[:3] != b"ID3":
        return data
    size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
    return data[10 + size + (10 if data[5] & 0x10 else 0):]


def flac_audio_offset(data):
    """走过 FLAC 的元数据块链，返回音频帧起始偏移。"""
    assert data[:4] == b"fLaC"
    pos = 4
    while True:
        header = data[pos]
        length = int.from_bytes(data[pos + 1:pos + 4], "big")
        pos += 4 + length
        if header & 0x80:
            return pos


def find(title, ext):
    hits = [p for p in produced if p.suffix.lower() == f".{ext}" and title in p.name]
    return hits[0] if hits else None


# 甲曲：MP3 + JPEG 封面
print("  甲曲（MP3 + JPEG 封面）")
jia = by_ncm["jia-mp3.ncm"]
f = find("甲曲", "mp3")
check("甲曲有输出", f is not None)
if f:
    print(f"    -> {f.name}")
    raw = f.read_bytes()
    check("甲曲不是重复副本（含 {artist}-{title} 模板结果）", "歌手甲" in f.name and "甲曲" in f.name, f.name)
    check("剥掉 ID3 后音频与原始明文逐字节一致（未重新编码）",
          sha(strip_id3(raw)) == jia["audioSha256"],
          f"{sha(strip_id3(raw))[:12]} vs {jia['audioSha256'][:12]}")
    tags = ID3(f)
    check("TIT2 标题正确", str(tags["TIT2"]) == jia["meta"]["title"], str(tags.get("TIT2")))
    check("TPE1 艺术家正确", str(tags["TPE1"]) == jia["meta"]["artist"], str(tags.get("TPE1")))
    check("TALB 专辑正确", str(tags["TALB"]) == jia["meta"]["album"], str(tags.get("TALB")))
    apic = tags.getall("APIC")
    check("内嵌了 1 张封面", len(apic) == 1)
    if apic:
        check("封面 MIME 正确", apic[0].mime == jia["cover"]["mime"], apic[0].mime)
        check("封面与 NCM 容器内封面逐字节一致",
              sha(apic[0].data) == jia["cover"]["sha256"],
              f"{len(apic[0].data)} 字节")

# 乙曲：真 FLAC + PNG 封面
print("\n  乙曲（FLAC + PNG 封面）")
yi = by_ncm["yi-flac.ncm"]
f = find("乙曲", "flac")
check("乙曲有输出", f is not None)
if f:
    print(f"    -> {f.name}")
    raw = f.read_bytes()
    check("输出仍是合法 FLAC", raw[:4] == b"fLaC")
    orig = (FIX / "payload.flac").read_bytes()
    check("FLAC 音频帧逐字节未被改动（只插入了元数据块）",
          sha(raw[flac_audio_offset(raw):]) == sha(orig[flac_audio_offset(orig):]),
          f"{len(raw) - flac_audio_offset(raw)} vs {len(orig) - flac_audio_offset(orig)}")
    fl = FLAC(f)
    check("FLAC 标签写入成功（title）", fl.get("title") == [yi["meta"]["title"]], str(fl.get("title")))
    check("FLAC 标签写入成功（artist）", fl.get("artist") == [yi["meta"]["artist"]], str(fl.get("artist")))
    check("FLAC 标签写入成功（album）", fl.get("album") == [yi["meta"]["album"]], str(fl.get("album")))
    check("FLAC 内嵌了 1 张封面", len(fl.pictures) == 1, str(len(fl.pictures)))
    if fl.pictures:
        check("FLAC 封面 MIME 正确", fl.pictures[0].mime == yi["cover"]["mime"], fl.pictures[0].mime)
        check("FLAC 封面与 NCM 容器内封面逐字节一致",
              sha(fl.pictures[0].data) == yi["cover"]["sha256"],
              f"{len(fl.pictures[0].data)} 字节")
    check("FLAC 仍能被 mutagen 完整解析（时长 10 秒）", abs(fl.info.length - 10.0) < 0.1,
          str(round(fl.info.length, 3)))

# 丙曲：MP3，无封面
print("\n  丙曲（MP3，NCM 里没有封面）")
bing = by_ncm["bing-mp3.ncm"]
f = find("丙曲", "mp3")
check("丙曲有输出", f is not None)
if f:
    print(f"    -> {f.name}")
    raw = f.read_bytes()
    check("音频逐字节一致", sha(strip_id3(raw)) == bing["audioSha256"])
    tags = ID3(f)
    check("标题写入", str(tags["TIT2"]) == bing["meta"]["title"], str(tags.get("TIT2")))
    check("没有封面时不写 APIC", len(tags.getall("APIC")) == 0)

# 戊：原生 mp3 不受影响
print("\n  戊（原生 MP3，验证原有流程未被破坏）")
f = find("戊", "mp3")
if f is None:
    f = [p for p in produced if "普通" in p.name]
    f = f[0] if f else None
check("原生 mp3 正常归档", f is not None and f.read_bytes() == plain,
      "字节不一致" if f else "找不到")

# 播放列表
print("\n  播放列表")
text = summary.playlist.read_text(encoding="utf-8")
lines = [ln for ln in text.splitlines() if ln.strip()]
for ln in lines:
    print(f"    {ln}")
check("m3u8 条目数与成功归档数一致",
      sum(1 for ln in lines if ln.startswith("#EXTINF")) == summary.total_ok,
      f"{sum(1 for ln in lines if ln.startswith('#EXTINF'))} vs {summary.total_ok}")

# ───────────── 安全性与清理 ─────────────

print("\n[4] 安全性\n")
check("源目录中的 .ncm 未被改动或删除",
      sorted(p.name for p in SRC.iterdir()) == sorted(list(sources.values()) + ["戊-普通文件.mp3"]),
      str(sorted(p.name for p in SRC.iterdir())))
check("源 .ncm 内容逐字节未变",
      sha((SRC / "甲.ncm").read_bytes()) == sha((FIX / "jia-mp3.ncm").read_bytes()))

check("解密缓存已被清理",
      not NCM_CACHE.exists() or not any(NCM_CACHE.iterdir()),
      str(list(NCM_CACHE.iterdir())) if NCM_CACHE.exists() else "")

print("\n" + "─" * 62)
if not fails:
    print(f"端到端验证全部通过：{checks} 项 ✓")
    sys.exit(0)
print(f"通过 {checks - len(fails)}，失败 {len(fails)} ✗")
for x in fails:
    print("  -", x)
sys.exit(1)
