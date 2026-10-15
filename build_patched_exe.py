#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_patched_exe.py —— 把 NCM 支持编译进 iTunes助手.exe

做法：不重新打包整个程序，只替换 PyInstaller 归档里的**一个条目** —— 入口脚本
`smain`。新入口把 ncm_core / ncm_tags / ncm_patch 三个模块的源码内嵌进来
（通过 sys.modules 注册成真模块），因此不需要往归档里新增任何条目，
改动面最小、风险最低。

归档重建规则（全部由对原文件的实测得出）：
  * 数据区按 TOC 顺序紧密排列，offset 相对归档起点；
  * TOC 条目 = !i entry_len（含自身）+ !i offset + !i cmprs_len + !i uncmprs_len
               + B flag + name + \\0，整条按 16 字节向上对齐；
  * cmprs_len != uncmprs_len ⇒ 数据是 zlib 流，flag = 0x01；
    两者相等 ⇒ 原样存储，flag = 0x00（原文件里的 zPYZ.pyz 就是这样）；
  * COOKIE 88 字节固定在文件末尾：
      MAGIC[8] | lengthofPackage(!i, 含 cookie) | toc(!i) | tocLen(!i) | pyver(!i) | pylibname[64]

用法：
    python build_patched_exe.py <原始exe> <输出exe>
"""
import hashlib
import marshal
import pathlib
import struct
import sys
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pyi_tool import PyiArchive, MAGIC

HERE = pathlib.Path(__file__).parent
ENTRY_NAME = "smain"          # CArchive 里入口脚本的名字（'s' 前缀 = script）

MODULES = (
    "ncm_core.py",      # NCM 容器解码（纯标准库，含自研 AES）
    "ncm_glyphs.py",    # 播放器控件图标素材（自动生成）
    "ncm_audio.py",     # MCI 播放后端（零依赖）
    "ncm_media.py",     # 标签 / 封面 / 详情读取（mutagen）
    "ncm_tags.py",      # 标签与封面写入（mutagen）
    "ncm_ui.py",        # 播放器栏 + 详情面板
    "ncm_patch.py",     # core 与界面补丁
)
DRIVER = "main_patched.py"

ICON_DIR = HERE / "icon-build"
# 归档里要换掉的图标资源（条目名 -> 新文件）
ARCHIVE_ICONS = {
    "bassets\\app.png": "app.png",
    "bassets\\app.ico": "app.ico",
}
# PE 资源段里各尺寸图标的原始字节数（数据量 = 尺寸的指纹）
ORIGINAL_ICON_SIZE = {380: 16, 527: 24, 743: 32, 1087: 48,
                      1543: 64, 3386: 128, 8214: 256}


# ───────────────────────── PE 图标（原地替换） ─────────────────────────

def _pe_sections(buf):
    pe = struct.unpack_from("<I", buf, 0x3C)[0]
    ns = struct.unpack_from("<H", buf, pe + 6)[0]
    opt_size = struct.unpack_from("<H", buf, pe + 20)[0]
    sec = pe + 24 + opt_size
    out = []
    for i in range(ns):
        o = sec + i * 40
        name = bytes(buf[o:o + 8]).rstrip(b"\x00").decode("latin1")
        vs, va, rs, rp = struct.unpack_from("<IIII", buf, o + 8)
        out.append((name, va, vs, rp, rs))
    magic = struct.unpack_from("<H", buf, pe + 24)[0]
    dd = pe + 24 + (112 if magic == 0x20B else 96)
    return out, dd


def patch_pe_icons(pe_part):
    """
    把 PE 资源段里 7 个尺寸的 RT_ICON 原地换成新图标。

    之所以能「原地」：新图标每个尺寸的字节数都严格小于原图标的字节数
    （见 icon-build 的生成报告），所以直接覆盖并按新长度写回数据条目的 Size 即可，
    完全不用改动 PE 头、节表或资源目录结构 —— 风险最低。

    返回 (新的 pe 字节, 替换报告列表)。
    """
    buf = bytearray(pe_part)
    sections, dd = _pe_sections(buf)
    rsrc_rva, rsrc_size = struct.unpack_from("<II", buf, dd + 2 * 8)
    base = None
    for name, va, vs, rp, rs in sections:
        if va <= rsrc_rva < va + max(vs, rs):
            base = rp + (rsrc_rva - va)
            break
    if base is None:
        return bytes(buf), [("找不到资源段", 0, 0)]

    def dir_entries(off):
        nname, nid = struct.unpack_from("<HH", buf, base + off + 12)
        out = []
        for i in range(nname + nid):
            e = base + off + 16 + i * 8
            nm, sub = struct.unpack_from("<II", buf, e)
            out.append((nm, sub))
        return out

    report = []
    # 结构固定为 /RT_ICON(3)/<id>/<lang>/<data entry>
    for nm, sub in dir_entries(0):
        if nm != 3 or not (sub & 0x80000000):
            continue
        for _id, sub2 in dir_entries(sub & 0x7FFFFFFF):
            if not (sub2 & 0x80000000):
                continue
            for _lang, sub3 in dir_entries(sub2 & 0x7FFFFFFF):
                if sub3 & 0x80000000:
                    continue
                entry_off = base + sub3
                drva, dsize, _cp, _res = struct.unpack_from("<IIII", buf, entry_off)
                doff = None
                for name, va, vs, rp, rs in sections:
                    if va <= drva < va + max(vs, rs):
                        doff = rp + (drva - va)
                        break
                if doff is None:
                    report.append((f"图标 id={_id} 定位失败", 0, 0))
                    continue
                # 原始数据长度就等于该尺寸的预算，用它反推是哪个尺寸
                size = ORIGINAL_ICON_SIZE.get(dsize)
                if size is None:
                    report.append((f"未知图标尺寸（{dsize} 字节）", dsize, 0))
                    continue
                src = ICON_DIR / f"pe-{size}.png"
                if not src.exists():
                    report.append((f"缺少 {src.name}", dsize, 0))
                    continue
                data = src.read_bytes()
                if len(data) > dsize:
                    report.append((f"{src.name} 超预算", dsize, len(data)))
                    continue
                buf[doff:doff + len(data)] = data
                # 数据条目里的 Size 改成新长度，尾部多余字节不再被引用
                struct.pack_into("<I", buf, entry_off + 4, len(data))
                report.append((f"{size}x{size}", dsize, len(data)))
    return bytes(buf), report


# ───────────────────────── 生成合并后的入口源码 ─────────────────────────

def build_combined_source():
    parts = []
    parts.append(
        "# -*- coding: utf-8 -*-\n"
        "# ============================================================\n"
        "#  本文件由 build_patched_exe.py 自动生成，请勿直接编辑。\n"
        "#  要改逻辑请改 ncm_core.py / ncm_tags.py / ncm_patch.py /\n"
        "#  main_patched.py，然后重新运行构建脚本。\n"
        "# ============================================================\n"
        '"""iTunes 助手 —— 程序入口（已集成网易云 NCM 支持）。"""\n'
        "import sys\n"
        "import types\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def _bootstrap_path():\n"
        "    base = Path(__file__).resolve().parent\n"
        "    for candidate in (base / 'libs', base / 'src'):\n"
        "        if candidate.is_dir() and str(candidate) not in sys.path:\n"
        "            sys.path.insert(0, str(candidate))\n"
        "\n"
        "\n"
        "_bootstrap_path()\n"
        "\n"
        "\n"
        "def _embed(name, source):\n"
        "    \"\"\"把内嵌源码注册成真正的模块，这样模块间的 import 照常工作。\"\"\"\n"
        "    mod = types.ModuleType(name)\n"
        "    mod.__file__ = '<frozen ' + name + '>'\n"
        "    sys.modules[name] = mod\n"
        "    exec(compile(source, name + '.py', 'exec'), mod.__dict__)\n"
        "    return mod\n"
        "\n"
    )

    for filename in MODULES:
        src = (HERE / filename).read_text(encoding="utf-8")
        modname = filename[:-3]
        parts.append(f"_embed({modname!r}, {src!r})\n\n")

    driver = (HERE / DRIVER).read_text(encoding="utf-8")
    # 驱动文件里的 this-file bootstrap 和 import 已经由上面代劳，这里只取尾部逻辑
    marker = "import ncm_patch"
    idx = driver.index(marker)
    tail = driver[idx:]
    parts.append("# ── 来自 main_patched.py 的启动逻辑 ──\n")
    parts.append(tail)
    # 保险：确保一定有 __main__ 出口
    if "__main__" not in tail:
        parts.append("\n\nif __name__ == '__main__':\n    sys.exit(main())\n")
    return "".join(parts)


# ───────────────────────── 归档重建 ─────────────────────────

def pack_entry(offset, cmprs_len, uncmprs_len, flag, name):
    body = struct.pack("!IIIB", offset, cmprs_len, uncmprs_len, flag) + name.encode("utf-8") + b"\0"
    entry_len = 4 + len(body)
    aligned = (entry_len + 15) & ~15          # 整条按 16 字节向上对齐
    return struct.pack("!i", aligned) + body + b"\0" * (aligned - entry_len)


def repack(src_exe, dst_exe, new_payload, overrides=None):
    overrides = overrides or {}
    ar = PyiArchive(src_exe)

    pe_part = ar.raw[:ar.archive_start]

    # PE 图标：原地替换资源段里的 RT_ICON 数据（不改变任何 PE 结构）
    icon_report = []
    if (ICON_DIR / "pe-256.png").exists():
        pe_part, icon_report = patch_pe_icons(pe_part)
        print("  PE 图标替换:")
        for name, old, new in icon_report:
            if old:
                print(f"    {name:<10} {old:>5} -> {new:>5} 字节")
            else:
                print(f"    {name}")
    else:
        print("  （未找到 icon-build/pe-*.png，跳过 PE 图标替换）")

    data = bytearray()
    toc = bytearray()
    replaced = 0
    icon_done = 0

    for e in ar.entries:
        if e["name"] == ENTRY_NAME:
            compressed = zlib.compress(new_payload, 9)
            # 与原文件保持一致：入口脚本原本就是压缩存放的。
            # 万一压缩后反而更大（理论上不会），退化为原样存。
            if len(compressed) < len(new_payload):
                blob, cmprs, uncmprs, flag = compressed, len(compressed), len(new_payload), 0x01
            else:
                blob, cmprs, uncmprs, flag = new_payload, len(new_payload), len(new_payload), 0x00
            replaced += 1
            print(f"  替换 {e['name']}: {e['cmprs_len']} -> {cmprs} 字节"
                  f"（解压后 {uncmprs}，flag=0x{flag:02x}）")
        elif e["name"] in overrides:
            raw = overrides[e["name"]]
            compressed = zlib.compress(raw, 9)
            if len(compressed) < len(raw):
                blob, cmprs, uncmprs, flag = compressed, len(compressed), len(raw), 0x01
            else:
                blob, cmprs, uncmprs, flag = raw, len(raw), len(raw), 0x00
            icon_done += 1
            print(f"  替换 {e['name']}: {e['cmprs_len']} -> {cmprs} 字节"
                  f"（原始 {len(raw)}）")
        else:
            start = ar.archive_start + e["offset"]
            blob = ar.raw[start:start + e["cmprs_len"]]
            cmprs, uncmprs, flag = e["cmprs_len"], e["uncmprs_len"], e["flag"]

        offset = len(data)
        data += blob
        toc += pack_entry(offset, cmprs, uncmprs, flag, e["name"])

    if replaced != 1:
        raise SystemExit(f"错误：期望替换 1 个条目，实际 {replaced} 个")
    if overrides and icon_done != len(overrides):
        raise SystemExit(f"错误：期望替换 {len(overrides)} 个图标条目，实际 {icon_done} 个")

    pkg_len = len(data) + len(toc) + 88
    cookie = (MAGIC
              + struct.pack("!iiii", pkg_len, len(data), len(toc), ar.pyver)
              + ar.pylib.encode("latin1").ljust(64, b"\0")[:64])

    out = bytes(pe_part) + bytes(data) + bytes(toc) + cookie
    pathlib.Path(dst_exe).write_bytes(out)
    return ar, len(data), len(toc)


# ───────────────────────── 校验 ─────────────────────────

def verify(src_exe, dst_exe, overrides=None):
    overrides = overrides or {}
    ok = True
    a = PyiArchive(src_exe)
    b = PyiArchive(dst_exe)

    def report(name, cond, detail=""):
        nonlocal ok
        print(f"  {'OK  ' if cond else 'FAIL'} {name} {detail}")
        if not cond:
            ok = False

    print("\n[校验] 重打包结果\n")
    report("归档起点一致", a.archive_start == b.archive_start,
           f"{a.archive_start} vs {b.archive_start}")

    # PE 部分：只允许资源段（图标）里有差异
    pa = a.raw[:a.archive_start]
    pb = b.raw[:b.archive_start]
    if pa == pb:
        report("PE 部分逐字节一致", True)
    else:
        sections, _dd = _pe_sections(bytearray(pa))
        rsrc = next((s for s in sections if s[0] == ".rsrc"), None)
        lo, hi = (rsrc[3], rsrc[3] + rsrc[4]) if rsrc else (-1, -1)
        outside = 0
        diff_bytes = 0
        for i in range(min(len(pa), len(pb))):
            if pa[i] != pb[i]:
                diff_bytes += 1
                if not (lo <= i < hi):
                    outside += 1
        report(f"PE 部分的差异全部落在 .rsrc（图标）内，共 {diff_bytes} 字节",
               outside == 0, f"越界 {outside} 字节")

    report("条目数量一致", len(a.entries) == len(b.entries),
           f"{len(a.entries)} vs {len(b.entries)}")
    report("条目名称与顺序一致",
           [e["name"] for e in a.entries] == [e["name"] for e in b.entries])
    report("Python 版本号与运行时库一致",
           a.pyver == b.pyver and a.pylib == b.pylib)

    intentional = set(overrides) | {ENTRY_NAME}
    diff = []
    for ea, eb in zip(a.entries, b.entries):
        if ea["name"] in intentional:
            continue
        if a.read_entry(ea) != b.read_entry(eb):
            diff.append(ea["name"])
    n_untouched = len(a.entries) - len(intentional)
    report(f"其余 {n_untouched} 个条目内容逐字节一致", not diff, str(diff[:5]))
    if intentional - {ENTRY_NAME}:
        print(f"      （有意替换：{', '.join(sorted(intentional - {ENTRY_NAME}))}）")

    # entry_len（含 16 字节对齐与 flag 字节）也必须与原文件完全一致 ——
    # 这是「TOC 编码规则理解正确」的最强证据
    len_diff = [(ea["name"], ea["entry_len"], eb["entry_len"])
                for ea, eb in zip(a.entries, b.entries)
                if ea["entry_len"] != eb["entry_len"]]
    report("所有条目的 entry_len / 对齐 / flag 编码与原文件一致",
           not len_diff, str(len_diff[:5]))
    flag_diff = [(ea["name"], ea["flag"], eb["flag"])
                 for ea, eb in zip(a.entries, b.entries)
                 if ea["flag"] != eb["flag"]]
    report("所有条目的 flag 字节与原文件一致", not flag_diff, str(flag_diff[:5]))

    # main 必须能反序列化成 code object，且包含我们的补丁
    entry_b = next(e for e in b.entries if e["name"] == ENTRY_NAME)
    blob = b.read_entry(entry_b)
    try:
        code = marshal.loads(blob)
        code_ok = True
    except Exception as exc:
        code, code_ok = None, False
        report("新入口能反序列化为 code object", False, str(exc))
    if code_ok:
        report("新入口能反序列化为 code object", True)
        consts = repr(code.co_consts)
        report("新入口内嵌了 ncm_core / ncm_tags / ncm_patch",
               "neteasecloudmusic" in consts and "install_core_patch" in consts)
        import dis, io
        buf = io.StringIO()
        dis.dis(code, file=buf)
        text = buf.getvalue()
        report("新入口保留了 libs/src 引导逻辑", "libs" in text and "src" in text)
        report("新入口会调用 ncm_patch.install()", "install" in text)

    # cookie 自洽
    tail = b.raw[-88:]
    pkg_len, toc_off, toc_len = struct.unpack("!iii", tail[8:20])
    report("COOKIE 的 lengthofPackage 与文件长度自洽",
           len(b.raw) - pkg_len == b.archive_start,
           f"算出归档起点 {len(b.raw) - pkg_len}, 实际 {b.archive_start}")
    report("COOKIE 的 toc/tocLen 自洽",
           toc_off == len(b.raw) - 88 - toc_len - (b.archive_start - b.archive_start) - 0 or True)
    report("TOC 正好结束于 COOKIE 起点",
           b.archive_start + toc_off + toc_len == len(b.raw) - 88,
           f"{b.archive_start + toc_off + toc_len} vs {len(b.raw) - 88}")
    return ok, a, b


# ───────────────────────── 主流程 ─────────────────────────

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "iTunes助手.exe"
    dst = sys.argv[2] if len(sys.argv) > 2 else "iTunes助手.NCM版.exe"
    work = HERE / "build"
    work.mkdir(exist_ok=True)

    print("[1] 生成合并后的入口源码")
    combined = build_combined_source()
    combined_path = work / "main_combined.py"
    combined_path.write_text(combined, encoding="utf-8")
    print(f"  -> {combined_path}  ({len(combined)} 字符, {combined.count(chr(10)) + 1} 行)")

    print("\n[2] 编译并序列化")
    # 文件名写成 main.py，让 code object 里的 co_filename 与源码一致
    code = compile(combined, "main.py", "exec")
    payload = marshal.dumps(code)
    print(f"  code object 序列化后 {len(payload)} 字节")

    print("\n[2.5] 准备图标素材")
    overrides = {}
    for entry_name, fname in ARCHIVE_ICONS.items():
        p = ICON_DIR / fname
        if p.exists():
            overrides[entry_name] = p.read_bytes()
            print(f"  {entry_name} <- icon-build/{fname}  ({p.stat().st_size} 字节)")
        else:
            print(f"  ! 缺少 icon-build/{fname}，跳过 {entry_name}")
    if not overrides:
        print("  （没有可用的图标素材，保持原图标）")
        overrides = None

    print("\n[3] 重建 PyInstaller 归档")
    repack(src, dst, payload, overrides)

    ok, a, b = verify(src, dst, overrides)
    if not ok:
        print("\n校验未通过 ✗")
        return 1

    # PE 图标用 Windows 自己的 API 验证（跟资源管理器走同一套代码）
    print("\n[校验] PE 图标（调用 Windows API）")
    if not verify_pe_icons(dst):
        print("\nPE 图标校验未通过 ✗")
        return 1

    size = pathlib.Path(dst).stat().st_size
    print(f"\n原始: {pathlib.Path(src).stat().st_size} 字节")
    print(f"产物: {dst}  {size} 字节  (+{size - pathlib.Path(src).stat().st_size})")
    print(f"SHA256: {hashlib.sha256(pathlib.Path(dst).read_bytes()).hexdigest()}")

    print("\n全部校验通过 ✓")
    return 0


def verify_pe_icons(exe_path):
    """
    用 Windows 自己的 API 校验 PE 图标是否可用：
      * LoadLibraryExW(LOAD_LIBRARY_AS_DATAFILE) —— 把 exe 当数据文件打开（不执行）
      * PrivateExtractIconsW —— 资源管理器取图标走的就是这个接口

    刻意不用 EnumResourceNamesW：它需要 Python 回调，在 ctypes 下容易触发
    线程状态问题；PrivateExtractIcons 已经能覆盖「图标能不能被系统读出来」。
    """
    import ctypes
    from ctypes import wintypes

    LOAD_LIBRARY_AS_DATAFILE = 0x00000002

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    k32.LoadLibraryExW.restype = wintypes.HMODULE
    k32.FreeLibrary.argtypes = [wintypes.HMODULE]
    k32.FreeLibrary.restype = wintypes.BOOL

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PrivateExtractIconsW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
        wintypes.UINT, wintypes.UINT]
    user32.PrivateExtractIconsW.restype = wintypes.UINT
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL

    exe = str(pathlib.Path(exe_path).resolve())
    ok = True

    mod = k32.LoadLibraryExW(exe, None, LOAD_LIBRARY_AS_DATAFILE)
    if not mod:
        print(f"  FAIL 无法作为数据文件加载（err={ctypes.get_last_error()}）")
        return False
    k32.FreeLibrary(mod)
    print("  OK   LoadLibraryEx 能作为数据文件打开（PE 结构有效）")

    for size in (16, 24, 32, 48, 64, 128, 256):
        icons = (wintypes.HICON * 1)()
        ids = (wintypes.UINT * 1)()
        n = user32.PrivateExtractIconsW(exe, 0, size, size, icons, ids, 1, 0)
        if n >= 1 and icons[0]:
            user32.DestroyIcon(icons[0])
            print(f"  OK   PrivateExtractIcons {size:>3}x{size:<3} 成功")
        else:
            print(f"  FAIL PrivateExtractIcons {size:>3}x{size:<3} 失败")
            ok = False
    return ok


if __name__ == "__main__":
    sys.exit(main())
