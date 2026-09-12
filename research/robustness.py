# -*- coding: utf-8 -*-
"""TSMOM 穩健性檢查：回看期敏感度 × 兩個資料源 × 前後半段分割。

會讓一個策略被否決的兩種結果：
  * 敏感度呈雙峰而非高原——鄰近參數塌陷代表帶運氣成分。
  * 後半段輸給買進持有——我們要下注的是未來，不是樣本前半。

用法：python robustness.py
"""
import sys
from gold_data import fetch, ymd
from engine import run, buy_hold, sig_tsmom

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

LBS = [1, 2, 3, 4, 6, 8, 9, 10, 12, 14, 15, 18, 21, 24]
SRC = [(s, fetch(s)) for s in ["GC=F", "GLD"]]

for name, bars in SRC:
    yrs = (bars[-1]["t"] - bars[0]["t"]) / 864e5 / 365
    print("%-6s %s ~ %s  %d 根  %.1f 年"
          % (name, ymd(bars[0]["t"]), ymd(bars[-1]["t"]), len(bars), yrs))
print()

for name, bars in SRC:
    b = buy_hold(bars)
    print("=== %s   買進持有 %.1f%% / 回撤 %.1f%% / 報酬÷回撤 %.2f ==="
          % (name, b["ret"], b["mdd"], b["rr"]))
    print("%6s | %28s | %28s"
          % ("回看", "只做多  報酬 / 回撤 / 筆 / 比", "多空    報酬 / 回撤 / 筆 / 比"))
    print("-" * 72)
    for lb in LBS:
        a = run(bars, sig_tsmom(bars, lb, False))
        s = run(bars, sig_tsmom(bars, lb, True))
        mark = " <<標準設定" if lb == 12 else ""
        print("%4d月 | %9.1f%% %6.1f%% %4d %5.2f | %9.1f%% %6.1f%% %4d %5.2f%s"
              % (lb, a["ret"], a["mdd"], a["n"], a["rr"],
                 s["ret"], s["mdd"], s["n"], s["rr"], mark))
    print()

print("=== 樣本分割：前半 / 後半（只做多）===")
for name, bars in SRC:
    N = len(bars)
    mid = N // 2
    print("%s  分割點 %s" % (name, ymd(bars[mid]["t"])))
    print("%6s | %22s | %22s" % ("回看", "前半 報酬/回撤/比", "後半 報酬/回撤/比"))
    for lb in [6, 9, 12, 15, 18]:
        a = run(bars, sig_tsmom(bars, lb, False), lo=0, hi=mid)
        c = run(bars, sig_tsmom(bars, lb, False), lo=mid, hi=N)
        print("%4d月 | %8.1f%% %6.1f%% %5.2f | %8.1f%% %6.1f%% %5.2f"
              % (lb, a["ret"], a["mdd"], a["rr"], c["ret"], c["mdd"], c["rr"]))
    ba, bc = buy_hold(bars, 0, mid), buy_hold(bars, mid, N)
    print("  全抱 | %8.1f%% %6.1f%% %5.2f | %8.1f%% %6.1f%% %5.2f\n"
          % (ba["ret"], ba["mdd"], ba["rr"], bc["ret"], bc["mdd"], bc["rr"]))
