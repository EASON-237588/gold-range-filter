# -*- coding: utf-8 -*-
"""參數優化：只做多、逆勢累積加倉、不做空。

用法：python optimize_long.py 240 1200   （週期分鐘、目前基準回看小時）
      python optimize_long.py 11 600

防過擬合的三道關卡，在看報酬之前就先套用：
  筆數 >= 10        六年至少每半年一筆，否則樣本撐不起結論
  集中度 <= 60%     最大單筆不能佔總獲利六成以上
  最長連虧 <= 8     連虧太長的組合實務上撐不住，會提早停用

排序用報酬÷回撤而不是報酬——這個專案先前每一次用報酬排序，
選到的都是單純曝險大的組合。

掃完之後對冠軍做高原檢查：沿**每個軸分開看**，不要把不同敏感度的軸混在一起
平均（先前犯過這個錯，把 mult 的窄脊與 per 的高原混算，誤判成尖峰）。
"""
import sys, time
import paxg_data
from dual_engine import backtest_asym, buy_hold, atr, dir_donchian
from subminute_sweep import aggregate

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MINS = int(sys.argv[1]) if len(sys.argv) > 1 else 240
BASE_H = float(sys.argv[2]) if len(sys.argv) > 2 else 1200
OFF = {"enabled": False}

HOURS = [200, 300, 400, 600, 800, 1000, 1200, 1600, 2000]
STEPS = [0.5, 1.0, 1.5, 2.0, 3.0]
STOPS = [2.0, 3.0, 4.0, 6.0, 999.0]
SEGSET = [3, 5]
MIN_TRADES, MAX_CONC, MAX_STREAK = 10, 60.0, 8


def load():
    if MINS == 240:
        return paxg_data.fetch("PAXGUSDT", "4h", max_bars=14000, verbose=False)
    if MINS == 60:
        return paxg_data.fetch("PAXGUSDT", "1h", max_bars=55000, verbose=False)
    m1 = paxg_data.fetch("PAXGUSDT", "1m", max_bars=3300000, verbose=False)
    return aggregate(m1, MINS)


def metrics(r):
    ts = r["trades"]
    gains = [t["ret"] for t in ts if t["ret"] > 0]
    conc = (max(gains) / sum(gains) * 100) if gains and sum(gains) > 0 else 999
    streak = mx = 0
    for t in ts:
        streak = streak + 1 if t["ret"] <= 0 else 0
        mx = max(mx, streak)
    return conc, mx


def main():
    bars = load()
    A = atr(bars, 14)
    bh = buy_hold(bars)
    bpd = 1440.0 / MINS
    yrs = (bars[-1]["t"] - bars[0]["t"]) / 31557600000
    print("PAXG %d 分・%s 根・%.1f 年・買進持有 %+.1f%%／回撤 %.1f%%（%.2f）"
          % (MINS, format(len(bars), ","), yrs, bh["net"], bh["mdd"], bh["net"] / bh["mdd"]))
    print("篩選：筆數>=%d・集中度<=%.0f%%・最長連虧<=%d\n" % (MIN_TRADES, MAX_CONC, MAX_STREAK))

    sigs = {}
    for H in HOURS:
        n = int(H * 60 / MINS)
        if n < 20 or n > len(bars) // 4:
            continue
        sigs[H] = dir_donchian(bars, n, max(10, n // 3))

    t0 = time.time()
    rows, tried = [], 0
    for H, d in sigs.items():
        for segs in SEGSET:
            for step in STEPS:
                for stop in STOPS:
                    tried += 1
                    cfg = {"mode": "average", "step": step,
                           "stop_atr": (None if stop >= 999 else stop), "stop_pct": None}
                    r = backtest_asym(bars, d, cfg, OFF, segs=segs,
                                      atr_arr=A, bar_minutes=MINS)
                    if r["total"] < MIN_TRADES or r["mdd"] <= 0:
                        continue
                    conc, streak = metrics(r)
                    rows.append({"H": H, "segs": segs, "step": step, "stop": stop,
                                 "net": r["net"], "mdd": r["mdd"],
                                 "rr": r["net"] / r["mdd"], "n": r["total"],
                                 "win": r["win"], "pf": r["pf"], "conc": conc,
                                 "streak": streak, "stops": r["stops"],
                                 "hold": (r["avg_held"] or 0) / bpd})
    print("掃了 %d 組、%.0f 秒" % (tried, time.time() - t0))

    ok = [x for x in rows if x["conc"] <= MAX_CONC and x["streak"] <= MAX_STREAK]
    print("通過篩選 %d／%d 組\n" % (len(ok), len(rows)))
    if not ok:
        print("沒有組合通過篩選。放寬後最好的：")
        ok = sorted(rows, key=lambda x: -x["rr"])[:5]

    ok.sort(key=lambda x: -x["rr"])
    print("%-7s %-5s %-6s %-7s │ %8s %7s %6s %5s %6s %6s %6s %7s"
          % ("回看", "段數", "step", "stop", "報酬", "回撤", "報/撤",
             "筆數", "勝率", "集中度", "連虧", "持倉天"))
    for x in ok[:15]:
        print("%-7s %-5d %-6.1f %-7s │ %+7.1f%% %6.1f%% %6.2f %5d %5.0f%% %5.0f%% %6d %7.1f"
              % ("%d時" % x["H"], x["segs"], x["step"],
                 ("無" if x["stop"] >= 999 else "%.0f" % x["stop"]),
                 x["net"], x["mdd"], x["rr"], x["n"], x["win"] or 0,
                 x["conc"], x["streak"], x["hold"]))

    b = ok[0]
    print("\n=== 冠軍的高原檢查（每軸分開看，其餘固定）===")
    print("冠軍：回看 %d 時・%d 段・step %.1f・stop %s → %.2f"
          % (b["H"], b["segs"], b["step"],
             "無" if b["stop"] >= 999 else "%.0f" % b["stop"], b["rr"]))

    def probe(vary, values):
        out = []
        for v in values:
            H = v if vary == "H" else b["H"]
            segs = v if vary == "segs" else b["segs"]
            step = v if vary == "step" else b["step"]
            stop = v if vary == "stop" else b["stop"]
            n = int(H * 60 / MINS)
            if n < 20 or n > len(bars) // 4:
                out.append((v, None))
                continue
            d = sigs.get(H) or dir_donchian(bars, n, max(10, n // 3))
            cfg = {"mode": "average", "step": step,
                   "stop_atr": (None if stop >= 999 else stop), "stop_pct": None}
            r = backtest_asym(bars, d, cfg, OFF, segs=segs, atr_arr=A, bar_minutes=MINS)
            out.append((v, r["net"] / r["mdd"] if r["mdd"] else 0))
        return out

    for vary, values, unit in [("H", HOURS, "小時"), ("step", STEPS, ""),
                               ("stop", [2.0, 3.0, 4.0, 6.0, 999.0], ""),
                               ("segs", [2, 3, 4, 5, 6], "段")]:
        cells = []
        for v, rr in probe(vary, values):
            lab = ("無" if (vary == "stop" and v >= 999) else
                   ("%g" % v) + unit)
            cells.append("%s=%s" % (lab, "—" if rr is None else "%.2f" % rr))
        print("  %-6s " % vary + "  ".join(cells))


if __name__ == "__main__":
    main()
