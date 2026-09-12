# -*- coding: utf-8 -*-
"""共用回測引擎。

成交假設：**這根收盤產生訊號、下一根開盤成交**。不要改成當根收盤成交，
那會用到當下還不知道的價格，回測會虛胖。

成本：單趟 COST，一進一出扣兩次。日線低頻策略成本影響小，
但不扣就會讓高頻的參數看起來假性地好，一律要扣。
"""
from gold_data import ym

COST = 0.001          # 單趟 0.1%


def sma(src, n):
    out, s = [None] * len(src), 0.0
    for i, v in enumerate(src):
        s += v
        if i >= n:
            s -= src[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def month_ends(T):
    """每月最後一個交易日的索引集合。"""
    N = len(T)
    return set(i for i in range(N) if i == N - 1 or ym(T[i]) != ym(T[i + 1]))


def monthly(sig, T):
    """把日頻訊號壓成月頻：只有月底那天能改變部位。

    Faber 200MA 與 TSMOM 的原始規格都是月度檢查。寫成日檢會得到
    完全不同（而且錯誤）的結論——見 research/README.md。
    """
    me = month_ends(T)
    out, cur = [None] * len(sig), None
    for i in range(len(sig)):
        if i in me and sig[i] is not None:
            cur = sig[i]
        out[i] = cur
    return out


def run(bars, sig, name="", lo=0, hi=None):
    """sig[i] = 這根收盤後想要的部位 (1 多 / 0 空手 / -1 空)，下一根開盤成交。"""
    C = [b["c"] for b in bars]
    O = [b["o"] for b in bars]
    T = [b["t"] for b in bars]
    N = len(bars)
    hi = N if hi is None else hi

    eq, pos, entry = 1.0, 0, 0.0
    trades, curve = [], []
    peak, mdd = 1.0, 0.0

    for i in range(max(lo, 0), min(hi, N) - 1):
        want = sig[i] if sig[i] is not None else pos
        if want != pos:
            px = O[i + 1]
            if pos != 0:
                r = (px / entry - 1) * pos
                eq *= (1 + r - 2 * COST)
                trades.append({"ret": (r - 2 * COST) * 100, "dir": pos, "t": T[i + 1]})
            pos, entry = want, px
        v = eq * (1 + (C[i + 1] / entry - 1) * pos) if pos != 0 else eq
        curve.append(v)
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > mdd:
            mdd = dd

    if pos != 0:
        j = min(hi, N) - 1
        r = (C[j] / entry - 1) * pos
        eq *= (1 + r - 2 * COST)
        trades.append({"ret": (r - 2 * COST) * 100, "dir": pos, "t": T[j]})

    wins = [t for t in trades if t["ret"] > 0]
    gp = sum(t["ret"] for t in wins)
    gl = abs(sum(t["ret"] for t in trades if t["ret"] <= 0))
    yrs = (T[min(hi, N) - 1] - T[max(lo, 0)]) / 864e5 / 365
    return {
        "name": name, "ret": (eq - 1) * 100, "mdd": mdd, "n": len(trades),
        "月頻": yrs * 12 / len(trades) if trades else None,
        "pf": gp / gl if gl else None,
        "勝率": len(wins) / len(trades) * 100 if trades else None,
        "rr": ((eq - 1) * 100 / mdd) if mdd else 0,
        "trades": trades, "curve": curve,
    }


def buy_hold(bars, lo=0, hi=None):
    C = [b["c"] for b in bars]
    hi = len(C) if hi is None else hi
    seg = C[lo:hi]
    peak, mdd = seg[0], 0.0
    for v in seg:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > mdd:
            mdd = dd
    ret = (seg[-1] / seg[0] - 1) * 100
    return {"name": "買進持有", "ret": ret, "mdd": mdd, "n": 1, "月頻": None,
            "pf": None, "勝率": None, "rr": ret / mdd if mdd else 0,
            "trades": [], "curve": [v / seg[0] for v in seg]}


# ---------------- 策略訊號 ----------------

def sig_ma(bars, days, allow_short, monthly_check=True):
    """均線擇時：收盤在均線之上持有。Faber 原版是 10 個月均線＋月度檢查。"""
    C = [b["c"] for b in bars]
    T = [b["t"] for b in bars]
    ma = sma(C, days)
    s = [None if ma[i] is None else (1 if C[i] > ma[i] else (-1 if allow_short else 0))
         for i in range(len(C))]
    return monthly(s, T) if monthly_check else s


def sig_tsmom(bars, lb_months, allow_short, monthly_check=True):
    """時間序列動量：過去 N 個月報酬為正則做多。標準設定 12 個月＋月度再平衡。"""
    C = [b["c"] for b in bars]
    T = [b["t"] for b in bars]
    LB = int(lb_months * 21)
    s = [None if i < LB else (1 if C[i] > C[i - LB] else (-1 if allow_short else 0))
         for i in range(len(C))]
    return monthly(s, T) if monthly_check else s


def sig_donchian(bars, n_in, n_out, allow_short):
    """海龜通道突破：N 日新高進場、M 日新低出場。本來就是日頻，不要改月頻。"""
    C = [b["c"] for b in bars]
    N = len(C)
    sig, pos = [None] * N, 0
    for i in range(N):
        if i < max(n_in, n_out):
            sig[i] = None
            continue
        hh, ll = max(C[i - n_in:i]), min(C[i - n_in:i])
        ho, lo_ = max(C[i - n_out:i]), min(C[i - n_out:i])
        if pos == 0:
            if C[i] > hh:
                pos = 1
            elif allow_short and C[i] < ll:
                pos = -1
        elif pos == 1:
            if C[i] < lo_:
                pos = -1 if (allow_short and C[i] < ll) else 0
        else:
            if C[i] > ho:
                pos = 1 if C[i] > hh else 0
        sig[i] = pos
    return sig
