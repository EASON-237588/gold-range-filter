# -*- coding: utf-8 -*-
"""對一組候選參數做完整體檢，產生評分需要的證據。

用法：
    python dual_evaluate.py                     4h / Donch300（掃描冠軍）
    python dual_evaluate.py 15m 15 400 average  15 分 / 回看 400 小時 / 攤平

每一項都是「試圖推翻它」，不是展示它：
  1. 分段     按日曆年切，看是不是只有一兩段在撐
  2. 前後半   後半段失效是這個專案先前所有策略的共同死因
  3. 多空拆解 把空單的真實代價量成一個數字
  4. 成本     0.115% 這個假設錯了會怎樣
  5. 鄰域     參數挪一格就崩，代表是尖峰不是高原
  6. 集中度   最大單筆、最長連虧、實際用到幾段

回看長度一律用「小時」指定再換算成根數。用根數指定的話，換週期等於同時改了
解析度與回看長度兩個變數，跑出來的差異無法歸因。
"""
import sys, calendar, time
import paxg_data
from dual_engine import backtest, buy_hold, atr, dir_donchian

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TF = sys.argv[1] if len(sys.argv) > 1 else "4h"
MINS = int(sys.argv[2]) if len(sys.argv) > 2 else 240
LOOKBACK_H = float(sys.argv[3]) if len(sys.argv) > 3 else 1200.0   # 4h 的 Donch300
MODE = sys.argv[4] if len(sys.argv) > 4 else "average"
STEP, STOP, SEGS = 1.0, 3.0, 5
BARS_PER_DAY = 1440.0 / MINS
N = int(LOOKBACK_H * 60 / MINS)
EXIT_N = max(10, N // 3)


def load(years=6.2):
    need = int(years * 365 * 24 * 60 / MINS) + 100
    return paxg_data.fetch("PAXGUSDT", TF, max_bars=need, verbose=True)


def run(bars, mode=MODE, step=STEP, stop=STOP, n=N, cost=0.115,
        long_only=False, short_only=False, atr_arr=None):
    d = dir_donchian(bars, n, max(10, n // 3))
    if long_only:
        d = [max(0, x) for x in d]
    if short_only:
        d = [min(0, x) for x in d]
    return backtest(bars, d, mode=mode, segs=SEGS, step_atr=step,
                    stop_atr=stop, cost=cost, atr_arr=atr_arr)


def line(tag, r, bh=None):
    rr = (r["net"] / r["mdd"]) if r["mdd"] else 0
    s = ("%-18s %+8.1f%% %7.1f%% %6.2f %5d筆 %6.1f%% 多%+7.1f%% 空%+7.1f%%"
         % (tag, r["net"], r["mdd"], rr, r["total"], r["win"] or 0,
            r["long_ret"], r["short_ret"]))
    if bh:
        s += "   （全抱 %+.1f%%／%.1f%%＝%.2f）" % (bh["net"], bh["mdd"],
                                              bh["net"] / bh["mdd"] if bh["mdd"] else 0)
    print(s)


def main():
    bars = load()
    A = atr(bars, 14)
    bh = buy_hold(bars)
    d0 = time.strftime("%Y-%m-%d", time.gmtime(bars[0]["t"] / 1000))
    d1 = time.strftime("%Y-%m-%d", time.gmtime(bars[-1]["t"] / 1000))
    print("PAXG %s・%s 根・%s ~ %s" % (TF, format(len(bars), ","), d0, d1))
    print("對象：回看 %.0f 小時（Donch%d/%d）・%s・step %.0f ATR・stop %.0f ATR・最多 %d 段\n"
          % (LOOKBACK_H, N, EXIT_N, MODE, STEP, STOP, SEGS))

    base = run(bars, atr_arr=A)
    line("全期", base, bh)
    print("  平均持倉 %.1f 天・停損觸發 %d 次・最慘單筆 %.1f%%"
          % (base["avg_held"] / BARS_PER_DAY, base["stops"], base["worst"] or 0))

    print("\n=== 1. 分段（日曆年）===")
    for y in [2021, 2022, 2023, 2024, 2025, 2026]:
        lo = calendar.timegm((y, 1, 1, 0, 0, 0)) * 1000
        hi = calendar.timegm((y + 1, 1, 1, 0, 0, 0)) * 1000
        seg = [b for b in bars if lo <= b["t"] < hi]
        if len(seg) < N * 2:
            continue
        line("%d" % y, run(seg), buy_hold(seg))

    print("\n=== 2. 前後半 ===")
    mid = len(bars) // 2
    line("前半", run(bars[:mid]), buy_hold(bars[:mid]))
    line("後半", run(bars[mid:]), buy_hold(bars[mid:]))

    print("\n=== 3. 多空拆解 ===")
    line("多空都做（基準）", base)
    line("只做多", run(bars, long_only=True, atr_arr=A))
    line("只做空", run(bars, short_only=True, atr_arr=A))

    print("\n=== 4. 成本敏感度（單趟 %）===")
    for c in [0.05, 0.115, 0.20, 0.30, 0.50]:
        r = run(bars, cost=c, atr_arr=A)
        print("  %.3f%% → %+7.1f%%／回撤 %5.1f%%（報/撤 %.2f）"
              % (c, r["net"], r["mdd"], r["net"] / r["mdd"] if r["mdd"] else 0))

    print("\n=== 5. 鄰域 ===")
    print("  -- 回看小時 --")
    for H in [LOOKBACK_H * f for f in [0.5, 0.75, 1.0, 1.5, 2.0]]:
        n = int(H * 60 / MINS)
        r = run(bars, n=n, atr_arr=A)
        print("     %5.0f 小時（%5d 根）→ %+7.1f%%／%5.1f%%（%.2f）%3d 筆"
              % (H, n, r["net"], r["mdd"], r["net"] / r["mdd"] if r["mdd"] else 0, r["total"]))
    print("  -- 加倉間距 step --")
    for s in [0.5, 1.0, 1.5, 2.0, 3.0]:
        r = run(bars, step=s, atr_arr=A)
        print("     step=%.1f → %+7.1f%%／%5.1f%%（%.2f）" % (s, r["net"], r["mdd"],
              r["net"] / r["mdd"] if r["mdd"] else 0))
    print("  -- 停損 stop --")
    for s in [2.0, 3.0, 4.0, 6.0, 999.0]:
        r = run(bars, stop=s, atr_arr=A)
        print("     stop=%5.0f → %+7.1f%%／%5.1f%%（%.2f）停損 %d 次"
              % (s, r["net"], r["mdd"], r["net"] / r["mdd"] if r["mdd"] else 0, r["stops"]))
    print("  -- 模式 --")
    for m in ["single", "pyramid", "average"]:
        r = run(bars, mode=m, atr_arr=A)
        print("     %-8s → %+7.1f%%／%5.1f%%（%.2f）" % (m, r["net"], r["mdd"],
              r["net"] / r["mdd"] if r["mdd"] else 0))

    print("\n=== 6. 交易結構 ===")
    ts = base["trades"]
    gains = sorted([t["ret"] for t in ts if t["ret"] > 0], reverse=True)
    if gains:
        tot_g = sum(gains)
        print("  最大單筆 %+.1f%%（佔總獲利 %.0f%%）・前三筆佔 %.0f%%"
              % (gains[0], gains[0] / tot_g * 100, sum(gains[:3]) / tot_g * 100))
    streak = mx = 0
    for t in ts:
        streak = streak + 1 if t["ret"] <= 0 else 0
        mx = max(mx, streak)
    print("  最長連續虧損 %d 筆・獲利筆 %d／虧損筆 %d" % (mx, len(gains), len(ts) - len(gains)))
    why = {}
    for t in ts:
        why[t["why"]] = why.get(t["why"], 0) + 1
    print("  出場原因：" + "、".join("%s %d 筆" % (k, v) for k, v in why.items()))
    seg_dist = {}
    for t in ts:
        seg_dist[t["segs"]] = seg_dist.get(t["segs"], 0) + 1
    print("  建到幾段：" + "、".join("%d段 %d筆" % (k, seg_dist[k]) for k in sorted(seg_dist)))


if __name__ == "__main__":
    main()
