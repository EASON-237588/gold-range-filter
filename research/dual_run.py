# -*- coding: utf-8 -*-
"""第一輪：確認引擎跑得動，並看三種部位模式的形狀差異。

這一輪不掃參數、不挑最佳解，只回答一件事：
分批加倉到底改變了什麼——是降低了單筆最大虧損，還是放大了它。
"""
import sys, time
import paxg_data
from dual_engine import backtest, buy_hold, dir_donchian, dir_ema_slope

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DAYS = 300


def load(tf, mins):
    need = int(DAYS * 24 * 60 / mins) + 10
    bars = paxg_data.fetch("PAXGUSDT", tf, max_bars=need)
    cut = bars[-1]["t"] - DAYS * 86400 * 1000
    return [b for b in bars if b["t"] >= cut]


def row(name, r, bh):
    if r["total"] == 0:
        print("  %-22s 無交易" % name)
        return
    print("  %-22s %8.1f%% %7.1f%% %6.2f %5d筆 %5.1f%% %6s "
          "多%3d/%7.1f%% 空%3d/%7.1f%% 最慘%7.1f%% 停損%3d 均段%4.1f 均持%6.1f根"
          % (name, r["net"], r["mdd"], (r["net"] / r["mdd"] if r["mdd"] else 0),
             r["total"], r["win"] or 0,
             ("%.2f" % r["pf"]) if r["pf"] else "—",
             r["long_n"], r["long_ret"], r["short_n"], r["short_ret"],
             r["worst"] or 0, r["stops"], r["avg_segs"] or 0, r["avg_held"] or 0))


def main():
    for tf, mins in [("4h", 240), ("1h", 60), ("15m", 15)]:
        bars = load(tf, mins)
        bh = buy_hold(bars)
        d0 = time.strftime("%Y-%m-%d", time.gmtime(bars[0]["t"] / 1000))
        d1 = time.strftime("%Y-%m-%d", time.gmtime(bars[-1]["t"] / 1000))
        print("\n=== %s・%s 根・%s ~ %s ===" % (tf, format(len(bars), ","), d0, d1))
        print("  買進持有            %8.1f%% %7.1f%% %6.2f"
              % (bh["net"], bh["mdd"], bh["net"] / bh["mdd"]))
        print("  %-22s %8s %7s %6s %5s %6s %6s"
              % ("策略", "淨報酬", "回撤", "報/撤", "筆數", "勝率", "獲利因子"))

        for dname, dfn in [("Donchian55/20", lambda b: dir_donchian(b, 55, 20)),
                           ("EMA20/60±0.25ATR", lambda b: dir_ema_slope(b, 20, 60))]:
            d = dfn(bars)
            nz = sum(1 for x in d if x != 0) / float(len(d)) * 100
            print("  -- %s（在場時間 %.0f%%）" % (dname, nz))
            for mode, label in [("single", "不分批"), ("pyramid", "順勢金字塔"),
                                ("average", "逆勢攤平")]:
                r = backtest(bars, d, mode=mode, segs=5, step_atr=1.0, stop_atr=3.0)
                row(label, r, bh)


if __name__ == "__main__":
    main()
