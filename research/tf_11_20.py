# -*- coding: utf-8 -*-
"""11~20 分鐘，只做多，六年 PAXG。

先前只測了 15 分（1.30）與 20 分（僅 300 天樣本 1.01），中間的週期沒逐一跑過。
11 分是儀表板現用的週期，值得放進同一張表比較。

非原生週期（11/13/14/17/18/19）由 1 分鐘聚合，六年 1 分鐘資料已在快取裡。
回看長度用小時指定，跨週期才可比。
"""
import sys, time
import paxg_data
from dual_engine import backtest_asym, buy_hold, atr, dir_donchian
from subminute_sweep import aggregate

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LONG = {"mode": "average", "step": 1.0, "stop_atr": 3.0, "stop_pct": None}
OFF = {"enabled": False}
TFS = [11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
LOOKBACKS = [400, 600, 800, 1200]


def main():
    m1 = paxg_data.fetch("PAXGUSDT", "1m", max_bars=3300000, verbose=False)
    print("PAXG 1 分鐘 %s 根・%s ~ %s"
          % (format(len(m1), ","),
             time.strftime("%Y-%m-%d", time.gmtime(m1[0]["t"] / 1000)),
             time.strftime("%Y-%m-%d", time.gmtime(m1[-1]["t"] / 1000))))
    bh = buy_hold(m1)
    print("買進持有 %+.1f%%／回撤 %.1f%%（報/撤 %.2f）\n"
          % (bh["net"], bh["mdd"], bh["net"] / bh["mdd"]))
    print("只做多・逆勢攤平・step 1 ATR・stop 3 ATR・成本 0.115%／單趟")
    print("%-6s %-10s │ %8s %7s %6s %5s %7s"
          % ("週期", "回看", "報酬", "回撤", "報/撤", "筆數", "持倉天"))

    rows = []
    for k in TFS:
        bars = aggregate(m1, k)
        A = atr(bars, 14)
        best = None
        for H in LOOKBACKS:
            n = int(H * 60 / k)
            if n > len(bars) // 4:
                continue
            d = dir_donchian(bars, n, max(10, n // 3))
            r = backtest_asym(bars, d, LONG, OFF, atr_arr=A, bar_minutes=k)
            if r["total"] < 5:
                continue
            rr = r["net"] / r["mdd"] if r["mdd"] else 0
            if best is None or rr > best[0]:
                best = (rr, H, r)
        if best is None:
            continue
        rr, H, r = best
        print("%-6s %-10s │ %+7.1f%% %6.1f%% %6.2f %5d %7.1f"
              % ("%d 分" % k, "%d 小時" % H, r["net"], r["mdd"], rr,
                 r["total"], (r["avg_held"] or 0) * k / 1440.0))
        sys.stdout.flush()
        rows.append((rr, k, H, r))

    print()
    rows.sort(reverse=True, key=lambda x: x[0])
    print("排序：", "、".join("%d分 %.2f" % (k, rr) for rr, k, H, r in rows))
    if rows:
        rr, k, H, r = rows[0]
        print("最好：%d 分・回看 %d 小時・報/撤 %.2f（買進持有 %.2f）"
              % (k, H, rr, bh["net"] / bh["mdd"]))


if __name__ == "__main__":
    main()
