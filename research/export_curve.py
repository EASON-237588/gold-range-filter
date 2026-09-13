# -*- coding: utf-8 -*-
"""匯出權益曲線與回撤曲線，給圖表用。

輸出 research/data/curves.json：
  {dates, series:{名稱:{equity, drawdown, pos}}, stats:{...}}
以週為單位取樣（每 5 個交易日一點），6532 根 -> 約 1300 點，
畫圖夠細又不會讓檔案太大。
"""
import io, json, os, sys
from gold_data import fetch, ymd
from engine import run_scaled, sig_tsmom
from new_indicators import sig_breadth_x_density

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

STEP = 5
bars = fetch("GC=F")
T = [b["t"] for b in bars]
C = [b["c"] for b in bars]
N = len(bars)

defs = [("廣度 × 密度", sig_breadth_x_density(bars)),
        ("買進持有",     [1.0] * N),
        ("TSMOM12",     sig_tsmom(bars, 12, False))]

out = {"dates": [], "price": [], "series": {}, "stats": {}}

runs = {}
for name, sig in defs:
    r = run_scaled(bars, sig, name)
    runs[name] = (r, sig)

# curve[j] 對應 bars[j+1]
L = min(len(r["curve"]) for r, _ in runs.values())
idx = list(range(0, L, STEP))
out["dates"] = [ymd(T[j + 1]) for j in idx]
out["price"] = [round(C[j + 1], 2) for j in idx]

for name, (r, sig) in runs.items():
    cv = r["curve"]
    eq, dd, peak = [], [], 0.0
    running_peak = 1.0
    ddfull = []
    for v in cv[:L]:
        if v > running_peak:
            running_peak = v
        ddfull.append(-(running_peak - v) / running_peak * 100)
    for j in idx:
        eq.append(round(cv[j], 4))
        dd.append(round(ddfull[j], 2))
    pos = [round(float(sig[j + 1]) if sig[j + 1] is not None else 0.0, 3) for j in idx]
    out["series"][name] = {"equity": eq, "drawdown": dd, "pos": pos}
    out["stats"][name] = {"ret": round(r["ret"], 1), "mdd": round(r["mdd"], 1),
                          "rr": round(r["rr"], 2), "n": r["n"]}

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
p = os.path.join(DATA, "curves.json")
io.open(p, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False))
print("已輸出 %s" % p)
print("點數 %d（原 %d 根，每 %d 根取一點）" % (len(idx), N, STEP))
print("期間 %s ~ %s" % (out["dates"][0], out["dates"][-1]))
for k, v in out["stats"].items():
    print("  %-12s 報酬 %8.1f%%  回撤 %5.1f%%  比 %5.2f" % (k, v["ret"], v["mdd"], v["rr"]))
print("檔案大小 %.0f KB" % (os.path.getsize(p) / 1024))
