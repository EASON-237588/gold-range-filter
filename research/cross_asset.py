# -*- coding: utf-8 -*-
"""換商品：做空虧錢是黃金的問題，還是這個架構的問題。

黃金六年漲 121%，在結構性上漲的標的上做空本來就是逆風，所以「空單負貢獻」
這個結論有可能只是商品特性。要分辨，得找**真正有大空頭**的標的來測。

加密貨幣是最好的試金石：Binance 有同格式的 4 小時六年資料（同一個引擎、同一段期間、
同一組參數，唯一變數就是商品），而且 2021-2022 有 -70% 以上的熊市。
如果空單在那種跌勢裡也賺不到錢，問題就在架構；如果賺得到，那就是黃金不適合做空。

參數完全沿用黃金的掃描冠軍，不針對各商品重新最佳化——重新調參數就變成
「每個商品各挑一個最好的」，那必然每個都好看，也就什麼都證明不了。
"""
import sys, time
import paxg_data
from dual_engine import backtest, buy_hold, atr, dir_donchian

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TF, MINS = "4h", 240
LOOKBACK_H = 1200.0                      # = Donchian 300 根
N = int(LOOKBACK_H * 60 / MINS)
SYMS = ["PAXGUSDT", "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT"]


def load(sym, years=6.2):
    need = int(years * 365 * 24 * 60 / MINS) + 100
    try:
        return paxg_data.fetch(sym, TF, max_bars=need, verbose=False)
    except Exception as e:
        print("  %s 抓取失敗：%s" % (sym, e))
        return None


def main():
    print("4 小時線・回看 %.0f 小時（Donch%d）・逆勢攤平・step 1 ATR・stop 3 ATR・成本 0.115%%"
          % (LOOKBACK_H, N))
    print("參數完全沿用黃金的掃描冠軍，各商品不重新最佳化。\n")

    print("%-10s %-21s │ %-40s │ %-17s"
          % ("商品", "買進持有", "多空都做", "拆解"))
    print("%-10s %9s %7s %5s │ %8s %7s %6s %5s %6s │ %8s %8s"
          % ("", "報酬", "回撤", "報/撤", "報酬", "回撤", "報/撤", "筆數", "持倉天",
             "多單", "空單"))

    rows = []
    for sym in SYMS:
        bars = load(sym)
        if not bars or len(bars) < N * 3:
            print("%-10s 資料不足（%d 根）" % (sym, len(bars) if bars else 0))
            continue
        A = atr(bars, 14)
        bh = buy_hold(bars)
        d = dir_donchian(bars, N, max(10, N // 3))
        r = backtest(bars, d, mode="average", segs=5, step_atr=1.0,
                     stop_atr=3.0, cost=0.115, atr_arr=A)
        # 最大跌幅：從歷史高點到之後最低點，用來標示這段期間有沒有真的大空頭
        peak = -1e18
        worst_dd = 0.0
        for b in bars:
            if b["c"] > peak:
                peak = b["c"]
            dd = (peak - b["c"]) / peak * 100
            if dd > worst_dd:
                worst_dd = dd
        print("%-10s %+8.1f%% %6.1f%% %5.2f │ %+7.1f%% %6.1f%% %6.2f %5d %6.1f │ %+7.1f%% %+7.1f%%"
              % (sym.replace("USDT", ""), bh["net"], bh["mdd"],
                 bh["net"] / bh["mdd"] if bh["mdd"] else 0,
                 r["net"], r["mdd"], r["net"] / r["mdd"] if r["mdd"] else 0,
                 r["total"], r["avg_held"] / 6.0,
                 r["long_ret"], r["short_ret"]))
        rows.append((sym, bh, r, worst_dd, bars, A, d))

    print("\n=== 只做多 vs 多空：關掉空單會怎樣 ===")
    print("%-10s %10s │ %10s %10s %10s │ %8s"
          % ("商品", "期間最大跌幅", "多空都做", "只做多", "只做空", "空單價值"))
    for sym, bh, r, worst_dd, bars, A, d in rows:
        dl = [max(0, x) for x in d]
        ds = [min(0, x) for x in d]
        rl = backtest(bars, dl, mode="average", segs=5, step_atr=1.0, stop_atr=3.0,
                      cost=0.115, atr_arr=A)
        rs = backtest(bars, ds, mode="average", segs=5, step_atr=1.0, stop_atr=3.0,
                      cost=0.115, atr_arr=A)
        delta = r["net"] - rl["net"]
        print("%-10s %9.1f%% │ %+9.1f%% %+9.1f%% %+9.1f%% │ %+7.1f%%"
              % (sym.replace("USDT", ""), worst_dd, r["net"], rl["net"], rs["net"], delta))
    print("\n「空單價值」= 多空都做 − 只做多。正數代表加空單有幫助，負數代表加了反而拖累。")


if __name__ == "__main__":
    main()
