# -*- coding: utf-8 -*-
"""用 11 分訊號當買進點，買了不賣。

跟前面兩支的差別：
  entry_timing.py  買進條件是「回檔／突破／定期」，機械式，不看趨勢狀態
  dual_*.py        有進有出，會賣
  這一支           買進條件是 11 分 Donchian 轉多（短週期裡表現最好的訊號），
                   但**永不賣出**，投完就長期持有

三種投法都測：
  首次訊號全投  等第一個多頭訊號出現就一次投滿，之後不動
  訊號分批      每次訊號轉多投一份，分 6 或 12 份投完
  期初全買      基準

滾動起點是必要的，不是加分項：entry_timing 的「回檔買進」在六年單一樣本上
贏 22.4pp，換成 21 個滾動起點後只贏 3 次、平均輸 46pp。單一起點會騙人。
"""
import sys, time
import paxg_data
from dual_engine import dir_donchian
from subminute_sweep import aggregate

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TF_MIN = 11
LOOKBACK_H = 600
COST = 0.115


def accumulate(bars, sig=None, parts=1, cost=COST):
    """投完不賣。sig=None 表示期初全投（基準）。

    sig 給定時，只在訊號**由非多轉為多**的那一根投一份——持續為多的期間不重複投，
    否則會退化成「一路買到滿」，跟期初全買沒兩樣。
    """
    n = len(bars)
    C = [b["c"] for b in bars]
    frac = 1.0 / parts
    invested = 0.0
    units = 0.0
    buys = []
    peak = 1.0
    mdd = 0.0
    prev = 0

    for i in range(n):
        buy = False
        if invested < 1.0 - 1e-9:
            if sig is None:
                buy = (i == 0)
            else:
                buy = (sig[i] > 0 and prev <= 0)
        if sig is not None:
            prev = sig[i]
        if buy:
            amt = min(frac, 1.0 - invested)
            units += amt * (1 - cost / 100.0) / C[i]
            invested += amt
            buys.append(i)
        eq = units * C[i] + (1.0 - invested)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > mdd:
            mdd = dd

    if invested < 1.0 - 1e-9:                 # 沒投完的在最後補齊，曝險才可比
        amt = 1.0 - invested
        units += amt * (1 - cost / 100.0) / C[-1]
        buys.append(n - 1)
    return {"net": (units * C[-1] - 1) * 100, "mdd": mdd,
            "cost_basis": 1.0 / units if units else None,
            "n_buys": len(buys), "first": buys[0] if buys else 0,
            "last": buys[-1] if buys else 0}


def main():
    m1 = paxg_data.fetch("PAXGUSDT", "1m", max_bars=3300000, verbose=False)
    bars = aggregate(m1, TF_MIN)
    n_look = int(LOOKBACK_H * 60 / TF_MIN)
    print("PAXG %d 分・%s 根・%s ~ %s・Donchian 回看 %d 小時（%d 根）"
          % (TF_MIN, format(len(bars), ","),
             time.strftime("%Y-%m-%d", time.gmtime(bars[0]["t"] / 1000)),
             time.strftime("%Y-%m-%d", time.gmtime(bars[-1]["t"] / 1000)),
             LOOKBACK_H, n_look))

    sig = dir_donchian(bars, n_look, max(10, n_look // 3))
    lump = accumulate(bars, None)
    print("\n=== 六年全樣本 ===")
    print("  %-16s %+8.1f%% │ 過程回撤 %5.1f%% │ 成本 %8.2f │ %2d 次"
          % ("期初全買（基準）", lump["net"], lump["mdd"], lump["cost_basis"], lump["n_buys"]))
    for parts in [1, 6, 12]:
        r = accumulate(bars, sig, parts)
        lab = "首次訊號全投" if parts == 1 else "訊號分批 %d 份" % parts
        print("  %-16s %+8.1f%% │ 過程回撤 %5.1f%% │ 成本 %8.2f │ %2d 次・首買 %s  %+6.1f pp"
              % (lab, r["net"], r["mdd"], r["cost_basis"], r["n_buys"],
                 time.strftime("%Y-%m-%d", time.gmtime(bars[r["first"]]["t"] / 1000)),
                 r["net"] - lump["net"]))

    print("\n=== 滾動起點（每季一個，各自跑到資料末端）===")
    print("  %-12s %-8s │ %9s %9s %9s │ %8s"
          % ("起點", "剩餘", "期初全買", "首次訊號", "訊號12份", "誰贏"))
    q = int(90 * 24 * 60 / TF_MIN)
    stats = {1: [], 12: []}
    for s in range(0, len(bars) - n_look * 3, q):
        seg = bars[s:]
        yrs = (seg[-1]["t"] - seg[0]["t"]) / 31557600000
        if yrs < 1.0:
            break
        sg = dir_donchian(seg, n_look, max(10, n_look // 3))
        lp = accumulate(seg, None)
        r1 = accumulate(seg, sg, 1)
        r12 = accumulate(seg, sg, 12)
        stats[1].append(r1["net"] - lp["net"])
        stats[12].append(r12["net"] - lp["net"])
        best = max([("期初全買", lp["net"]), ("首次訊號", r1["net"]),
                    ("訊號12份", r12["net"])], key=lambda x: x[1])[0]
        print("  %-12s %-8s │ %+8.1f%% %+8.1f%% %+8.1f%% │ %s"
              % (time.strftime("%Y-%m-%d", time.gmtime(seg[0]["t"] / 1000)),
                 "%.1f 年" % yrs, lp["net"], r1["net"], r12["net"], best))
        sys.stdout.flush()

    print()
    for k, name in [(1, "首次訊號全投"), (12, "訊號分批 12 份")]:
        d = stats[k]
        w = sum(1 for x in d if x > 0)
        print("  %s：勝 %d／%d（%.0f%%）・平均 %+.1f pp・中位數 %+.1f pp"
              % (name, w, len(d), w / len(d) * 100,
                 sum(d) / len(d), sorted(d)[len(d) // 2]))


if __name__ == "__main__":
    main()
