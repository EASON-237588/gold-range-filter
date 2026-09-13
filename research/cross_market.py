# -*- coding: utf-8 -*-
"""跨市場交叉比對：黃金 / 美元指數 / 原油。

評估標準是**風險來臨時誰賠得少**，不是誰賺得多：
  - 最大回撤
  - 各市場自己最慘那段的損失
  - 下檔捕捉率 = 策略在該段的損失 ÷ 買進持有的損失（越低越好）

11 分與 15 分無法跨市場（Yahoo 的分鐘資料只給幾十天），所以 RF 一律用日線，
參數固定 100/23 與 25/8，**不針對各市場調參**——調了就只是過擬合。

用法：python cross_market.py
"""
import sys
import engine
from engine import run_scaled
from gold_data import fetch, ymd
from rangefilter import compute, to_position
from new_indicators import sig_breadth_x_density

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

engine.COST = 0.001

MARKETS = [("黃金", "GC=F"), ("美元指數", "DX-Y.NYB"), ("原油", "CL=F")]


def worst_window(bars, lo=0, hi=None):
    """找買進持有最慘的一段（由高點到其後最低點），回傳 (起, 迄, 跌幅%)。"""
    C = [b["c"] for b in bars]
    hi = len(C) if hi is None else hi
    peak_i, peak, worst = lo, C[lo], (lo, lo, 0.0)
    for i in range(lo, hi):
        if C[i] > peak:
            peak, peak_i = C[i], i
        dd = (C[i] / peak - 1) * 100
        if dd < worst[2]:
            worst = (peak_i, i, dd)
    return worst


for label, sym in MARKETS:
    try:
        bars = fetch(sym)
    except Exception as e:
        print("%s (%s) 抓取失敗：%s\n" % (label, sym, str(e)[:60]))
        continue
    N = len(bars)
    T = [b["t"] for b in bars]
    C = [b["c"] for b in bars]

    R1 = compute(bars, per=100, mult=23, src_mode="hl2")
    R2 = compute(bars, per=25, mult=8, src_mode="hl2")
    defs = [
        ("買進持有", [1.0] * N),
        ("RF100/23 只做多", to_position(R1["sig"], True)),
        ("RF100/23 多空", to_position(R1["sig"], False)),
        ("RF25/8 只做多", to_position(R2["sig"], True)),
        ("RF25/8 多空", to_position(R2["sig"], False)),
        ("廣度 × 密度", sig_breadth_x_density(bars)),
    ]

    a, b, dd = worst_window(bars)
    print("=" * 92)
    print("%s (%s)　%s ~ %s　%d 根" % (label, sym, ymd(T[0]), ymd(T[-1]), N))
    print("最慘一段：%s ~ %s　買進持有 %.1f%%" % (ymd(T[a]), ymd(T[b]), dd))
    print("=" * 92)
    print("%-18s %10s %10s %14s %12s" % ("", "全期報酬", "最大回撤", "最慘段報酬", "下檔捕捉率"))
    print("-" * 92)

    base_loss = None
    rows = []
    for nm, sig in defs:
        r = run_scaled(bars, sig, nm)
        w = run_scaled(bars, sig, lo=a, hi=b + 1)
        if nm == "買進持有":
            base_loss = w["ret"]
        cap = (w["ret"] / base_loss * 100) if base_loss and base_loss < 0 else None
        rows.append((nm, r, w, cap))
        print("%-18s %9.1f%% %9.1f%% %13.1f%% %11s"
              % (nm, r["ret"], r["mdd"], w["ret"],
                 "%.0f%%" % cap if cap is not None else "—"))
    print()
