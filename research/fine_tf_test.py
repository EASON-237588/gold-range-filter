# -*- coding: utf-8 -*-
"""1/3/5 分鐘：把 15 分那套完整跑一次，確認短週期的趨勢。

15 分六年的結果：只做多最好 1.30（回看 600 小時），加空單一律扣分（160 組全負），
買進持有 4.08。這支要回答的是：往更細的週期走，這兩件事會不會改變。

資料量很大（1 分六年 315 萬根），所以每個週期只跑必要的組合：
  只做多 × 四個回看長度      找該週期的最佳只做多設定
  最佳只做多 + 三種空單規則  確認空單價值在該週期是否仍為負

回看長度一律用小時指定，跨週期才可比。
"""
import sys, time
import paxg_data
from dual_engine import backtest_asym, buy_hold, atr, dir_donchian

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

YEARS = 6.15
LONG = {"mode": "average", "step": 1.0, "stop_atr": 3.0, "stop_pct": None}
LOOKBACKS = [400, 600, 800, 1200]
TFS = [("5m", 5), ("3m", 3), ("1m", 1)]


def main():
    for tf, mins in TFS:
        need = int(YEARS * 365 * 24 * 60 / mins) + 100
        t0 = time.time()
        print("\n######## %s：抓取中（約需 %s 根）..." % (tf, format(need, ",")))
        sys.stdout.flush()
        bars = paxg_data.fetch("PAXGUSDT", tf, max_bars=need, verbose=False)
        print("  %s 根・%.0f 秒" % (format(len(bars), ","), time.time() - t0))
        sys.stdout.flush()

        A = atr(bars, 14)
        bh = buy_hold(bars)
        print("  買進持有 %+.1f%%／回撤 %.1f%%（報/撤 %.2f）"
              % (bh["net"], bh["mdd"], bh["net"] / bh["mdd"]))
        print("  %-10s %8s %7s %6s %5s %7s" % ("回看", "報酬", "回撤", "報/撤", "筆數", "持倉天"))

        best = None
        for H in LOOKBACKS:
            n = int(H * 60 / mins)
            if n > len(bars) // 4:
                continue
            t1 = time.time()
            d = dir_donchian(bars, n, max(10, n // 3))
            r = backtest_asym(bars, d, LONG, {"enabled": False}, atr_arr=A)
            rr = r["net"] / r["mdd"] if r["mdd"] else 0
            print("  %-10s %+7.1f%% %6.1f%% %6.2f %5d %7.1f   (%.0f 秒)"
                  % ("%d 小時" % H, r["net"], r["mdd"], rr, r["total"],
                     (r["avg_held"] or 0) * mins / 1440.0, time.time() - t1))
            sys.stdout.flush()
            if best is None or rr > best[0]:
                best = (rr, H, n, d, r)

        if best is None:
            continue
        rr, H, n, d, rl = best
        print("  → 最佳只做多：回看 %d 小時，報/撤 %.2f" % (H, rr))
        print("  -- 在這個設定上加空單 --")
        for smode, sstep, spct in [("pyramid", 1.0, 2.0), ("pyramid", 0.5, 1.0),
                                   ("single", 1.0, 2.0), ("average", 1.0, 3.0)]:
            r = backtest_asym(bars, d, LONG,
                              {"mode": smode, "step": sstep,
                               "stop_atr": None, "stop_pct": spct}, atr_arr=A)
            print("     %-8s step%.1f stop%.0f%% → %+7.1f%%（空單價值 %+.1f%%）"
                  % (smode, sstep, spct, r["net"], r["net"] - rl["net"]))
            sys.stdout.flush()


if __name__ == "__main__":
    main()
