# -*- coding: utf-8 -*-
"""成本地板：決定哪些週期值得進回測，在選定任何策略之前。

為什麼要先跑這支：短週期策略的天花板是成本佔比，不是參數。
每筆交易固定扣一次來回成本（0.23%），週期縮短會同時讓可捕捉的幅度變小、
交易次數變多，兩邊一起惡化。與其掃完幾萬組才發現全滅，不如先算比值。

判斷式（見 skill subminute-backtest）：
    平均單筆波幅 ÷ 來回成本 >= 10  值得掃
                            ~= 7   邊緣，大概率白工
                            <= 5   算術上不可能

這裡用一個**無參數的上界**代替「平均單筆波幅」：持有 h 根之後的平均絕對位移
mean(|c[i+h]/c[i]-1|)。任何策略的平均單筆毛利都不可能超過它——那需要每一筆
都押對方向。真實策略頂多拿到其中一部分，所以這是很寬鬆的上界：
**連上界都過不了關的週期，不必再測。**

順帶量兩件事：
  空 K 比例——沒有成交的那根會被補成平盤，會稀釋波動率估計，讓通道被壓窄、假訊號暴增。
  同一段日曆區間——不同週期的相同根數涵蓋的天數差好幾倍，比較一定要固定日曆區間。
"""
import io, json, os, sys, time
import paxg_data

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

COST_ONE_WAY = 0.115          # 實測：Binance VIP0 taker 0.10% + $1 萬單滑價 0.013%
COST_ROUND = COST_ONE_WAY * 2

TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
DAYS = 300                    # 1 分 K 只回溯約 312 天，取 300 天讓所有週期共用同一段
HOLDS_MIN = [15, 30, 60, 120, 240, 480, 1440, 4320, 10080]   # 持倉時間（分鐘）


def load(tf, days=DAYS):
    """抓足 days 天，回傳落在同一段日曆區間內的 K 線。"""
    need = int(days * 24 * 60 / TF_MIN[tf]) + 10
    bars = paxg_data.fetch("PAXGUSDT", tf, max_bars=need, verbose=True)
    cut = bars[-1]["t"] - days * 86400 * 1000
    return [b for b in bars if b["t"] >= cut]


def displacement(bars, h):
    """持有 h 根之後的平均絕對位移（%）。"""
    C = [b["c"] for b in bars]
    n = len(C) - h
    if n <= 0:
        return None
    s = 0.0
    for i in range(n):
        s += abs(C[i + h] / C[i] - 1.0)
    return s / n * 100.0


def main():
    print("PAXGUSDT・最近 %d 天・來回成本 %.3f%%\n" % (DAYS, COST_ROUND))

    data = {}
    for tf in TF_MIN:
        print("抓 %s ..." % tf)
        b = load(tf)
        data[tf] = b
        empty = sum(1 for x in b if x["v"] <= 0) / float(len(b)) * 100
        d0 = time.strftime("%Y-%m-%d", time.gmtime(b[0]["t"] / 1000))
        d1 = time.strftime("%Y-%m-%d", time.gmtime(b[-1]["t"] / 1000))
        print("  %s 根 %s ~ %s・空 K %.1f%%・每根平均絕對報酬 %.4f%%"
              % (format(len(b), ","), d0, d1, empty, displacement(b, 1)))

    print("\n== 持有 T 分鐘的平均絕對位移（%），括號內是 ÷ 來回成本的比值 ==")
    print("這是上界：每一筆都押對方向才拿得到。真實策略只能拿到其中一部分。\n")
    head = "持有時間".ljust(10)
    for tf in TF_MIN:
        head += tf.rjust(16)
    print(head)

    for T in HOLDS_MIN:
        label = ("%d 分" % T) if T < 60 else ("%d 小時" % (T / 60) if T < 1440 else "%d 天" % (T / 1440))
        line = label.ljust(10)
        for tf in TF_MIN:
            h = T // TF_MIN[tf]
            if h < 1:
                line += "—".rjust(16)
                continue
            d = displacement(data[tf], h)
            line += ("%.2f%% (%.1f)" % (d, d / COST_ROUND)).rjust(16)
        print(line)

    print("\n== 同一個持倉時間，換週期會多付多少成本 ==")
    print("可捕捉的幅度只取決於**持有多久**，跟 K 線切多細無關（上表同一列橫著看幾乎一樣）。")
    print("短週期唯一的差別是決策次數變多，也就是成本變多。\n")
    for T in [60, 240, 1440]:
        label = "%d 小時" % (T / 60) if T < 1440 else "%d 天" % (T / 1440)
        d_ref = displacement(data["4h"], max(1, T // 240))
        print("  持有 %s：可捕捉上界約 %.2f%%" % (label, d_ref))
        for tf in TF_MIN:
            # 假設策略平均持倉 T 分鐘，一年會做幾筆、扣掉多少成本
            per_year = 365 * 24 * 60 / float(T)
            print("      %-4s 平均持倉 %6.1f 根 → 一年約 %5.0f 筆 → 成本吃掉 %6.1f%%"
                  % (tf, T / float(TF_MIN[tf]), per_year, per_year * COST_ROUND))
        break   # 三個持倉時間的成本結構一樣，示範一個就夠

    print("\n== 一年成本 vs 一年可捕捉幅度 ==")
    print("持倉時間    一年筆數    一年成本    一年位移上界    上界扣成本後")
    for T in HOLDS_MIN:
        label = ("%d 分" % T) if T < 60 else ("%d 小時" % (T / 60) if T < 1440 else "%d 天" % (T / 1440))
        per_year = 365 * 24 * 60 / float(T)
        cost_y = per_year * COST_ROUND
        # 用 4h 線估位移（同一持倉時間各週期一致），不足一根就用 1h/15m 線
        for tf in ["4h", "1h", "15m", "5m", "1m"]:
            h = T // TF_MIN[tf]
            if h >= 1:
                d = displacement(data[tf], h)
                break
        gross_y = d * per_year
        print("%-10s %9.0f %10.0f%% %14.0f%% %14.0f%%"
              % (label, per_year, cost_y, gross_y, gross_y - cost_y))
    print("\n注意最後一欄不是「可以賺到」——它假設每一筆都押對方向。")
    print("真實策略的方向準確率大約落在 50~60%，實際毛利只有上界的一小部分。")


if __name__ == "__main__":
    main()
