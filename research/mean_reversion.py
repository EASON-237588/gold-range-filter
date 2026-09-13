# -*- coding: utf-8 -*-
"""均值回歸類策略 —— 跟趨勢跟隨相反的一整類。

為什麼要測這個：先前七種策略全是趨勢跟隨（追漲殺跌），而且都收斂到
「只做多或空手」。那個收斂的依據是 26 年大多頭樣本，把它當設計前提
等於把歷史外推。均值回歸的行為完全相反——漲多了減碼甚至做空、跌深了加碼——
在高點區的表現與趨勢跟隨南轅北轍，必須獨立驗證。

**對稱測試**：每個策略都跑純多、純空、多空三種版本，不預先排除做空。
分段一律含 2011-2015 空頭與 2024-2026 高點區。

用法：python mean_reversion.py
"""
import sys
import engine
from engine import run_scaled, sma, monthly
from gold_data import fetch, ymd

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

engine.COST = 0.001


def zscore_sig(bars, win=200, entry=2.0, mode="both", monthly_check=False):
    """Z-score 均值回歸：價格偏離均線超過 entry 個標準差就反向押注。

    mode: 'long'（只在超跌時做多）/ 'short'（只在超漲時做空）/ 'both'
    """
    C = [b["c"] for b in bars]
    T = [b["t"] for b in bars]
    ma = sma(C, win)
    s = [None] * len(C)
    for i in range(len(C)):
        if i < win or ma[i] is None:
            continue
        w = C[i - win:i]
        m = ma[i]
        var = sum((x - m) ** 2 for x in w) / len(w)
        sd = var ** 0.5
        if sd <= 0:
            s[i] = 0.0
            continue
        z = (C[i] - m) / sd
        if z <= -entry:
            s[i] = 1.0 if mode in ("long", "both") else 0.0
        elif z >= entry:
            s[i] = -1.0 if mode in ("short", "both") else 0.0
        else:
            s[i] = 0.0
    return monthly(s, T) if monthly_check else s


def rsi(C, n=14):
    out, up, dn = [None] * len(C), 0.0, 0.0
    for i in range(1, len(C)):
        d = C[i] - C[i - 1]
        u, v = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            up += u / n
            dn += v / n
            if i == n:
                out[i] = 100 - 100 / (1 + (up / dn if dn else 999))
        else:
            up = (up * (n - 1) + u) / n
            dn = (dn * (n - 1) + v) / n
            out[i] = 100 - 100 / (1 + (up / dn if dn else 999))
    return out


def rsi_sig(bars, n=14, lo=30, hi=70, mode="both"):
    """RSI 極值反轉：超賣做多、超買做空，回到中性就平倉。"""
    C = [b["c"] for b in bars]
    r = rsi(C, n)
    s, pos = [None] * len(C), 0.0
    for i in range(len(C)):
        if r[i] is None:
            continue
        if r[i] <= lo:
            pos = 1.0 if mode in ("long", "both") else 0.0
        elif r[i] >= hi:
            pos = -1.0 if mode in ("short", "both") else 0.0
        elif 45 <= r[i] <= 55:
            pos = 0.0
        s[i] = pos
    return s


def bollinger_sig(bars, win=20, k=2.0, mode="both"):
    """布林通道回歸：跌破下軌做多、突破上軌做空，回到中線平倉。"""
    C = [b["c"] for b in bars]
    ma = sma(C, win)
    s, pos = [None] * len(C), 0.0
    for i in range(len(C)):
        if i < win or ma[i] is None:
            continue
        w = C[i - win:i]
        m = ma[i]
        sd = (sum((x - m) ** 2 for x in w) / len(w)) ** 0.5
        if C[i] < m - k * sd:
            pos = 1.0 if mode in ("long", "both") else 0.0
        elif C[i] > m + k * sd:
            pos = -1.0 if mode in ("short", "both") else 0.0
        elif abs(C[i] - m) < 0.25 * sd:
            pos = 0.0
        s[i] = pos
    return s


SEGS = [("2000-2011 大多頭", "2000-08-30", "2011-09-05"),
        ("2011-2015 大空頭", "2011-09-05", "2015-12-17"),
        ("2015-2019 盤整", "2015-12-17", "2019-06-01"),
        ("2019-2024 多頭", "2019-06-01", "2024-11-01"),
        ("2024-2026 高點區", "2024-11-01", "2026-09-11")]

for sym in ["GC=F"]:
    bars = fetch(sym)
    T = [b["t"] for b in bars]
    N = len(bars)

    def idx(d):
        return next((i for i, t in enumerate(T) if ymd(t) >= d), N - 1)

    defs = [("買進持有", [1.0] * N)]
    for mode, tag in [("long", "純多"), ("short", "純空"), ("both", "多空")]:
        defs.append(("Z-score200/2 " + tag, zscore_sig(bars, 200, 2.0, mode)))
    for mode, tag in [("long", "純多"), ("short", "純空"), ("both", "多空")]:
        defs.append(("RSI14 30/70 " + tag, rsi_sig(bars, 14, 30, 70, mode)))
    for mode, tag in [("long", "純多"), ("short", "純空"), ("both", "多空")]:
        defs.append(("布林20/2 " + tag, bollinger_sig(bars, 20, 2.0, mode)))

    print("=== %s 均值回歸類・全期 %s ~ %s（成本單趟 0.1%%）===" % (sym, ymd(T[0]), ymd(T[-1])))
    print("%-20s %10s %9s %7s %9s" % ("", "複利報酬", "最大回撤", "換手", "報酬/回撤"))
    print("-" * 62)
    res = []
    for nm, s in defs:
        r = run_scaled(bars, s, nm)
        res.append((nm, s, r))
        print("%-20s %9.1f%% %8.1f%% %7d %9.2f" % (nm, r["ret"], r["mdd"], r["n"], r["rr"]))

    print("\n分段報酬（複利 %）")
    hdr = "%-20s" % ""
    for nm, _, _ in [(s[0], 0, 0) for s in [(x,) for x in SEGS]]:
        pass
    hdr = "%-20s" % "策略"
    for nm, a, b in SEGS:
        hdr += " %16s" % nm
    print(hdr)
    print("-" * 104)
    for nm, s, _ in res:
        line = "%-20s" % nm
        for _, a, b in SEGS:
            rr = run_scaled(bars, s, lo=idx(a), hi=idx(b))
            line += " %15.1f%%" % rr["ret"]
        print(line)
