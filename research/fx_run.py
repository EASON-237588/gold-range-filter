# -*- coding: utf-8 -*-
"""EURUSD 第一輪：把黃金那套已驗證的架構搬到外匯。

沿用的前提（在黃金上驗證過，不重測）：
  多單逆勢攤平有效；順勢金字塔一致最差；回看長度用小時指定才跨週期可比。

外匯與加密的兩個關鍵差異：
  成本   Dukascopy 實測 EURUSD 平均點差 0.0023%，來回約 0.005%。
         加密是 0.23%，差 50 倍。這裡用 0.0075%／單趟（含一點滑價，比實測保守）。
  swap   持倉兩週約 10 個交易日，2% 年化 carry 約 0.08%——比點差大十幾倍。
         這七年半美歐利差變化極大（2019 約 2.4%、2021 近零、2023-24 逾 5%），
         寫死任何一個數字都會誤導，所以做成敏感度軸。

判準同前：報酬÷回撤 要贏過買進持有，且空單價值（多空 − 只做多）要為正。
"""
import sys, time
import numpy as np
import fx_data
from dual_engine import backtest_asym, buy_hold, atr, dir_donchian

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PAIR = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
SPREAD = 0.0075                      # % 單趟
LONG = {"mode": "average", "step": 1.0, "stop_atr": 3.0, "stop_pct": None}
OFF = {"enabled": False}
SHORT = {"mode": "pyramid", "step": 1.0, "stop_atr": None, "stop_pct": 0.5}
LOOKBACKS = [200, 400, 600, 800, 1200]
TFS = [10, 15, 30]


def main():
    m1 = fx_data.fetch_m1(PAIR, 8.0, verbose=False)
    print("%s・%s 根 1 分鐘・%s ~ %s"
          % (PAIR, format(len(m1), ","),
             time.strftime("%Y-%m-%d", time.gmtime(m1[0, 0] / 1000)),
             time.strftime("%Y-%m-%d", time.gmtime(m1[-1, 0] / 1000))))
    print("點差 %.4f%%／單趟・carry 先設 0（下面單獨做敏感度）\n" % SPREAD)

    best = []
    for k in TFS:
        bars = fx_data.aggregate(m1, k)
        A = atr(bars, 14)
        bh = buy_hold(bars)
        print("=== %d 分・%s 根・買進持有 %+.1f%%／回撤 %.1f%%（%.2f）==="
              % (k, format(len(bars), ","), bh["net"], bh["mdd"],
                 bh["net"] / bh["mdd"] if bh["mdd"] else 0))
        print("  %-8s │ %8s %7s %6s %5s %7s │ %8s %7s %6s │ %9s"
              % ("回看", "只做多", "回撤", "報/撤", "筆數", "持倉天",
                 "多空", "回撤", "報/撤", "空單價值"))
        for H in LOOKBACKS:
            n = int(H * 60 / k)
            if n > len(bars) // 4:
                continue
            d = dir_donchian(bars, n, max(10, n // 3))
            rl = backtest_asym(bars, d, LONG, OFF, cost=SPREAD, atr_arr=A, bar_minutes=k)
            rb = backtest_asym(bars, d, LONG, SHORT, cost=SPREAD, atr_arr=A, bar_minutes=k)
            if rl["total"] < 5:
                continue
            rrl = rl["net"] / rl["mdd"] if rl["mdd"] else 0
            rrb = rb["net"] / rb["mdd"] if rb["mdd"] else 0
            print("  %-8s │ %+7.1f%% %6.1f%% %6.2f %5d %7.1f │ %+7.1f%% %6.1f%% %6.2f │ %+8.1f%%%s"
                  % ("%d 小時" % H, rl["net"], rl["mdd"], rrl, rl["total"],
                     (rl["avg_held"] or 0) * k / 1440.0,
                     rb["net"], rb["mdd"], rrb, rb["net"] - rl["net"],
                     " ←" if rb["net"] > rl["net"] else ""))
            best.append((rrl, k, H, rl, rb, bars, A, d, bh))
        print()

    if not best:
        print("沒有結果")
        return
    best.sort(key=lambda x: -x[0])
    rr, k, H, rl, rb, bars, A, d, bh = best[0]
    print("=== 最佳只做多：%d 分・回看 %d 小時（報/撤 %.2f）的 carry 敏感度 ===" % (k, H, rr))
    print("  年化 carry 是外匯的主要成本，這七年半區間內實際在 0~5% 之間變動")
    print("  %-10s │ %8s %7s %6s │ %8s %7s %6s"
          % ("年化 carry", "只做多", "回撤", "報/撤", "多空", "回撤", "報/撤"))
    for c in [0.0, 1.0, 2.0, 3.0, 5.0]:
        a = backtest_asym(bars, d, LONG, OFF, cost=SPREAD, atr_arr=A,
                          carry_annual=c, bar_minutes=k)
        b = backtest_asym(bars, d, LONG, SHORT, cost=SPREAD, atr_arr=A,
                          carry_annual=c, bar_minutes=k)
        print("  %-10s │ %+7.1f%% %6.1f%% %6.2f │ %+7.1f%% %6.1f%% %6.2f"
              % ("%.1f%%" % c, a["net"], a["mdd"], a["net"] / a["mdd"] if a["mdd"] else 0,
                 b["net"], b["mdd"], b["net"] / b["mdd"] if b["mdd"] else 0))
    print("\n  買進持有（同期、無 carry）%+.1f%%／回撤 %.1f%%（%.2f）"
          % (bh["net"], bh["mdd"], bh["net"] / bh["mdd"] if bh["mdd"] else 0))


if __name__ == "__main__":
    main()
