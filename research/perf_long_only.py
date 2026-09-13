# -*- coding: utf-8 -*-
"""績效報表：11 分與 4 小時，只做多、逆勢累積加倉、不做空。

兩套都是先前掃描出來的該週期最佳只做多組合：
  11 分   Donchian 回看 600 小時・逆勢攤平最多 5 段・stop 3 ATR
  4 小時  Donchian 回看 1200 小時（300 根）・同上

除了各自的績效，也算兩者各半資金的組合——兩個週期的訊號時機不同，
若相關性低，組合的回撤會低於各自的加權平均，這是唯一「免費」的改善來源。
"""
import sys, time, calendar, math
import paxg_data
from dual_engine import backtest_asym, buy_hold, atr, dir_donchian
from subminute_sweep import aggregate

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LONG = {"mode": "average", "step": 1.0, "stop_atr": 3.0, "stop_pct": None}
OFF = {"enabled": False}
CFG = [("11 分", 11, 600), ("4 小時", 240, 1200)]


def load(mins):
    if mins == 240:
        return paxg_data.fetch("PAXGUSDT", "4h", max_bars=14000, verbose=False)
    m1 = paxg_data.fetch("PAXGUSDT", "1m", max_bars=3300000, verbose=False)
    return aggregate(m1, mins)


def run(bars, mins, H, A=None):
    n = int(H * 60 / mins)
    d = dir_donchian(bars, n, max(10, n // 3))
    return backtest_asym(bars, d, LONG, OFF, atr_arr=A, bar_minutes=mins), d


def stats_block(name, bars, mins, r):
    bpd = 1440.0 / mins
    ts = r["trades"]
    gains = sorted([t["ret"] for t in ts if t["ret"] > 0], reverse=True)
    losses = [t["ret"] for t in ts if t["ret"] <= 0]
    tot_g = sum(gains) if gains else 1
    streak = mx = 0
    for t in ts:
        streak = streak + 1 if t["ret"] <= 0 else 0
        mx = max(mx, streak)
    seg_dist = {}
    for t in ts:
        seg_dist[t["segs"]] = seg_dist.get(t["segs"], 0) + 1
    why = {}
    for t in ts:
        why[t["why"]] = why.get(t["why"], 0) + 1
    yrs = (bars[-1]["t"] - bars[0]["t"]) / 31557600000
    cagr = ((1 + r["net"] / 100) ** (1 / yrs) - 1) * 100

    print("  淨報酬 %+.1f%%（年化 %+.1f%%）・最大回撤 %.1f%%・報酬÷回撤 %.2f"
          % (r["net"], cagr, r["mdd"], r["net"] / r["mdd"] if r["mdd"] else 0))
    print("  交易 %d 筆・勝率 %.1f%%・獲利因子 %s・平均持倉 %.1f 天"
          % (r["total"], r["win"] or 0,
             ("%.2f" % r["pf"]) if r["pf"] else "—",
             (r["avg_held"] or 0) / bpd))
    print("  最大單筆 %+.1f%%（佔總獲利 %.0f%%）・前三筆佔 %.0f%%・最慘單筆 %.1f%%"
          % (gains[0] if gains else 0, (gains[0] / tot_g * 100) if gains else 0,
             (sum(gains[:3]) / tot_g * 100) if gains else 0, r["worst"] or 0))
    print("  最長連虧 %d 筆・獲利 %d／虧損 %d・停損觸發 %d 次"
          % (mx, len(gains), len(losses), r["stops"]))
    print("  出場原因：" + "、".join("%s %d" % (k, v) for k, v in why.items())
          + "　建到段數：" + "、".join("%d段%d筆" % (k, seg_dist[k]) for k in sorted(seg_dist)))


def year_table(name, bars, mins, H):
    print("\n  %-6s %10s │ %9s %8s %7s %6s" % ("年份", "買進持有", "策略報酬", "回撤", "報/撤", "筆數"))
    for y in [2021, 2022, 2023, 2024, 2025, 2026]:
        lo = calendar.timegm((y, 1, 1, 0, 0, 0)) * 1000
        hi = calendar.timegm((y + 1, 1, 1, 0, 0, 0)) * 1000
        seg = [b for b in bars if lo <= b["t"] < hi]
        n = int(H * 60 / mins)
        if len(seg) < n * 2:
            continue
        r, _ = run(seg, mins, H)
        bh = buy_hold(seg)
        print("  %-6d %+9.1f%% │ %+8.1f%% %7.1f%% %7.2f %6d"
              % (y, bh["net"], r["net"], r["mdd"],
                 r["net"] / r["mdd"] if r["mdd"] else 0, r["total"]))


def main():
    curves = {}
    for name, mins, H in CFG:
        bars = load(mins)
        A = atr(bars, 14)
        r, d = run(bars, mins, H, A)
        bh = buy_hold(bars)
        yrs = (bars[-1]["t"] - bars[0]["t"]) / 31557600000
        print("\n" + "=" * 76)
        print("%s・只做多・逆勢累積最多 5 段・回看 %d 小時・%s 根・%.1f 年"
              % (name, H, format(len(bars), ","), yrs))
        print("=" * 76)
        print("  【對照】買進持有 %+.1f%%／回撤 %.1f%%（報酬÷回撤 %.2f）"
              % (bh["net"], bh["mdd"], bh["net"] / bh["mdd"]))
        stats_block(name, bars, mins, r)
        year_table(name, bars, mins, H)
        curves[name] = (bars, r)

    # 組合：兩套各半資金。用日頻權益取樣後合併，避免根數不同無法對齊。
    print("\n" + "=" * 76)
    print("兩套各半資金的組合")
    print("=" * 76)
    daily = {}
    for name, (bars, r) in curves.items():
        c = r["curve"]
        by_day = {}
        for i in range(min(len(c), len(bars))):
            day = bars[i]["t"] // 86400000
            by_day[day] = c[i]
        daily[name] = by_day
    days = sorted(set(daily[CFG[0][0]]) & set(daily[CFG[1][0]]))
    a = [daily[CFG[0][0]][d] for d in days]
    b = [daily[CFG[1][0]][d] for d in days]
    comb = [(a[i] + b[i]) / 2 for i in range(len(days))]

    def mdd_of(series):
        peak = -1e18
        m = 0.0
        for v in series:
            eq = 1 + v / 100
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > m:
                m = dd
        return m

    # 日報酬相關係數
    ra = [a[i] - a[i - 1] for i in range(1, len(a))]
    rb = [b[i] - b[i - 1] for i in range(1, len(b))]
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(len(ra)))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((x - mb) ** 2 for x in rb))
    corr = cov / (va * vb) if va and vb else 0

    print("  共同期間 %d 天（%s ~ %s）"
          % (len(days), time.strftime("%Y-%m-%d", time.gmtime(days[0] * 86400)),
             time.strftime("%Y-%m-%d", time.gmtime(days[-1] * 86400))))
    print("  %-12s %9s %8s %7s" % ("", "終值", "回撤", "報/撤"))
    for lab, ser in [(CFG[0][0], a), (CFG[1][0], b), ("各半組合", comb)]:
        m = mdd_of(ser)
        print("  %-12s %+8.1f%% %7.1f%% %7.2f" % (lab, ser[-1], m, ser[-1] / m if m else 0))
    print("  兩套日報酬相關係數 %.2f" % corr)
    print("  組合回撤 %.1f%%，兩者平均 %.1f%%——%s"
          % (mdd_of(comb), (mdd_of(a) + mdd_of(b)) / 2,
             "分散有效" if mdd_of(comb) < (mdd_of(a) + mdd_of(b)) / 2 else "沒有分散效果"))


if __name__ == "__main__":
    main()
