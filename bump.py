# -*- coding: utf-8 -*-
"""黃金即時儀表板 — 版本自動跳號

用法：
    python bump.py          小版號 +1（V1.01 -> V1.02 -> ... -> V1.99 -> V2.00）
    python bump.py major    大版號 +1，小版號歸零（V1.23 -> V2.00）
    python bump.py 1.05     直接指定版本

會同時：
  1. 把目前的 index.html 備份到 版本歷程/index_V<現版號>.html
  2. 改寫 index.html 裡的 const VERSION = "Vx.yy"

**跑這支的時機：改動做完、確認要定版的當下。**
備份存的是「現版號的最終內容」，所以順序是：改東西 → 確認 OK → bump。
反過來先 bump 再改，那個版號的封存檔會是空殼，改動會掛到下一版去。

2026-09-03 踩過一次：在 V1.02 底下加了螢光配色才跑 bump，
於是 index_V1.02.html 存到的是含螢光的版本，
使用者要「回復 1.02」時封存檔給不出正確內容，只能回頭翻 git。
封存檔是給不想碰 git 的人用的，內容對不上就失去意義。

版號字串只出現在 index.html 的 VERSION 常數，標題與說明面板都讀它。
"""
import io, os, re, sys, shutil

try:                                    # Windows 主控台預設 cp950，中文訊息會亂碼
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "index.html")
VERDIR = os.path.join(HERE, "版本歷程")
PAT = re.compile(r'(const VERSION = "V)(\d+)\.(\d+)(";)')


def main():
    s = io.open(SRC, encoding="utf-8").read()
    m = PAT.search(s)
    if not m:
        print('找不到版本字串 const VERSION = "Vx.yy"，請確認 index.html 未被改動格式')
        return 1

    cur_major, cur_minor = int(m.group(2)), int(m.group(3))
    cur = "V%d.%02d" % (cur_major, cur_minor)

    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if re.match(r"^\d+\.\d+$", arg):
        new_major, new_minor = [int(x) for x in arg.split(".")]
    elif arg == "major":
        new_major, new_minor = cur_major + 1, 0
    else:
        new_major, new_minor = cur_major, cur_minor + 1
        if new_minor > 99:
            new_major, new_minor = new_major + 1, 0
    new = "V%d.%02d" % (new_major, new_minor)

    if not os.path.isdir(VERDIR):
        os.makedirs(VERDIR)
    bak = os.path.join(VERDIR, "index_%s.html" % cur)
    if os.path.exists(bak):
        print("版本歷程/index_%s.html 已存在，沒有覆蓋。" % cur)
        print("若確定要重新封存這一版，先手動刪掉那個檔再跑一次。")
        return 1
    shutil.copy2(SRC, bak)

    s = PAT.sub(lambda x: x.group(1) + "%d.%02d" % (new_major, new_minor) + x.group(4), s, count=1)
    io.open(SRC, "w", encoding="utf-8").write(s)
    print("版本 %s -> %s" % (cur, new))
    print("舊版已封存：版本歷程/index_%s.html" % cur)
    return 0


if __name__ == "__main__":
    sys.exit(main())
