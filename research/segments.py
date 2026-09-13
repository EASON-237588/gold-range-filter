# -*- coding: utf-8 -*-
"""六年內分段：三個配置在不同市況下各是什麼表現。

六年總計與 221 天的結論互相矛盾（一個說 15 分只做多最好、一個說 11 分多空最好），
差別在市況。要判斷哪個是穩定能力、哪個是抽到好籤，只能把期間切開看。

用法：python segments.py
"""
import sys
import engine
from engine import run_scaled
from gold_data import ymd
from paxg_data import fetch as fetch_binance, aggregate
from rangefilter import apply_session, compute, to_position
from new_indicators import sig_breadth_x_density

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

engine.COST = 0.00115

# 15 分
raw15 = fetch_binance("PAXGUSDT", "15m", max_bars=215000)
ses15 = apply_session(raw15, legacy=False)
b15 = ses15[-140000:]
R15 = compute(b15, per=100, mult=23, src_mode="hl2")
pos15_L = to_position(R15["sig"], True)
pos15_LS = to_position(R15["sig"], False)

# 11 分（只覆蓋得到最後一段）
m1 = fetch_binance("PAXGUSDT", "1m", max_bars=390000)
b11 = apply_session(aggregate(m1, 11), legacy=False)[-20000:]
R11 = compute(b11, per=300, mult=23, src_mode="hl2")
pos11_LS = to_position(R11["sig"], False)

# 日線
day = fetch_binance("PAXGUSDT", "1d")
bd = sig_breadth_x_density(day)

T15 = [b["t"] for b in b15]
T11 = [b["t"] for b in b11]
Td = [b["t"] for b in day]


def rng(T, a, b):
    lo = next((i for i, t in enumerate(T) if t >= a), None)
    hi = next((i for i, t in enumerate(T) if t > b), len(T))
    return (lo, hi) if lo is not None and hi - lo > 30 else None


SEGS = [
    ("2020-11 ~ 2022-11  盤整後段", "2020-11-11", "2022-11-01"),
    ("2022-11 ~ 2024-11  穩定多頭", "2022-11-01", "2024-11-01"),
    ("2024-11 ~ 2026-02  加速上漲", "2024-11-01", "2026-02-02"),
    ("2026-02 ~ 2026-09  崩跌與反彈", "2026-02-02", "2026-09-11"),
]

print("PAXG 六年分段（成本 0.115%、逐日複利、訊號次根成交）")
print("%-28s %11s %11s %11s %11s" % ("期間", "買進持有", "RF15只做多", "RF15多空", "廣度×密度"))
print("-" * 78)

for nm, a, b in SEGS:
    import time as _t
    ta = _t.mktime(_t.strptime(a, "%Y-%m-%d")) * 1000
    tb = _t.mktime(_t.strptime(b, "%Y-%m-%d")) * 1000
    out = [nm]
    r = rng(Td, ta, tb)
    out.append("%+.1f%%" % run_scaled(day, [1.0]*len(day), lo=r[0], hi=r[1])["ret"] if r else "—")
    r15 = rng(T15, ta, tb)
    out.append("%+.1f%%" % run_scaled(b15, pos15_L, lo=r15[0], hi=r15[1])["ret"] if r15 else "—")
    out.append("%+.1f%%" % run_scaled(b15, pos15_LS, lo=r15[0], hi=r15[1])["ret"] if r15 else "—")
    out.append("%+.1f%%" % run_scaled(day, bd, lo=r[0], hi=r[1])["ret"] if r else "—")
    print("%-28s %11s %11s %11s %11s" % tuple(out))

# 11 分只能覆蓋最後一段
import time as _t
ta = _t.mktime(_t.strptime("2026-02-02", "%Y-%m-%d")) * 1000
tb = _t.mktime(_t.strptime("2026-09-11", "%Y-%m-%d")) * 1000
r11 = rng(T11, ta, tb)
if r11:
    x = run_scaled(b11, pos11_LS, lo=r11[0], hi=r11[1])
    print("\n11 分多空都做只覆蓋得到最後一段：%+.1f%%（回撤 %.1f%%）—— 前三段它沒有資料"
          % (x["ret"], x["mdd"]))

print("\n全期回撤對照")
for nm, sig, bars in [("RF15 只做多", pos15_L, b15), ("RF15 多空", pos15_LS, b15)]:
    r = run_scaled(bars, sig)
    print("  %-12s 報酬 %+8.1f%%  回撤 %5.1f%%  比 %5.2f" % (nm, r["ret"], r["mdd"], r["rr"]))
for nm, sig in [("廣度×密度", bd), ("買進持有", [1.0]*len(day))]:
    lo = next(i for i, t in enumerate(Td) if t >= T15[0])
    r = run_scaled(day, sig, lo=lo, hi=len(day))
    print("  %-12s 報酬 %+8.1f%%  回撤 %5.1f%%  比 %5.2f" % (nm, r["ret"], r["mdd"], r["rr"]))
