# -*- coding: utf-8 -*-
"""11 分・兩態反轉・多空都做：找出能在儀表板可載入的樣本內給出足夠筆數的參數。

問題：儀表板的 11 分只能載入約 152 天（20,000 根）——11 分不是原生週期，
要用 1 分 K 合成，20,000 根 11 分就得下載 22 萬根 1 分 K。而目前回看 800 小時
（4,364 根）佔掉樣本的 22%，六年只翻轉幾次，152 天內只有 1 筆。

所以要同時滿足兩件事，缺一不可：
  六年樣本上站得住（報酬÷回撤 夠好、分段不崩）
  152 天樣本內筆數夠（>= 10 筆才有辦法在畫面上看出東西）

這兩者互相拉扯：回看越短筆數越多，但短週期高頻正是先前測到全滅的區域。
所以這支同時印出「六年績效」與「最近 152 天筆數」，讓取捨看得見。
"""
import sys, time
import paxg_data
from dual_engine import backtest_asym, buy_hold, atr, dir_donchian
from subminute_sweep import aggregate

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MINS = 11
DASH_BARS = 20000          # 儀表板實際會載入的根數
HOURS = [50, 100, 150, 200, 300, 400, 600, 800]
STEPS = [0.5, 1.0, 1.5, 2.0]
SEGSET = [2, 3, 5]


def main():
    m1 = paxg_data.fetch("PAXGUSDT", "1m", max_bars=3300000, verbose=False)
    bars = aggregate(m1, MINS)
    A = atr(bars, 14)
    bh = buy_hold(bars)
    yrs = (bars[-1]["t"] - bars[0]["t"]) / 31557600000
    print("PAXG %d 分・%s 根・%.1f 年・買進持有 %+.1f%%／回撤 %.1f%%（%.2f）"
          % (MINS, format(len(bars), ","), yrs, bh["net"], bh["mdd"], bh["net"] / bh["mdd"]))
    print("模式：兩態反轉（多空都做、永遠在場、無硬停損）\n")
    print("%-8s %-5s %-6s │ %8s %7s %6s %6s │ %8s │ %s"
          % ("回看", "段數", "step", "六年報酬", "回撤", "報/撤", "六年筆",
             "近152天筆", "判定"))

    rows = []
    for H in HOURS:
        n = int(H * 60 / MINS)
        if n < 20 or n > len(bars) // 6:
            continue
        d = dir_donchian(bars, n, max(10, n // 3), reverse=True)
        for segs in SEGSET:
            for step in STEPS:
                cfg = {"mode": "average", "step": step, "stop_atr": None, "stop_pct": None}
                r = backtest_asym(bars, d, cfg, cfg, segs=segs, atr_arr=A, bar_minutes=MINS)
                if r["total"] < 2 or r["mdd"] <= 0:
                    continue
                # 儀表板實際看到的那一段：最後 DASH_BARS 根裡有幾筆
                cut = bars[-DASH_BARS]["t"]
                recent = sum(1 for t in r["trades"] if bars[t["idx"]]["t"] >= cut)
                rr = r["net"] / r["mdd"]
                ok = "✓" if (recent >= 10 and rr > 0) else ("筆數不足" if rr > 0 else "負報酬")
                rows.append((rr, recent, H, segs, step, r))
                print("%-8s %-5d %-6.1f │ %+7.1f%% %6.1f%% %6.2f %6d │ %8d │ %s"
                      % ("%d時" % H, segs, step, r["net"], r["mdd"], rr,
                         r["total"], recent, ok))
        sys.stdout.flush()

    good = [x for x in rows if x[1] >= 10 and x[0] > 0]
    print()
    if good:
        good.sort(key=lambda x: -x[0])
        print("=== 近 152 天 >= 10 筆且六年為正的組合，依六年報酬÷回撤排序 ===")
        for rr, recent, H, segs, step, r in good[:8]:
            print("  回看 %4d 時・%d 段・step %.1f → 六年 %+.1f%%／%.1f%%（%.2f）"
                  "・六年 %d 筆・近期 %d 筆・勝率 %.0f%%"
                  % (H, segs, step, r["net"], r["mdd"], rr, r["total"], recent, r["win"] or 0))
    else:
        print("沒有組合能同時滿足「近 152 天 >= 10 筆」與「六年為正」。")
        pos = [x for x in rows if x[0] > 0]
        if pos:
            pos.sort(key=lambda x: -x[1])
            rr, recent, H, segs, step, r = pos[0]
            print("  六年為正之中，近期筆數最多的：回看 %d 時・%d 段・step %.1f"
                  "→ 近期 %d 筆・六年 %.2f" % (H, segs, step, recent, rr))


if __name__ == "__main__":
    main()
