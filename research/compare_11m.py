# -*- coding: utf-8 -*-
"""11 分面板：驗證移植，並跟 15 分、廣度×密度在同一段期間比較。

11 分不是原生週期，要由 1 分 K 聚合，而 Binance 的 1 分 K 只回溯約 312 天——
所以這個面板的歷史深度結構上就卡在那裡，不可能跟六年的表並列。
這支只做兩件事：
  1. 用儀表板的算法驗證 11 分的移植（對照 20,000 根那次的實測值）
  2. 在 11 分能覆蓋的期間內，把三個配置放在同一個引擎上比

用法：python compare_11m.py
"""
import sys
import engine
from engine import run_scaled, sig_tsmom
from gold_data import ymd
from paxg_data import fetch as fetch_binance, aggregate
from rangefilter import apply_session, compute, to_position, backtest_dashboard
from new_indicators import sig_breadth_x_density

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

engine.COST = 0.00115

m1 = fetch_binance("PAXGUSDT", "1m", max_bars=390000)
print("1 分 K %d 根  %s ~ %s" % (len(m1), ymd(m1[0]["t"]), ymd(m1[-1]["t"])))

# 儀表板順序：聚合 → session → 取尾段
agg11 = aggregate(m1, 11)
ses11_legacy = apply_session(agg11, legacy=True)
ses11 = apply_session(agg11, legacy=False)
print("聚合 11 分 %d 根，session 過濾後 %d 根（正確版）/ %d 根（儀表板版）\n"
      % (len(agg11), len(ses11), len(ses11_legacy)))

# ---- 驗證移植：對照儀表板 20,000 根那次 ----
b20 = ses11_legacy[-20000:]
R20 = compute(b20, per=300, mult=23, src_mode="hl2")
print("驗證（legacy session、20,000 根、300/23）  %s ~ %s"
      % (ymd(b20[0]["t"]), ymd(b20[-1]["t"])))
for lo, nm in [(False, "多空都做"), (True, "只做多")]:
    d = backtest_dashboard(b20, R20["sig"], long_only=lo, cost=0.115)
    print("  %-8s 筆數 %3d  單利淨 %7.2f%%  回撤 %6.2f%%  空單 %d 筆 %+.2f%%"
          % (nm, d["n"], d["net"], d["mdd"], d["shorts"], d["shortPnl"]))
print("  儀表板實測：多空都做 16 筆 / +37.91% / 6.50% / 空單 8 筆 +28.88%\n")

# ---- 同期比較 ----
b11 = ses11[-20000:]
R11 = compute(b11, per=300, mult=23, src_mode="hl2")
t0, t1 = b11[0]["t"], b11[-1]["t"]

raw15 = fetch_binance("PAXGUSDT", "15m", max_bars=215000)
ses15 = apply_session(raw15, legacy=False)
b15 = [b for b in ses15 if t0 <= b["t"] <= t1]
R15 = compute(b15, per=100, mult=23, src_mode="hl2")

day = fetch_binance("PAXGUSDT", "1d")
lo_i = next((i for i, b in enumerate(day) if b["t"] >= t0), 0)
hi_i = next((i for i, b in enumerate(day) if b["t"] > t1), len(day))

print("同期比較  %s ~ %s（%d 天，受限於 1 分 K 的可得範圍）"
      % (ymd(t0), ymd(t1), (t1 - t0) / 864e5))
print("15 分 %d 根 / 日線 %d 根\n" % (len(b15), hi_i - lo_i))

rows = []
rows.append(run_scaled(b11, to_position(R11["sig"], False), "RF 11分 多空都做"))
rows.append(run_scaled(b11, to_position(R11["sig"], True), "RF 11分 只做多"))
rows.append(run_scaled(b15, to_position(R15["sig"], True), "RF 15分 只做多"))
N = len(day)
rows.append(run_scaled(day, sig_breadth_x_density(day), "廣度 × 密度", lo_i, hi_i))
rows.append(run_scaled(day, [1.0] * N, "買進持有", lo_i, hi_i))

print("%-18s %10s %10s %7s %10s" % ("", "複利報酬", "真實回撤", "換手", "報酬/回撤"))
print("-" * 60)
for r in rows:
    print("%-18s %9.1f%% %9.1f%% %7d %10.2f" % (r["name"], r["ret"], r["mdd"], r["n"], r["rr"]))

print("\n儀表板回撤 vs 真實回撤（11 分）")
for lo, nm in [(False, "11分 多空都做"), (True, "11分 只做多")]:
    d = backtest_dashboard(b11, R11["sig"], long_only=lo, cost=0.115)
    r = run_scaled(b11, to_position(R11["sig"], lo))
    print("  %-14s 儀表板 %6.2f%%   真實 %6.2f%%   （低估 %.1f pp）"
          % (nm, d["mdd"], r["mdd"], r["mdd"] - d["mdd"]))
