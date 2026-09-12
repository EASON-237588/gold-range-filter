# -*- coding: utf-8 -*-
"""現成策略在 GC=F 26 年上的比較（含依市況分段）。

用法：python compare_strategies.py [GC=F|GLD]
"""
import sys
from gold_data import fetch, ymd, describe
from engine import run, buy_hold, sig_ma, sig_tsmom, sig_donchian

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SYM = sys.argv[1] if len(sys.argv) > 1 else "GC=F"
bars = fetch(SYM)
T = [b["t"] for b in bars]

print(describe(bars, SYM) + "\n")

res = [buy_hold(bars),
       run(bars, sig_tsmom(bars, 12, False), "TSMOM12月檢 只做多"),
       run(bars, sig_tsmom(bars, 12, True),  "TSMOM12月檢 多空"),
       run(bars, sig_ma(bars, 210, False),   "10月均線 只做多(Faber原版)"),
       run(bars, sig_ma(bars, 200, False),   "200MA月檢 只做多"),
       run(bars, sig_ma(bars, 200, True),    "200MA月檢 多空"),
       run(bars, sig_donchian(bars, 20, 10, False),  "Donchian20/10 只做多"),
       run(bars, sig_donchian(bars, 55, 20, False),  "Donchian55/20 只做多"),
       run(bars, sig_donchian(bars, 100, 50, False), "Donchian100/50 只做多")]

print("%-28s %10s %8s %6s %7s %6s %6s %9s"
      % ("策略", "複利報酬", "最大回撤", "筆數", "月頻", "PF", "勝率", "報酬/回撤"))
print("-" * 92)
for r in res:
    print("%-28s %9.1f%% %7.1f%% %6s %7s %6s %6s %9.2f" % (
        r["name"], r["ret"], r["mdd"], r["n"],
        "%.1f" % r["月頻"] if r["月頻"] else "—",
        "%.2f" % r["pf"] if r["pf"] else "—",
        "%.0f%%" % r["勝率"] if r["勝率"] else "—",
        r["rr"]))

# 依實際市況分段，而不是等分——等分會把空頭段稀釋掉
SEGS = [("2000-2011多頭", "2000-08-30", "2011-09-05"),
        ("2011-2015空頭", "2011-09-05", "2015-12-17"),
        ("2015-2019盤整", "2015-12-17", "2019-06-01"),
        ("2019-2026多頭", "2019-06-01", "2026-09-11")]


def idx_of(d):
    for i, t in enumerate(T):
        if ymd(t) >= d:
            return i
    return len(T) - 1


print("\n分段報酬（複利 %）")
hdr = "%-28s" % "策略"
for s in SEGS:
    hdr += " %14s" % s[0]
print(hdr)
print("-" * 92)
for r in res:
    line = "%-28s" % r["name"]
    cv = r["curve"]
    for _, a, b in SEGS:
        ia, ib = min(idx_of(a), len(cv) - 1), min(idx_of(b), len(cv) - 1)
        line += " %13.1f%%" % (((cv[ib] / cv[ia]) - 1) * 100 if cv[ia] else 0)
    print(line)
