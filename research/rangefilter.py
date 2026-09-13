# -*- coding: utf-8 -*-
"""Range Filter —— index.html 的 compute() 與 backtest() 的 Python 移植。

搬過來的目的有二：
  1. 讓 RF 跟其他策略跑在同一個引擎、同一種回撤定義上，才能公平比較。
  2. 讓 RF 能放到 GC=F 26 年含空頭的樣本上測——它至今從未在空頭段被驗證過，
     因為 Binance 的 PAXG 只有 2020 年之後。

**移植必須逐項對得上，否則比較沒有意義。** 對照方式見 verify() 與
compare_rf.py：用同一份資料、同一種（儀表板的）回測算法，比對筆數與損益。

兩個容易搞錯的地方：
  * 暖機：前 6×per 根的訊號一律丟棄。不丟的話前段全是假訊號，會優化出相反結論。
  * session：PAXG 是 24/7，不剔除休市就沒有週末跳空，smoothrng 會偏小、
    通道偏窄、訊號暴增，跟 TVC:GOLD / XAUUSD 對不起來。
"""
import datetime
import time

UTC = datetime.timezone.utc


# ---------------- 美國夏令時 ----------------
# Windows 的 Python 沒有內建時區資料庫（zoneinfo 需要另外裝 tzdata），
# 而這個 research 資料夾要在三台電腦上跑，所以自己算，不加依賴。
# 規則在 2007 年改過一次，GC=F 的資料從 2000 年起，兩套都需要。

def _nth_weekday(year, month, weekday, n):
    """該月第 n 個星期 weekday（Python 慣例：週一=0 … 週日=6）。"""
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(weekday - d.weekday()) % 7)
    return d + datetime.timedelta(days=7 * (n - 1))


def _last_weekday(year, month, weekday):
    """該月最後一個星期 weekday。"""
    if month == 12:
        d = datetime.date(year + 1, 1, 1)
    else:
        d = datetime.date(year, month + 1, 1)
    d -= datetime.timedelta(days=1)
    return d - datetime.timedelta(days=(d.weekday() - weekday) % 7)


def _ny_offset_hours(dt_utc):
    """紐約時間相對 UTC 的偏移：夏令 -4、冬令 -5。"""
    y = dt_utc.year
    if y >= 2007:
        start = _nth_weekday(y, 3, 6, 2)      # 3 月第二個週日
        end = _nth_weekday(y, 11, 6, 1)       # 11 月第一個週日
    else:
        start = _nth_weekday(y, 4, 6, 1)      # 4 月第一個週日（2006 年以前）
        end = _last_weekday(y, 10, 6)         # 10 月最後一個週日
    # 切換都發生在當地 02:00：春天 02:00 EST = 07:00 UTC、秋天 02:00 EDT = 06:00 UTC
    s = datetime.datetime.combine(start, datetime.time(7), tzinfo=UTC)
    e = datetime.datetime.combine(end, datetime.time(6), tzinfo=UTC)
    return -4 if s <= dt_utc < e else -5


def to_ny(ms):
    dt = datetime.datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    return dt + datetime.timedelta(hours=_ny_offset_hours(dt))


# ---------------- session ----------------

def gold_open_legacy(ms):
    """index.html 目前的版本：UTC 時刻寫死，**沒有處理美國夏令時**。

    只有夏令時（3 月中～11 月初）是對的；冬令時那約四個月，每天有一小時
    的 K 線被錯誤分類。保留它唯一的用途是驗證 Python 移植跟儀表板一致。
    """
    tm = time.gmtime(ms / 1000.0)
    day = (tm.tm_wday + 1) % 7        # Python 週一=0 → 轉成 JS 的週日=0
    h = tm.tm_hour
    if day == 6:
        return False                  # 週六全休
    if day == 0 and h < 22:
        return False                  # 週日 22:00 前未開盤
    if day == 5 and h >= 21:
        return False                  # 週五 21:00 後收盤
    if h == 21:
        return False                  # 每日休息一小時
    return True


def gold_open(ms):
    """正確版：以紐約時間判定，夏令時自動跟著移動。

    黃金現貨的實際規則：週日 18:00 ET 開盤 → 週五 17:00 ET 收盤，
    每日 17:00-18:00 ET 休息。換成 UTC 會隨夏令時差一小時，
    所以必須用時區換算，不能寫死 UTC 時刻。
    """
    dt = to_ny(ms)
    day, h = dt.weekday(), dt.hour     # weekday: 週一=0 … 週六=5、週日=6
    if day == 5:
        return False                   # 週六全休
    if day == 6 and h < 18:
        return False                   # 週日 18:00 ET 前未開盤
    if day == 4 and h >= 17:
        return False                   # 週五 17:00 ET 後收盤
    if h == 17:
        return False                   # 每日休息一小時
    return True


def apply_session(bars, on=True, legacy=False):
    if not on:
        return list(bars)
    f = gold_open_legacy if legacy else gold_open
    return [b for b in bars if f(b["t"])]


# ---------------- 指標 ----------------

def ema(src, length):
    a = 2.0 / (length + 1)
    out, prev = [None] * len(src), None
    for i, v in enumerate(src):
        if v is None:
            out[i] = prev
            continue
        prev = v if prev is None else a * v + (1 - a) * prev
        out[i] = prev
    return out


def smoothrng(x, t, m):
    diff = [0.0 if i == 0 else abs(x[i] - x[i - 1]) for i in range(len(x))]
    avrng = ema(diff, t)
    wper = t * 2 - 1
    return [None if v is None else v * m for v in ema(avrng, wper)]


def rngfilt(x, r):
    """對應 Pine 的遞迴，bar0 的 nz(rngfilt[1]) 視為 0。"""
    out, prev = [0.0] * len(x), 0.0
    for i in range(len(x)):
        xi = x[i]
        ri = r[i] if r[i] is not None else 0.0
        if xi > prev:
            f = prev if (xi - ri < prev) else xi - ri
        else:
            f = prev if (xi + ri > prev) else xi + ri
        out[i] = f
        prev = f
    return out


def compute(bars, per=100, mult=23.0, src_mode="hl2"):
    """回傳 {'sig': [...], 'filt': [...], 'warm': n}。sig：1 買、-1 賣、0 無。"""
    n = len(bars)
    if src_mode == "close":
        src = [b["c"] for b in bars]
    elif src_mode == "hlc3":
        src = [(b["h"] + b["l"] + b["c"]) / 3.0 for b in bars]
    else:
        src = [(b["h"] + b["l"]) / 2.0 for b in bars]

    smrng = smoothrng(src, per, mult)
    filt = rngfilt(src, smrng)

    upward, downward = [0] * n, [0] * n
    for i in range(n):
        pu = upward[i - 1] if i else 0
        pd = downward[i - 1] if i else 0
        pf = filt[i - 1] if i else filt[0]
        upward[i] = pu + 1 if filt[i] > pf else (0 if filt[i] < pf else pu)
        downward[i] = pd + 1 if filt[i] < pf else (0 if filt[i] > pf else pd)

    sig = [0] * n
    cond_ini = 0
    for i in range(n):
        rose = i > 0 and src[i] > src[i - 1]
        fell = i > 0 and src[i] < src[i - 1]
        L = src[i] > filt[i] and (rose or fell) and upward[i] > 0
        S = src[i] < filt[i] and (rose or fell) and downward[i] > 0
        prev_ini = cond_ini
        if L:
            cond_ini = 1
        elif S:
            cond_ini = -1
        if L and prev_ini == -1:
            sig[i] = 1
        if S and prev_ini == 1:
            sig[i] = -1

    # 暖機區（內層 EMA 尚未收斂、通道偏窄）的訊號一律丟棄
    warm = min(6 * per, n)
    for i in range(warm):
        sig[i] = 0
    return {"sig": sig, "filt": filt, "warm": warm}


# ---------------- 部位 / 回測 ----------------

def to_position(sig, long_only):
    """把事件訊號轉成逐根部位，給 engine.run_scaled 用（它會在下一根成交）。"""
    out, pos = [0.0] * len(sig), 0.0
    for i, s in enumerate(sig):
        if s == 1:
            pos = 1.0
        elif s == -1:
            pos = 0.0 if long_only else -1.0
        out[i] = pos
    return out


def backtest_dashboard(bars, sig, long_only=False, cost=0.115):
    """完全照 index.html 的 backtest() 重寫，**只用於驗證移植是否正確**。

    注意它的兩個特性，正是不能拿它的回撤跟其他策略比較的原因：
      * 用當根收盤價成交（訊號要收盤才知道，卻用收盤價成交，有前瞻偏差）
      * 最大回撤只用「已平倉交易的單利累積損益」算，持倉期間的浮動虧損不計
    """
    trades, pos = [], None
    for i, b in enumerate(bars):
        if pos is not None:
            if sig[i] != 0 and sig[i] != pos["dir"]:
                exit_px = b["c"]
                d = pos["dir"]
                gross = (exit_px / pos["entry"] - 1) * 100 if d > 0 \
                    else (pos["entry"] / exit_px - 1) * 100
                trades.append({"ret": gross - 2 * cost, "dir": d, "i": i})
                pos = None
        if pos is None and sig[i] != 0 and not (long_only and sig[i] < 0):
            pos = {"dir": sig[i], "entry": b["c"], "i": i}

    eq = peak = mdd = 0.0
    for t in trades:
        eq += t["ret"]
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    wins = [t for t in trades if t["ret"] > 0]
    gp = sum(t["ret"] for t in wins)
    gl = abs(sum(t["ret"] for t in trades if t["ret"] <= 0))
    return {"n": len(trades), "net": eq, "mdd": mdd,
            "pf": gp / gl if gl else None,
            "winRate": len(wins) / len(trades) * 100 if trades else None,
            "shorts": sum(1 for t in trades if t["dir"] < 0),
            "shortPnl": sum(t["ret"] for t in trades if t["dir"] < 0),
            "longPnl": sum(t["ret"] for t in trades if t["dir"] > 0),
            "trades": trades}
