# -*- coding: utf-8 -*-
"""
prepare_repo.py —— 把 itunes-helper/ 整理成可以直接 git init 的仓库

做四件事：
  1. 把要展示的截图收进 docs/
  2. 写出 .gitignore（把从原版 exe 派生出来的一切、测试产物、编译产物都挡在外面）
  3. 生成 README.md（GitHub 首页）和 LICENSE
  4. 列出「最终会被提交的文件」，方便在 git init 之前先肉眼核对一遍
"""
import pathlib
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
DOCS = HERE / "docs"
DOCS.mkdir(exist_ok=True)

# ── 1. 截图 ──
SHOTS = {
    "v3-playing.png": "screenshot-main.png",
    "v4-dark-playing.png": "screenshot-player-dark.png",
    "v5-volume-light.png": "screenshot-volume-light.png",
    "v5-volume-dark.png": "screenshot-volume-dark.png",
    "drop-shot.png": "screenshot-list.png",
}
for src, dst in SHOTS.items():
    s = HERE / src
    if s.exists():
        shutil.copy2(s, DOCS / dst)
        print(f"  docs/{dst}  <- {src}  ({s.stat().st_size / 1024:.0f} KB)")
    else:
        print(f"  ! 缺少 {src}，跳过")

# ── 2. .gitignore ──
GITIGNORE = """\
# ============================================================
#  基础版本 / 集成版的 exe
#
#  二进制不进 git 历史：36 MB 的文件一旦提交，以后每次改动都会
#  再存一份，仓库会迅速膨胀。成品放在 GitHub Releases 里。
# ============================================================
/iTunes助手.exe
/iTunes助手.NCM版.exe

# PyInstaller 归档解包 / 重建出来的运行时目录
/extracted/
/runtime/
/assets/
/build/
/meipass/
/disasm/

# ============================================================
#  测试与调试产物
# ============================================================
/e2e/
/e2e-fixtures/
/playtmp/
/real-samples/
/mkdirtest/
/modetest/
/demoshot/
/droptest/
/v2test/
/v3test/
/verifyicons/
/voltestcache/

# 注册表 / 环境探针留下的临时东西
/env-scan.txt

# ============================================================
#  生成物（图标都可以用脚本重新生成）
# ============================================================
/icon-build/
/player-icons/
__pycache__/
*.pyc

# ============================================================
#  报告与截图
#  说明：仓库里只保留 docs/ 下那几张 README 要用的截图
# ============================================================
*.txt
!首次运行-安装到桌面.说明.txt

*.png
!/icon-source.png
!/icon-src/*.png
!/vol-src/*.png
!/docs/*.png

bisect-*.qss
aes_vectors.json
*.dis.txt

# ============================================================
#  编辑器 / 系统
# ============================================================
.vscode/
.idea/
Thumbs.db
desktop.ini

# 本脚本自己生成的清单
/repo-file-list.txt
"""

(HERE / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
print(f"\n  .gitignore  {len(GITIGNORE)} 字节")


# ── 3. 模拟 gitignore，列出最终会被提交的文件 ──

def load_ignores():
    rules = []
    for line in GITIGNORE.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        neg = line.startswith("!")
        if neg:
            line = line[1:]
        rules.append((neg, line))
    return rules


RULES = load_ignores()


def _glob(pat, name):
    """只支持 * 和 ?，够用了。"""
    regex = ""
    for ch in pat:
        if ch == "*":
            regex += ".*"
        elif ch == "?":
            regex += "."
        else:
            regex += re.escape(ch)
    return re.fullmatch(regex, name) is not None


def ignored(rel):
    """
    rel：正斜杠分隔、不带前导 ./
    规则语义按 gitignore：
      /x/   锚定在仓库根的目录，命中它自己及下面所有内容
      x/    任意层级的同名目录
      /x    锚定在仓库根的文件/路径
      *.x   任意层级的文件名
    """
    state = False
    parts = rel.split("/")
    for neg, raw in RULES:
        anchored = raw.startswith("/")
        pat = raw.lstrip("/")
        hit = False
        if pat.endswith("/"):
            d = pat.rstrip("/")
            if anchored:
                hit = rel == d or rel.startswith(d + "/")
            else:
                hit = d in parts[:-1] or parts[-1] == d
        elif "/" in pat:
            hit = _glob(pat, rel)
        else:
            hit = any(_glob(pat, part) for part in parts)
        if hit:
            state = not neg
    return state


tracked = []
for p in sorted(HERE.rglob("*")):
    if not p.is_file():
        continue
    rel = p.relative_to(HERE).as_posix()
    if rel.startswith(".git/"):
        continue
    if not ignored(rel):
        tracked.append((rel, p.stat().st_size))

total = sum(s for _n, s in tracked)
print(f"\n  最终会被提交：{len(tracked)} 个文件，合计 {total / 1024:.0f} KB\n")

groups = {}
for name, size in tracked:
    top = name.split("/")[0] if "/" in name else "(根目录文件)"
    groups.setdefault(top, []).append((name, size))
for top in sorted(groups):
    items = groups[top]
    size = sum(s for _n, s in items)
    print(f"  {top:<20} {len(items):>3} 个  {size / 1024:>7.1f} KB")
    if top == "(根目录文件)":
        for name, s in sorted(items):
            print(f"        {name:<44} {s / 1024:>7.1f} KB")

(HERE / "repo-file-list.txt").write_text(
    "\n".join(f"{s:>10}  {n}" for n, s in tracked), encoding="utf-8")
print(f"\n  完整清单 -> repo-file-list.txt")
