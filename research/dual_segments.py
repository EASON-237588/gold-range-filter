# -*- coding: utf-8 -*-
"""六年分段：攤平在真正的趨勢行情裡會不會崩。

上一輪（最近 300 天）逆勢攤平的報酬÷回撤 0.91 大勝買進持有 0.23，但那 300 天
黃金只漲 6.6%，是震盪市——攤平在震盪市天生有利，價格來回擺盪正好讓它低接高出。
而且攤平會把平均成本拉近現價，讓硬停損更難觸發：停損次數從 27 降到 6，
可以解讀成「保護有效」，也可以解讀成「保護失靈、扛得更久」，單一震盪樣本分不出來。

所以這支按**日曆年**切段跑，每段獨立計算，並印出該段買進持有的漲跌與回撤當市況標籤。
要看的不是哪一段最賺，是**攤平在單邊段有沒有崩**。

分段用日曆年而不是固定根數：不同週期的相同根數涵蓋的天數差好幾倍，
固定根數比較是這類分析最容易犯的錯。
"""
import sys, time, calendar
import paxg_data
from dual_engine import backtest, buy_hold, dir_donchian, dir_ema_slope

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

YEARS = [2021, 2022, 2023, 2024, 2025, 2026]


def load(tf, mins, years=6.2):
    need = int(years * 365 * 24 * 60 / mins) + 100
    return paxg_data.fetch("PAXGUSDT", tf, max_bars=need, verbose=True)


def slice_year(bars, y):
    lo = calendar.timegm((y, 1, 1, 0, 0, 0)) * 1000
    hi = calendar.timegm((y + 1, 1, 1, 0, 0, 0)) * 1000
    return [b for b in bars if lo <= b["t"] < hi]


def regime(bh):
    """用該段買進持有的漲跌與回撤貼一個市況標籤。"""
    if bh["net"] > 15:
        return "單邊漲"
    if bh["net"] < -8:
        return "單邊跌"
    return "震盪"


def main():
    for tf, mins in [("4h", 240), ("1h", 60)]:
        bars = load(tf, mins)
        d0 = time.strftime("%Y-%m-%d", time.gmtime(bars[0]["t"] / 1000))
        print("\n############ %s・%s 根・%s 起 ############"
              % (tf, format(len(bars), ","), d0))

        for dname, dfn in [("Donchian55/20", lambda b: dir_donchian(b, 55, 20)),
                           ("EMA20/60", lambda b: dir_ema_slope(b, 20, 60))]:
            print("\n=== 方向訊號：%s ===" % dname)
            print("%-6s %-7s %9s │ %-28s │ %-28s │ %-28s"
                  % ("年份", "市況", "買進持有", "不分批（滿倉）", "順勢金字塔", "逆勢攤平"))
            print("%-6s %-7s %9s │ %8s %7s %6s %s │ %8s %7s %6s %s │ %8s %7s %6s %s"
                  % ("", "", "報酬/回撤", "報酬", "回撤", "報/撤", "最慘",
                     "報酬", "回撤", "報/撤", "最慘", "報酬", "回撤", "報/撤", "最慘"))

            tot = {m: 1.0 for m in ["single", "pyramid", "average"]}
            for y in YEARS:
                seg = slice_year(bars, y)
                if len(seg) < 500:
                    continue
                bh = buy_hold(seg)
                d = dfn(seg)
                cells = []
                for m in ["single", "pyramid", "average"]:
                    r = backtest(seg, d, mode=m, segs=5, step_atr=1.0, stop_atr=3.0)
                    tot[m] *= (1 + r["net"] / 100.0)
                    cells.append("%7.1f%% %6.1f%% %6.2f %6.1f%%"
                                 % (r["net"], r["mdd"],
                                    (r["net"] / r["mdd"]) if r["mdd"] else 0,
                                    r["worst"] if r["worst"] is not None else 0))
                print("%-6d %-7s %+6.1f%%/%4.1f%% │ %s │ %s │ %s"
                      % (y, regime(bh), bh["net"], bh["mdd"],
                         cells[0], cells[1], cells[2]))

            print("%-6s %-7s %9s │ %8s %19s │ %8s %19s │ %8s %19s"
                  % ("逐年複利", "", "",
                     "%.1f%%" % ((tot["single"] - 1) * 100), "",
                     "%.1f%%" % ((tot["pyramid"] - 1) * 100), "",
                     "%.1f%%" % ((tot["average"] - 1) * 100), ""))


if __name__ == "__main__":
    main()
