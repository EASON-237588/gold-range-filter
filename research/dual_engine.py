# -*- coding: utf-8 -*-
"""多空雙向 × 分批加倉 × 硬停損 的回測引擎。

跟這個專案先前所有回測的差別，在於**方向與部位是分開的兩層**：

  方向層  只回答三件事之一：做多 / 做空 / 空手。可以插不同的訊號進來比較。
  部位層  獨立管理 0~5 段的加減碼、硬停損、反轉全平。方向層不知道部位層在幹嘛。

為什麼要拆開：先前的策略都是「訊號翻向就全額反手」，等於部位層只有 0 和 1 兩個值，
一次進出的曝險就是全部，沒有任何轉圜餘地——那正是「一次畢業」的結構。
拆開之後，做空不再只是「反向的做多」，它有自己的加碼節奏與退出紀律。

兩種加倉方向都實作，用回測決定，不預設立場：
  順勢金字塔  浮盈每達到 step×ATR 加一段。最大虧損鎖在第一段，抗一次畢業。
  逆勢攤平    浮虧每達到 step×ATR 加一段。勝率高、小賺頻繁，但單筆最大虧損隨段數放大，
              必須配硬停損才能測——沒有停損的攤平在數學上就是遲早歸零。

出場只有兩種（依使用者 2026-09-13 的決定）：方向訊號反轉、或觸及硬停損。
**不主動停利**，讓大波段抱住。

成本按部位變化量計：加一段扣一段的錢，不是每次都扣整筆。
"""
import math


COST_ONE_WAY = 0.115          # % 單趟，實測值


# ---------------------------------------------------------------- 指標

def atr(bars, n=14):
    """Wilder ATR，回傳與 bars 等長的陣列（前 n 根為 None）。"""
    tr = [None] * len(bars)
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    out = [None] * len(bars)
    if len(bars) <= n:
        return out
    seed = sum(tr[1:n + 1]) / n
    out[n] = seed
    for i in range(n + 1, len(bars)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def roll_max(x, n):
    """長度 n 的滑動最大值（不含當根，out[i] = max(x[i-n:i])），單調佇列 O(n)。
    掃描時 n 會拉到 300、資料五萬根，每根重算 max(切片) 是 O(n*w)，慢到跑不完。"""
    out = [None] * len(x)
    dq = []                       # 存 index，對應值遞減
    for i in range(len(x)):
        if i >= n:
            out[i] = x[dq[0]]
        while dq and x[dq[-1]] <= x[i]:
            dq.pop()
        dq.append(i)
        if dq[0] <= i - n:
            dq.pop(0)
    return out


def roll_min(x, n):
    out = [None] * len(x)
    dq = []
    for i in range(len(x)):
        if i >= n:
            out[i] = x[dq[0]]
        while dq and x[dq[-1]] >= x[i]:
            dq.pop()
        dq.append(i)
        if dq[0] <= i - n:
            dq.pop(0)
    return out


# ---------------------------------------------------------------- 方向訊號
# 每支都回傳與 bars 等長的 +1 / -1 / 0 陣列。0 = 空手，不是「維持前一個方向」。

def dir_donchian(bars, n=55, exit_n=20, reverse=False):
    """突破 n 根高點做多、跌破 n 根低點做空；跌破 exit_n 根低點（多單）就回到空手。

    經典結構，多空天然對稱，沒有需要爭論的門檻。放在這裡當管線的對照組。

    reverse=True 走**反轉系統**：拿掉「回到空手」那條規則，訊號翻轉直接反手、永遠在場。
    儀表板 V2 的「多空都做」用的是這個模式，掃描要對齊才有意義。
    """
    C = [b["c"] for b in bars]
    H = [b["h"] for b in bars]
    L = [b["l"] for b in bars]
    HH = roll_max(H, n); LL = roll_min(L, n)
    HE = roll_max(H, exit_n); LE = roll_min(L, exit_n)
    out = [0] * len(bars)
    cur = 0
    for i in range(len(bars)):
        if i < n:
            continue
        hh = HH[i]; ll = LL[i]
        he = HE[i]; le = LE[i]
        if C[i] > hh:
            cur = 1
        elif C[i] < ll:
            cur = -1
        elif (not reverse) and cur == 1 and C[i] < le:
            cur = 0
        elif (not reverse) and cur == -1 and C[i] > he:
            cur = 0
        out[i] = cur
    return out


def dir_ema_slope(bars, fast=20, slow=60, atr_n=14, thresh=0.25):
    """快慢均線的距離除以 ATR，超過門檻才認方向，否則空手。

    用 ATR 正規化的意義：同樣是「快線在慢線上方」，在低波動時可能只是雜訊，
    在高波動時才是真的分開了。除以 ATR 讓門檻在不同波動環境下是同一件事。
    """
    C = [b["c"] for b in bars]
    A = atr(bars, atr_n)
    ef = [None] * len(C); es = [None] * len(C)
    kf = 2.0 / (fast + 1); ks = 2.0 / (slow + 1)
    for i, c in enumerate(C):
        ef[i] = c if i == 0 else ef[i - 1] + kf * (c - ef[i - 1])
        es[i] = c if i == 0 else es[i - 1] + ks * (c - es[i - 1])
    out = [0] * len(C)
    for i in range(len(C)):
        if A[i] is None or A[i] <= 0 or i < slow:
            continue
        z = (ef[i] - es[i]) / A[i]
        out[i] = 1 if z > thresh else (-1 if z < -thresh else 0)
    return out


# ---------------------------------------------------------------- 回測

def backtest(bars, direction, mode="pyramid", segs=5, step_atr=1.0,
             stop_atr=3.0, atr_n=14, cost=COST_ONE_WAY, seg_frac=None, atr_arr=None):
    """逐根複利回測。

    mode      "pyramid" 順勢加碼 / "average" 逆勢攤平 / "single" 不分批（對照組）
    segs      最多幾段
    step_atr  每隔幾個 ATR 加一段（順勢看浮盈、逆勢看浮虧）
    stop_atr  以**平均成本**計，反向走幾個 ATR 全平
    seg_frac  每段佔總部位的比例，預設平均分配

    回撤用逐根權益計算，含持倉期間的浮動虧損——這才是實際要承受的東西。
    先前 index.html 的 backtest() 只用已平倉交易算回撤，會低估。
    """
    n = len(bars)
    A = atr_arr if atr_arr is not None else atr(bars, atr_n)
    # 對照組必須是**滿倉**一次進出，否則它只開第一段（20%），報酬與回撤都被縮小五倍，
    # 跟分批模式不是同一個曝險基準，比較沒有意義。
    if mode == "single":
        segs, seg_frac = 1, [1.0]
    elif seg_frac is None:
        seg_frac = [1.0 / segs] * segs

    eq = 1.0
    pos = 0.0            # -1 ~ +1
    side = 0             # 0 空手 / +1 多 / -1 空
    filled = 0           # 已建立幾段
    avg = 0.0            # 平均成本
    last_add = 0.0       # 上次加段時的價格
    peak = 1.0
    mdd = 0.0
    trades = []
    leg = None
    curve = [0.0]
    stops = 0
    blocked = 0          # 剛被停損掉的方向，訊號沒換過之前不准用同一個方向重進

    def close_leg(i, why):
        """單筆報酬要用**平均成本**與**實際部位**算，否則三種加倉模式會印出一模一樣的
        數字——那只反映第一段的進出價，跟加了幾段完全無關。這裡算的是這一筆對權益的
        百分比貢獻（含來回成本），可以直接橫向比較。"""
        nonlocal leg, pos, side, filled, avg
        if leg is not None:
            w = sum(seg_frac[:filled])
            gross = (bars[i]["c"] / avg - 1) * 100 * leg["dir"] * w
            ret = gross - 2 * cost * w
            leg.update(exit=bars[i]["c"], exitIdx=i, why=why, ret=ret, gross=gross,
                       avg=avg, weight=w, held=i - leg["idx"], segs=filled)
            trades.append(leg)
        leg = None
        # **不要在這裡把 pos 歸零。** 外層是用 `if target != pos` 來決定要不要扣
        # 交易成本的；先把 pos 改成 0，target 也是 0，判定就變成「部位沒變」，
        # 平倉那一次的成本整個漏掉。實測 4 小時 14 筆少扣 1.3pp（JS 移植版對照
        # 才發現）。部位一律交給外層的 target 維護。
        side = 0
        filled = 0
        avg = 0.0

    for i in range(n - 1):
        d = direction[i]
        a = A[i]
        c = bars[i]["c"]
        target = pos

        if a is not None and a > 0:
            # 方向訊號換過了，解除封鎖
            if blocked != 0 and d != blocked:
                blocked = 0

            # 1. 硬停損優先於一切
            if side != 0 and filled > 0:
                adverse = (avg - c) * side
                if adverse >= stop_atr * a:
                    blocked = side       # 沒有這行，下面第 3 步會用同一個訊號當根重開，
                                         # 等於扣了成本又原封不動買回來，停損完全失效
                    close_leg(i, "停損")
                    stops += 1
                    target = 0.0
                else:
                    target = pos
            # 2. 方向反轉（含轉為空手）
            if side != 0 and d != side:
                close_leg(i, "訊號反轉")
                target = 0.0
            # 3. 開第一段
            if side == 0 and d != 0 and d != blocked:
                side = d
                filled = 1
                avg = c
                last_add = c
                target = d * seg_frac[0]
                leg = {"dir": d, "entry": c, "idx": i, "t": bars[i]["t"]}
            # 4. 加段
            elif side != 0 and filled < segs:
                move = (c - last_add) * side          # 正=順勢，負=逆勢
                trigger = (move >= step_atr * a) if mode == "pyramid" else \
                          (-move >= step_atr * a) if mode == "average" else False
                if trigger:
                    w_old = sum(seg_frac[:filled])
                    w_new = seg_frac[filled]
                    avg = (avg * w_old + c * w_new) / (w_old + w_new)
                    filled += 1
                    last_add = c
                    target = side * sum(seg_frac[:filled])

        # 成本按部位變化量
        if target != pos:
            eq *= (1 - abs(target - pos) * cost / 100.0)
            pos = target

        # 下一根的損益
        eq *= (1 + pos * (bars[i + 1]["c"] / bars[i]["c"] - 1))
        curve.append((eq - 1) * 100)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > mdd:
            mdd = dd

    closed = trades
    longs = [t for t in closed if t["dir"] > 0]
    shorts = [t for t in closed if t["dir"] < 0]
    wins = [t for t in closed if t["ret"] > 0]
    losses = [t for t in closed if t["ret"] <= 0]
    gp = sum(t["ret"] for t in wins)
    gl = abs(sum(t["ret"] for t in losses))
    net = (eq - 1) * 100

    return {
        "net": net, "mdd": mdd, "total": len(closed), "stops": stops,
        "win": (len(wins) / len(closed) * 100) if closed else None,
        "pf": (gp / gl) if gl else None,
        "long_n": len(longs), "short_n": len(shorts),
        "long_ret": sum(t["ret"] for t in longs),
        "short_ret": sum(t["ret"] for t in shorts),
        "worst": min((t["ret"] for t in closed), default=None),
        "best": max((t["ret"] for t in closed), default=None),
        "avg_held": (sum(t["held"] for t in closed) / len(closed)) if closed else None,
        "avg_segs": (sum(t["segs"] for t in closed) / len(closed)) if closed else None,
        "trades": closed, "curve": curve,
    }


def buy_hold(bars):
    """同一段的買進持有，含逐根回撤——所有結論都要跟它比。"""
    eq0 = bars[0]["c"]
    peak = eq0
    mdd = 0.0
    for b in bars:
        if b["c"] > peak:
            peak = b["c"]
        dd = (peak - b["c"]) / peak * 100
        if dd > mdd:
            mdd = dd
    return {"net": (bars[-1]["c"] / eq0 - 1) * 100, "mdd": mdd}


# ---------------------------------------------------------------- 不對稱回測

def backtest_asym(bars, direction, long_cfg, short_cfg, segs=5, atr_n=14,
                  cost=COST_ONE_WAY, atr_arr=None, carry_annual=0.0,
                  carry_short_factor=0.5, bar_minutes=None):
    """多空各用自己的部位規則。

    為什麼需要這個：跨七個商品（跌幅 29%~95%）與四個熊市段測完，用多單的鏡像規則
    做空一律是負貢獻——BTC 一年跌七成，只做空只賺 0.1%。三個結構性原因：
      空頭反彈又快又猛，逆勢攤平會在反彈時加空單，等於在最糟的時機加碼；
      跌破進場點常常正好是短期底部；
      跌的時候 ATR 放大，同一個 ATR 倍數的停損在空單上自動變寬。
    所以空單需要自己的規則，不是把多單反過來。

    cfg 欄位：
      mode      "average" 逆勢攤平 / "pyramid" 順勢金字塔 / "single" 不分批
      step      每隔幾個 ATR 加一段
      stop_atr  ATR 倍數停損（設 None 表示不用）
      stop_pct  固定百分比停損（設 None 表示不用）；兩者都設時取先觸發的
                空單建議用這個：ATR 在跌勢中放大，用倍數會讓停損自動放寬
      enabled   False 代表這一側的訊號一律當成空手

    carry_annual        外匯特有的隔夜利息（swap），年化 %。做多**高利差劣勢方**要付，
                        這裡的慣例是：正值代表持有多單每年付掉這個百分比。
                        持倉兩週約 10 個交易日，以 2% 年化計約 0.08%——比 EURUSD 的
                        點差（來回約 0.005%）大十幾倍，是外匯真正的主要成本。
                        加密與現貨黃金沒有這一項，預設 0。
    carry_short_factor  做空那一側收到的比例。理論上做空該收到等額利息，但經紀商
                        兩邊都要抽，實務上收到的少於付出的。預設 0.5（收一半）。
    bar_minutes         一根 K 幾分鐘，用來把年化 carry 換算到每根。不給就從資料推。
    """
    n = len(bars)
    A = atr_arr if atr_arr is not None else atr(bars, atr_n)

    # 每根要扣多少 carry。用實際時間差推算，外匯週末有缺口，用根數換算會低估。
    if bar_minutes is None and n > 10:
        diffs = sorted(bars[i + 1]["t"] - bars[i]["t"] for i in range(min(n - 1, 500)))
        bar_minutes = max(1.0, diffs[len(diffs) // 2] / 60000.0)
    year_min = 365.0 * 24 * 60
    carry_per_bar = (carry_annual / 100.0) * (bar_minutes / year_min) if carry_annual else 0.0

    def cfg_of(side):
        return long_cfg if side > 0 else short_cfg

    def fracs(c):
        s = 1 if c.get("mode") == "single" else segs
        return [1.0 / s] * s

    eq = 1.0
    pos = 0.0
    side = 0
    filled = 0
    avg = 0.0
    last_add = 0.0
    peak = 1.0
    mdd = 0.0
    trades = []
    leg = None
    curve = [0.0]
    stops = 0
    blocked = 0
    cur_frac = None
    carry_paid = 0.0

    def close_leg(i, why):
        nonlocal leg, pos, side, filled, avg, cur_frac
        if leg is not None:
            w = sum(cur_frac[:filled])
            gross = (bars[i]["c"] / avg - 1) * 100 * leg["dir"] * w
            leg.update(exit=bars[i]["c"], exitIdx=i, why=why, gross=gross,
                       ret=gross - 2 * cost * w, avg=avg, weight=w,
                       held=i - leg["idx"], segs=filled)
            trades.append(leg)
        leg = None
        # 同上：pos 歸零會讓平倉成本漏扣，交給外層 target 維護
        side = 0
        filled = 0
        avg = 0.0
        cur_frac = None

    for i in range(n - 1):
        d = direction[i]
        a = A[i]
        c = bars[i]["c"]
        target = pos

        if d > 0 and not long_cfg.get("enabled", True):
            d = 0
        if d < 0 and not short_cfg.get("enabled", True):
            d = 0

        if a is not None and a > 0:
            if blocked != 0 and d != blocked:
                blocked = 0

            if side != 0 and filled > 0:
                cf = cfg_of(side)
                adverse = (avg - c) * side
                hit = False
                if cf.get("stop_atr") is not None and adverse >= cf["stop_atr"] * a:
                    hit = True
                if cf.get("stop_pct") is not None and adverse / avg * 100 >= cf["stop_pct"]:
                    hit = True
                if hit:
                    blocked = side
                    close_leg(i, "停損")
                    stops += 1
                    target = 0.0

            if side != 0 and d != side:
                close_leg(i, "訊號反轉")
                target = 0.0

            if side == 0 and d != 0 and d != blocked:
                side = d
                cur_frac = fracs(cfg_of(d))
                filled = 1
                avg = c
                last_add = c
                target = d * cur_frac[0]
                leg = {"dir": d, "entry": c, "idx": i, "t": bars[i]["t"]}
            elif side != 0 and filled < len(cur_frac):
                cf = cfg_of(side)
                move = (c - last_add) * side
                m = cf.get("mode")
                trig = (move >= cf.get("step", 1.0) * a) if m == "pyramid" else \
                       (-move >= cf.get("step", 1.0) * a) if m == "average" else False
                if trig:
                    w_old = sum(cur_frac[:filled])
                    w_new = cur_frac[filled]
                    avg = (avg * w_old + c * w_new) / (w_old + w_new)
                    filled += 1
                    last_add = c
                    target = side * sum(cur_frac[:filled])

        if target != pos:
            eq *= (1 - abs(target - pos) * cost / 100.0)
            pos = target
        eq *= (1 + pos * (bars[i + 1]["c"] / bars[i]["c"] - 1))

        # 隔夜利息：多單付、空單收（收的打折）。按實際持倉比例與時間長度計。
        if carry_per_bar and pos != 0:
            gap = (bars[i + 1]["t"] - bars[i]["t"]) / 60000.0 / bar_minutes
            g = carry_per_bar * max(1.0, gap)      # 週末缺口照算，錢照付
            if pos > 0:
                eq *= (1 - pos * g)
                carry_paid += pos * g * 100
            else:
                eq *= (1 + abs(pos) * g * carry_short_factor)
                carry_paid -= abs(pos) * g * carry_short_factor * 100

        curve.append((eq - 1) * 100)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > mdd:
            mdd = dd

    closed = trades
    wins = [t for t in closed if t["ret"] > 0]
    losses = [t for t in closed if t["ret"] <= 0]
    gp = sum(t["ret"] for t in wins)
    gl = abs(sum(t["ret"] for t in losses))
    longs = [t for t in closed if t["dir"] > 0]
    shorts = [t for t in closed if t["dir"] < 0]
    return {
        "net": (eq - 1) * 100, "mdd": mdd, "total": len(closed), "stops": stops,
        "carry": carry_paid,
        "win": (len(wins) / len(closed) * 100) if closed else None,
        "pf": (gp / gl) if gl else None,
        "long_n": len(longs), "short_n": len(shorts),
        "long_ret": sum(t["ret"] for t in longs),
        "short_ret": sum(t["ret"] for t in shorts),
        "worst": min((t["ret"] for t in closed), default=None),
        "avg_held": (sum(t["held"] for t in closed) / len(closed)) if closed else None,
        "trades": closed, "curve": curve,
    }
