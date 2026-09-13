# -*- coding: utf-8 -*-
"""不對稱設計掃描：多單攤平不動，只改空單的規則，週期限制在 1~15 分。

前提（已驗證，不再重測）：
  多單用逆勢攤平有效——六年、兩週期、兩種方向訊號、十二個年份格子幾乎無例外。
  空單用多單的鏡像規則無效——七個商品（跌幅 29%~95%）加四個熊市段全部負貢獻。

所以這裡固定多單設定，只掃空單：
  模式      金字塔（跌勢確認才加碼，避開在反彈中加倉）／不分批／攤平（對照）
  停損      固定百分比，而不是 ATR 倍數——跌勢中 ATR 放大會讓倍數型停損自動放寬
  關閉      enabled=False 當基準線，看空單到底有沒有加分

判準只有一個：**空單價值 = 多空都做 − 只做多**。是正的才算成功，
報酬高但空單價值是負的，代表多單在補空單的洞，那不叫多空雙向可行。
"""
import sys, time
import paxg_data
from dual_engine import backtest_asym, buy_hold, atr, dir_donchian

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TF, MINS = "15m", 15
YEARS = 6.2
LONG = {"mode": "average", "step": 1.0, "stop_atr": 3.0, "stop_pct": None}


def load():
    need = int(YEARS * 365 * 24 * 60 / MINS) + 100
    return paxg_data.fetch("PAXGUSDT", TF, max_bars=need, verbose=False)


def main():
    bars = load()
    A = atr(bars, 14)
    bh = buy_hold(bars)
    d0 = time.strftime("%Y-%m-%d", time.gmtime(bars[0]["t"] / 1000))
    print("PAXG %s・%s 根・%s 起・買進持有 %+.1f%%／回撤 %.1f%%（%.2f）"
          % (TF, format(len(bars), ","), d0, bh["net"], bh["mdd"], bh["net"] / bh["mdd"]))
    print("多單固定：逆勢攤平・step 1 ATR・stop 3 ATR\n")

    for H in [400, 600, 800, 1200]:
        n = int(H * 60 / MINS)
        d = dir_donchian(bars, n, max(10, n // 3))

        base_long = backtest_asym(bars, d, LONG,
                                  {"enabled": False}, atr_arr=A)
        print("=== 回看 %d 小時（Donch%d）・只做多基準 %+.1f%%／回撤 %.1f%%（%.2f）%d 筆 ==="
              % (H, n, base_long["net"], base_long["mdd"],
                 base_long["net"] / base_long["mdd"] if base_long["mdd"] else 0,
                 base_long["total"]))
        print("  %-10s %-6s %6s │ %8s %7s %6s %5s │ %8s %8s │ %9s"
              % ("空單模式", "step", "停損", "報酬", "回撤", "報/撤", "筆數",
                 "多單", "空單", "空單價值"))

        best = None
        for smode in ["pyramid", "single", "average"]:
            steps = [1.0] if smode == "single" else [0.5, 1.0, 2.0]
            for sstep in steps:
                for spct in [1.0, 2.0, 3.0, 5.0]:
                    short = {"mode": smode, "step": sstep,
                             "stop_atr": None, "stop_pct": spct}
                    r = backtest_asym(bars, d, LONG, short, atr_arr=A)
                    val = r["net"] - base_long["net"]
                    mark = " ←" if val > 0 else ""
                    print("  %-10s %6.1f %5.0f%% │ %+7.1f%% %6.1f%% %6.2f %5d │ %+7.1f%% %+7.1f%% │ %+8.1f%%%s"
                          % (smode, sstep, spct, r["net"], r["mdd"],
                             r["net"] / r["mdd"] if r["mdd"] else 0, r["total"],
                             r["long_ret"], r["short_ret"], val, mark))
                    if best is None or val > best[0]:
                        best = (val, smode, sstep, spct, r)
        print("  → 這個回看下最好的空單設定：%s step%.1f stop%.0f%%，空單價值 %+.1f%%\n"
              % (best[1], best[2], best[3], best[0]))


if __name__ == "__main__":
    main()
