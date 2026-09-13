# -*- coding: utf-8 -*-
"""只優化進場時機：買了就不賣，比較「什麼時候買」的差別。

這跟先前所有測試都不同。前面測的全是「有進有出」的策略，它們的失敗有兩個來源
混在一起：進場點不好，以及出場後錯過上漲。這支把第二個來源整個拿掉——
**永不賣出**，所以唯一的變數只剩「資金什麼時候投進去」。

比較四種投法（同一段期間、同樣把 100% 資金投完）：
  期初全買    第一根就滿倉。這是買進持有的標準定義，也是基準。
  定期定額    把期間平均切成 N 份，每隔一段時間投一份，不看行情。
  回檔買進    價格跌破近期低點（或距高點回落 X%）時投一份。
  突破買進    價格突破近期高點時投一份，順勢。

判準跟先前不同，因為終點部位都是滿倉、最終價格相同：
  最終報酬    誰的平均成本低誰就贏
  過程回撤    投入期間承受的最大帳面虧損
  平均成本    直接比進場價，這是這個問題真正的答案

一個常被忽略的事實：資金未投入的期間是**空手**，不是無風險。
在上漲市場裡，等待本身就是成本——這正是「回檔買進」最常輸的原因。
"""
import sys, time, calendar
import paxg_data
from dual_engine import atr, roll_max, roll_min

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def run_accum(bars, when, parts=12, lookback=None, cost=0.115, dip_pct=None):
    """把資金分成 parts 份投入，投完不賣。回傳最終報酬、過程回撤、平均成本。

    when:
      "lump"    第一根全投
      "dca"     時間平均分配
      "dip"     跌破近 lookback 根低點時投一份（或距近期高點回落 dip_pct%）
      "breakout" 突破近 lookback 根高點時投一份
    """
    n = len(bars)
    C = [b["c"] for b in bars]
    H = [b["h"] for b in bars]
    L = [b["l"] for b in bars]
    HH = roll_max(H, lookback) if lookback else None
    LL = roll_min(L, lookback) if lookback else None

    # 期初全買就是一次投滿。忘了這行的話它會走 parts 的分母只投 1/parts，
    # 剩下的拖到最後一根才補，基準被嚴重低估（六年 +120% 會變成 +10%）。
    if when == "lump":
        parts = 1
    frac = 1.0 / parts
    invested = 0.0          # 已投入的資金比例
    units = 0.0             # 買到的部位（以「初始資金/價格」為單位）
    buys = []
    dca_at = set()
    if when == "dca":
        step = n // parts
        dca_at = set(min(n - 1, i * step) for i in range(parts))

    peak_eq = 1.0
    mdd = 0.0
    last_buy_i = -10 ** 9
    min_gap = (lookback // 2) if lookback else 0     # 同一波不要連續狂買

    for i in range(n):
        buy = False
        if invested < 1.0 - 1e-9:
            if when == "lump":
                buy = (i == 0)
            elif when == "dca":
                buy = (i in dca_at)
            elif when == "dip" and lookback and i >= lookback:
                if dip_pct is not None:
                    buy = C[i] <= HH[i] * (1 - dip_pct / 100.0)
                else:
                    buy = C[i] < LL[i]
                buy = buy and (i - last_buy_i >= min_gap)
            elif when == "breakout" and lookback and i >= lookback:
                buy = C[i] > HH[i] and (i - last_buy_i >= min_gap)

        if buy:
            amt = min(frac, 1.0 - invested)
            units += amt * (1 - cost / 100.0) / C[i]
            invested += amt
            last_buy_i = i
            buys.append((i, C[i]))

        # 權益 = 已買到的部位市值 + 尚未投入的現金
        eq = units * C[i] + (1.0 - invested)
        if eq > peak_eq:
            peak_eq = eq
        dd = (peak_eq - eq) / peak_eq * 100
        if dd > mdd:
            mdd = dd

    # 期末若還沒投完，剩下的在最後一根補齊（否則不同方法的曝險不同，不能比）
    if invested < 1.0 - 1e-9:
        amt = 1.0 - invested
        units += amt * (1 - cost / 100.0) / C[-1]
        invested = 1.0
        buys.append((n - 1, C[-1]))

    final = units * C[-1]
    avg_cost = (1.0 / units) if units else None
    return {"net": (final - 1) * 100, "mdd": mdd, "avg_cost": avg_cost,
            "buys": buys, "n_buys": len(buys),
            "last_i": buys[-1][0] if buys else 0}


def show(tag, r, base=None, bars=None):
    d = ""
    if base is not None:
        d = "  %+6.1f pp" % (r["net"] - base["net"])
    fill = ""
    if bars is not None and r["buys"]:
        fill = "・投完於 %s" % time.strftime("%Y-%m-%d",
                                          time.gmtime(bars[r["last_i"]]["t"] / 1000))
    print("  %-16s %+8.1f%% │ 過程回撤 %5.1f%% │ 平均成本 %9.2f │ %2d 次%s%s"
          % (tag, r["net"], r["mdd"], r["avg_cost"], r["n_buys"], fill, d))


def main():
    for tf, mins in [("15m", 15), ("30m", 30)]:
        need = int(6.2 * 365 * 24 * 60 / mins) + 100
        bars = paxg_data.fetch("PAXGUSDT", tf, max_bars=need, verbose=False)
        bpd = 1440.0 / mins
        print("\n######## %s・%s 根・%s ~ %s ########"
              % (tf, format(len(bars), ","),
                 time.strftime("%Y-%m-%d", time.gmtime(bars[0]["t"] / 1000)),
                 time.strftime("%Y-%m-%d", time.gmtime(bars[-1]["t"] / 1000))))

        lump = run_accum(bars, "lump")
        show("期初全買（基準）", lump, None, bars)
        for parts in [6, 12, 24]:
            show("定期定額 %d 份" % parts, run_accum(bars, "dca", parts=parts), lump, bars)

        print()
        for parts in [6, 12]:
            for H in [200, 400, 800]:
                n = int(H * 60 / mins)
                r = run_accum(bars, "dip", parts=parts, lookback=n)
                show("回檔買 %d份/%d時" % (parts, H), r, lump, bars)
        print()
        for parts in [6, 12]:
            for dp in [2.0, 5.0, 10.0]:
                n = int(400 * 60 / mins)
                r = run_accum(bars, "dip", parts=parts, lookback=n, dip_pct=dp)
                show("回落%.0f%% %d份" % (dp, parts), r, lump, bars)
        print()
        for parts in [6, 12]:
            for H in [200, 400, 800]:
                n = int(H * 60 / mins)
                r = run_accum(bars, "breakout", parts=parts, lookback=n)
                show("突破買 %d份/%d時" % (parts, H), r, lump, bars)


if __name__ == "__main__":
    main()
