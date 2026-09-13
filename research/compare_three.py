# -*- coding: utf-8 -*-
"""儀表板的 Range Filter 與廣度×密度，跑在同一個引擎上比較。

為什麼需要這支：儀表板的 backtest() 算最大回撤時，只用**已平倉交易的單利
累積損益**，持倉期間的浮動虧損完全不計，而且用當根收盤價成交（訊號要收盤
才知道，卻用收盤價成交，有前瞻偏差）。那個回撤數字不能跟其他策略並列——
等於拿兩把不同的尺量。這裡一律走 engine.run_scaled：逐日複利權益、
訊號次根成交、成本按部位變化量計。

用法：python compare_three.py
"""
import sys
import engine
from engine import run_scaled, sig_tsmom
from gold_data import ymd
from paxg_data import fetch as fetch_binance
from rangefilter import apply_session, compute, to_position, backtest_dashboard
from new_indicators import sig_breadth_x_density

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

engine.COST = 0.00115          # 統一成儀表板用的單趟成本

# ---- Range Filter：15 分、100/23、只做多 ----
raw = fetch_binance("PAXGUSDT", "15m", max_bars=215000)
ses = apply_session(raw, legacy=False)          # 正確的 session（含夏令時）
bars15 = ses[-140000:]
R = compute(bars15, per=100, mult=23, src_mode="hl2")

t0, t1 = bars15[0]["t"], bars15[-1]["t"]
print("Range Filter 15 分・100/23　%s ~ %s　%d 根（過濾後 %d 根取尾段）"
      % (ymd(t0), ymd(t1), len(bars15), len(ses)))

rows = []
for lo, nm in [(True, "RF 15分 只做多"), (False, "RF 15分 多空都做")]:
    pos = to_position(R["sig"], long_only=lo)
    r = run_scaled(bars15, pos, nm)
    d = backtest_dashboard(bars15, R["sig"], long_only=lo, cost=0.115)
    rows.append((r, d))

# ---- 日線策略：同一段期間 ----
day = fetch_binance("PAXGUSDT", "1d")
lo_i = next((i for i, b in enumerate(day) if b["t"] >= t0), 0)
hi_i = next((i for i, b in enumerate(day) if b["t"] > t1), len(day))
print("日線對齊同期　%s ~ %s　%d 根\n" % (ymd(day[lo_i]["t"]), ymd(day[hi_i-1]["t"]), hi_i-lo_i))

N = len(day)
day_rows = [
    run_scaled(day, [1.0]*N, "買進持有", lo_i, hi_i),
    run_scaled(day, sig_breadth_x_density(day), "廣度 × 密度", lo_i, hi_i),
    run_scaled(day, sig_tsmom(day, 12, False), "TSMOM12", lo_i, hi_i),
]

print("%-18s %10s %10s %7s %10s" % ("", "複利報酬", "真實回撤", "換手", "報酬/回撤"))
print("-" * 60)
for r in day_rows:
    print("%-18s %9.1f%% %9.1f%% %7d %10.2f" % (r["name"], r["ret"], r["mdd"], r["n"], r["rr"]))
for r, d in rows:
    print("%-18s %9.1f%% %9.1f%% %7d %10.2f" % (r["name"], r["ret"], r["mdd"], r["n"], r["rr"]))

print("\n儀表板的回撤低估了多少（只有 RF 受影響）")
print("%-18s %14s %14s" % ("", "儀表板回撤", "逐日複利回撤"))
for r, d in rows:
    print("%-18s %13.2f%% %13.2f%%   （低估 %.1f 個百分點）"
          % (r["name"], d["mdd"], r["mdd"], r["mdd"] - d["mdd"]))
