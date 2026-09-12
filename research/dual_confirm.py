# -*- coding: utf-8 -*-
"""雙確認防護 vs 既有策略。

所有策略一律走 run_scaled（逐日權益、成本按部位變化量），內部可比。
重點不是總報酬，而是三件事：
  1. 後半段（近十年）還贏不贏得了買進持有 —— 這是 TSMOM 倒下的地方
  2. 換 GLD 重不重現
  3. 2011-2015 大空頭擋不擋得住

用法：python dual_confirm.py
"""
import sys
from gold_data import fetch, ymd
from engine import (run_scaled, sig_ma, sig_tsmom, sig_dual_confirm)

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def build(bars):
    N = len(bars)
    hold = [1.0] * N
    return [
        ("買進持有",              hold),
        ("雙確認 AND",            sig_dual_confirm(bars, mode="and")),
        ("雙確認 分級0/50/100",    sig_dual_confirm(bars, mode="scale")),
        ("雙確認 OR",             sig_dual_confirm(bars, mode="or")),
        ("TSMOM12 只做多",        sig_tsmom(bars, 12, False)),
        ("200MA月檢 只做多",       sig_ma(bars, 200, False)),
    ]


def show(title, bars, lo=0, hi=None):
    print(title)
    print("%-22s %10s %8s %6s %8s %9s" % ("策略", "複利報酬", "最大回撤", "換手", "月頻", "報酬/回撤"))
    print("-" * 70)
    out = []
    for name, sig in build(bars):
        r = run_scaled(bars, sig, name, lo, hi)
        out.append(r)
        print("%-22s %9.1f%% %7.1f%% %6d %8s %9.2f"
              % (name, r["ret"], r["mdd"], r["n"],
                 "%.1f" % r["月頻"] if r["月頻"] else "—", r["rr"]))
    print()
    return out


for sym in ["GC=F", "GLD"]:
    bars = fetch(sym)
    T = [b["t"] for b in bars]
    N = len(bars)
    yrs = (T[-1] - T[0]) / 864e5 / 365
    show("=== %s 全期  %s ~ %s  %.1f 年 ===" % (sym, ymd(T[0]), ymd(T[-1]), yrs), bars)

    mid = N // 2
    show("--- %s 前半（%s 起）---" % (sym, ymd(T[0])), bars, 0, mid)
    show("--- %s 後半（%s 起）← 決定性的一段 ---" % (sym, ymd(T[mid])), bars, mid, N)

# 2011-2015 大空頭單獨看
bars = fetch("GC=F")
T = [b["t"] for b in bars]
def idx_of(d):
    for i, t in enumerate(T):
        if ymd(t) >= d:
            return i
    return len(T) - 1
show("=== GC=F 2011-09 ~ 2015-12 大空頭（全抱 -43.8%）===",
     bars, idx_of("2011-09-05"), idx_of("2015-12-17"))
