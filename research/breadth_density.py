# -*- coding: utf-8 -*-
"""「廣度 × 密度」的深入回測。

總報酬之外，實際要操作還得知道：逐年表現、多少時間在場外、
最長空手期、最差的一年、以及成本敏感度（它換手比 TSMOM 密 10 倍）。

用法：python breadth_density.py
"""
import sys
import engine
from gold_data import fetch, ymd
from engine import run_scaled, sig_tsmom
from new_indicators import sig_breadth_x_density

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def yearly(bars, sig, lo=0, hi=None):
    """逐年報酬（複利），回傳 {年: 報酬%}。"""
    N = len(bars)
    hi = N if hi is None else hi
    r = run_scaled(bars, sig, lo=lo, hi=hi)
    cv = r["curve"]
    T = [b["t"] for b in bars]
    out, prev_y, start_v = {}, None, 1.0
    last_v = 1.0
    for j, v in enumerate(cv):
        y = ymd(T[lo + j + 1])[:4]
        if prev_y is None:
            prev_y = y
        if y != prev_y:
            out[prev_y] = (last_v / start_v - 1) * 100
            start_v, prev_y = last_v, y
        last_v = v
    if prev_y is not None:
        out[prev_y] = (last_v / start_v - 1) * 100
    return out


def pos_stats(bars, sig, lo=0, hi=None):
    """部位分布與最長空手期。"""
    N = len(bars)
    hi = N if hi is None else hi
    buckets = {}
    pos, run_flat, max_flat, flat_start, max_flat_at = 0.0, 0, 0, None, ""
    T = [b["t"] for b in bars]
    for i in range(lo, min(hi, N) - 1):
        want = sig[i] if sig[i] is not None else pos
        pos = float(want)
        key = round(pos, 2)
        buckets[key] = buckets.get(key, 0) + 1
        if pos == 0.0:
            if run_flat == 0:
                flat_start = ymd(T[i])
            run_flat += 1
            if run_flat > max_flat:
                max_flat, max_flat_at = run_flat, flat_start
        else:
            run_flat = 0
    total = sum(buckets.values())
    return buckets, total, max_flat, max_flat_at


for sym in ["GC=F", "GLD"]:
    bars = fetch(sym)
    T = [b["t"] for b in bars]
    N = len(bars)
    bd = sig_breadth_x_density(bars)
    hold = [1.0] * N
    tsm = sig_tsmom(bars, 12, False)

    print("=" * 78)
    print("%s  %s ~ %s  %d 根" % (sym, ymd(T[0]), ymd(T[-1]), N))
    print("=" * 78)

    a = run_scaled(bars, bd, "廣度×密度")
    b = run_scaled(bars, hold, "買進持有")
    c = run_scaled(bars, tsm, "TSMOM12")
    print("%-12s %10s %8s %6s %8s %9s" % ("", "複利報酬", "最大回撤", "換手", "月頻", "報酬/回撤"))
    for r in (b, c, a):
        print("%-12s %9.1f%% %7.1f%% %6d %8s %9.2f"
              % (r["name"], r["ret"], r["mdd"], r["n"],
                 "%.1f" % r["月頻"] if r["月頻"] else "—", r["rr"]))

    # 部位分布
    buckets, total, max_flat, flat_at = pos_stats(bars, bd)
    print("\n部位分布（佔交易日比例）")
    for k in sorted(buckets):
        print("  部位 %4.0f%%  %5.1f%%  (%d 天)" % (k*100, buckets[k]/total*100, buckets[k]))
    print("  最長連續空手 %d 天（約 %.1f 個月），自 %s 起" % (max_flat, max_flat/21.0, flat_at))

    # 關鍵檢驗：低回撤是擇時能力，還是單純低曝險？
    # 用相同平均部位的「固定部位一直抱」當對照。贏不過它就代表沒有擇時價值。
    avg_pos = sum(k * v for k, v in buckets.items()) / float(total)
    fixed = [avg_pos] * N
    fx = run_scaled(bars, fixed, "固定%.0f%%一直抱" % (avg_pos*100))
    print("\n關鍵檢驗：擇時能力 vs 單純低曝險")
    print("  廣度×密度的平均部位 %.1f%%" % (avg_pos*100))
    print("  %-16s %9.1f%% / 回撤 %5.1f%% / 比 %5.2f" % ("廣度×密度", a["ret"], a["mdd"], a["rr"]))
    print("  %-16s %9.1f%% / 回撤 %5.1f%% / 比 %5.2f" % (fx["name"], fx["ret"], fx["mdd"], fx["rr"]))
    verdict = "有擇時價值" if a["rr"] > fx["rr"] else "沒有擇時價值——等於低曝險而已"
    print("  → %s" % verdict)

    # 成本敏感度
    print("\n成本敏感度（單趟）")
    orig = engine.COST
    for cst in [0.0005, 0.001, 0.002, 0.004]:
        engine.COST = cst
        x = run_scaled(bars, bd)
        y = run_scaled(bars, hold)
        print("  %.2f%%  廣度×密度 %8.1f%% / 回撤 %5.1f%% / 比 %5.2f   （全抱 %.1f%%）"
              % (cst*100, x["ret"], x["mdd"], x["rr"], y["ret"]))
    engine.COST = orig

    # 逐年
    ybd = yearly(bars, bd)
    ybh = yearly(bars, hold)
    ytm = yearly(bars, tsm)
    print("\n逐年報酬（%）   年份  廣度×密度   買進持有   TSMOM12   差距")
    wins = 0; yrs = 0
    for y in sorted(ybd):
        d1, d2, d3 = ybd[y], ybh.get(y, 0), ytm.get(y, 0)
        yrs += 1
        if d1 > d2: wins += 1
        flag = ""
        if d2 < -10 and d1 > d2 + 5: flag = "  <-空頭年保護"
        print("               %s  %8.1f  %9.1f  %8.1f  %+7.1f%s" % (y, d1, d2, d3, d1-d2, flag))
    print("  勝過買進持有的年數：%d / %d (%.0f%%)" % (wins, yrs, wins/yrs*100))
    print()
