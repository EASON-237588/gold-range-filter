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


def run_scaled(bars, sig, name="", lo=0, hi=None):
    """逐日權益版，支援分數部位（0.5 這種）。

    run() 用的是交易配對法，只能處理全額進出。要比較分級部位就得用這個。
    成本按**部位變化量**計算（1.0→0.5 只扣一半），比 run() 的全額扣法公平。

    數字會跟 run() 有微小差異（這裡用收盤到收盤、run() 用次根開盤成交），
    所以要比較時請讓所有策略都走同一個函式，不要混用。
    """
    C = [b["c"] for b in bars]
    T = [b["t"] for b in bars]
    N = len(bars)
    hi = N if hi is None else hi
    lo = max(lo, 0)

    eq, pos = 1.0, 0.0
    peak, mdd = 1.0, 0.0
    curve, switches = [], 0

    for i in range(lo, min(hi, N) - 1):
        want = sig[i] if sig[i] is not None else pos
        want = float(want)
        if want != pos:
            eq *= (1 - abs(want - pos) * COST)
            switches += 1
            pos = want
        eq *= (1 + pos * (C[i + 1] / C[i] - 1))
        curve.append(eq)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > mdd:
            mdd = dd

    yrs = (T[min(hi, N) - 1] - T[lo]) / 864e5 / 365
    return {"name": name, "ret": (eq - 1) * 100, "mdd": mdd, "n": switches,
            "月頻": yrs * 12 / switches if switches else None,
            "rr": ((eq - 1) * 100 / mdd) if mdd else 0,
            "curve": curve, "pf": None, "勝率": None, "trades": []}


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


def sig_dual_confirm(bars, lb_months=12, ma_days=200, mode="and"):
    """雙確認防護：預設持有，只有動量與均線「同時」轉空才出場。

    設計依據（2026-09-13 的驗證結論）：
      * 買進持有是黃金最強的基準，所以預設狀態必須是持有，不是空手。
      * 擇時唯一穩定成立的能力是大空頭保護，所以出場門檻要嚴。
      * 大空頭時兩個條件必然同時成立；多頭段的假訊號很難兩個一起觸發。
        這個非對稱性是白撿的，不需要額外參數去調。

    刻意不引入任何新參數：12 個月動量與 200 日均線都是現成策略的標準設定。

    mode="and"   兩個都轉空才出場（保守，保留多頭段）
    mode="or"    任一轉空就出場（敏感，接近 Faber/TSMOM 的行為）
    mode="scale" 分級部位：都看多 100%、一個看多 50%、都看空 0%
    """
    C = [b["c"] for b in bars]
    T = [b["t"] for b in bars]
    LB = int(lb_months * 21)
    ma = sma(C, ma_days)
    s = [None] * len(C)
    for i in range(len(C)):
        if i < LB or ma[i] is None:
            continue
        mom_ok = C[i] > C[i - LB]
        ma_ok = C[i] > ma[i]
        if mode == "and":
            s[i] = 0 if (not mom_ok and not ma_ok) else 1
        elif mode == "or":
            s[i] = 1 if (mom_ok and ma_ok) else 0
        else:
            s[i] = 1.0 if (mom_ok and ma_ok) else (0.5 if (mom_ok or ma_ok) else 0.0)
    return monthly(s, T)


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
