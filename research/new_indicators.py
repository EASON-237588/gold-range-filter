# -*- coding: utf-8 -*-
"""兩個自創指標，針對「大空頭 vs 一般回檔」的區分。

為什麼要新指標：均線與單一尺度動量都只回答「現在 vs 過去某一點」，
看不到「這次下跌有多廣、多持久」。而 2026-09-13 的驗證顯示，擇時唯一
穩定成立的能力是大空頭保護，所以能不能分辨大空頭與一般回檔就是關鍵。

刻意的自我約束（否則就是換個方式過擬合）：
  * 不引入可調的門檻參數，時間尺度一律用現成策略的標準值（1/3/6/12 個月、252 日）。
  * 分級部位直接用「幾個條件成立」的比例，不另外挑係數。
  * 一律月頻檢查、成本按部位變化量計。

用法：python new_indicators.py
"""
import sys
from gold_data import fetch, ymd
from engine import run_scaled, monthly, sig_tsmom, sig_dual_confirm

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def sig_momentum_breadth(bars, months=(1, 3, 6, 12)):
    """動量廣度：1/3/6/12 個月動量有幾個為正，直接當部位比例。

    一般回檔只打掉短天期（廣度 0.5~0.75），大空頭會讓全部轉負（廣度 0）。
    部位 = 為正的比例，所以是天然的分級，不需要挑門檻。
    """
    C = [b["c"] for b in bars]
    T = [b["t"] for b in bars]
    lbs = [int(m * 21) for m in months]
    s = [None] * len(C)
    for i in range(len(C)):
        if i < max(lbs):
            continue
        s[i] = sum(1 for L in lbs if C[i] > C[i - L]) / float(len(lbs))
    return monthly(s, T)


def sig_high_density(bars, win=252, near=0.95):
    """新高密度：過去一年有多少比例的日子收在年度高點的 95% 以上。

    多頭期頻繁貼近新高、空頭期幾乎不貼近。這是價格位置看不到的資訊：
    同樣「跌破均線」，在高密度環境是回檔，在低密度環境是趨勢已死。

    密度本身就落在 0~1，直接當部位比例，一樣不挑門檻。
    """
    import bisect
    C = [b["c"] for b in bars]
    T = [b["t"] for b in bars]
    s = [None] * len(C)
    for i in range(len(C)):
        if i < win:
            continue
        w = C[i - win:i + 1]
        hi = max(w)
        s[i] = sum(1 for v in w if v >= hi * near) / float(len(w))

    # 密度的絕對值偏低（多頭期約 0.2~0.4），要除以自身的歷史中位數做正規化。
    # **中位數只能用「到當下為止」的歷史**——用整個樣本算會把未來資訊洩進回測，
    # 那個除數在實盤根本算不出來。前 MIN_HIST 筆樣本太少、中位數不穩，一律不進場。
    MIN_HIST = 252
    hist, out = [], [None] * len(s)
    for i, v in enumerate(s):
        if v is None:
            continue
        bisect.insort(hist, v)
        if len(hist) < MIN_HIST:
            out[i] = 0.0
            continue
        med = hist[len(hist) // 2]
        out[i] = 0.0 if med <= 0 else max(0.0, min(1.0, v / (med * 2)))
    return monthly(out, T)


def sig_breadth_x_density(bars):
    """兩個新指標相乘：都健康才滿倉，任一轉弱就減碼。"""
    a = sig_momentum_breadth(bars)
    b = sig_high_density(bars)
    return [None if (a[i] is None or b[i] is None) else a[i] * b[i]
            for i in range(len(a))]


def build(bars):
    return [
        ("買進持有",            [1.0] * len(bars)),
        ("動量廣度",            sig_momentum_breadth(bars)),
        ("新高密度",            sig_high_density(bars)),
        ("廣度 × 密度",         sig_breadth_x_density(bars)),
        ("TSMOM12 只做多",      sig_tsmom(bars, 12, False)),
        ("雙確認 AND",          sig_dual_confirm(bars, mode="and")),
    ]


def show(title, bars, lo=0, hi=None):
    print(title)
    print("%-20s %10s %8s %6s %8s %9s" % ("策略", "複利報酬", "最大回撤", "換手", "月頻", "報酬/回撤"))
    print("-" * 68)
    for name, sig in build(bars):
        r = run_scaled(bars, sig, name, lo, hi)
        print("%-20s %9.1f%% %7.1f%% %6d %8s %9.2f"
              % (name, r["ret"], r["mdd"], r["n"],
                 "%.1f" % r["月頻"] if r["月頻"] else "—", r["rr"]))
    print()


def main():
    for sym in ["GC=F", "GLD"]:
        bars = fetch(sym)
        T = [b["t"] for b in bars]
        N = len(bars)
        show("=== %s 全期  %s ~ %s ===" % (sym, ymd(T[0]), ymd(T[-1])), bars)
        mid = N // 2
        show("--- %s 後半（%s 起）← 決定性的一段 ---" % (sym, ymd(T[mid])), bars, mid, N)

    bars = fetch("GC=F")
    T = [b["t"] for b in bars]

    def idx_of(d):
        for i, t in enumerate(T):
            if ymd(t) >= d:
                return i
        return len(T) - 1

    show("=== GC=F 2011-09 ~ 2015-12 大空頭 ===",
         bars, idx_of("2011-09-05"), idx_of("2015-12-17"))
    show("=== GC=F 2019-06 ~ 2026-09 近期多頭（檢查有沒有拖累）===",
         bars, idx_of("2019-06-01"), len(T) - 1)


# 這些函式會被其他腳本 import，執行段一定要包在 main 裡，
# 否則每次 import 都會重跑一整輪回測。
if __name__ == "__main__":
    main()
