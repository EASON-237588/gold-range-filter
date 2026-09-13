# -*- coding: utf-8 -*-
"""掃描：把平均持倉推到 5 天以上，看報酬與回撤變成什麼樣。

為什麼把「持倉時間」當主軸而不是報酬率：cost_floor.py 量到可捕捉的幅度只取決於
抱多久，跟 K 線切多細無關。持倉 2 天的比值約 6（邊緣），5 天以上才進得了值得做的區間。
上一輪 1h 全滅時平均持倉正好是 2 天，所以要先確認那是參數造成的，還是架構不行。

篩選條件（在看報酬之前就先過濾掉）：
  平均持倉 >= 5 天      成本地板的要求
  筆數 >= 12            六年至少每半年一筆，否則樣本不足以談穩健
  最大單筆佔淨利 <= 60%  避免整個結論靠一次行情撐著

排序用報酬÷回撤，不是報酬——這個專案先前所有結論都指向同一件事：
擇時的價值在降回撤，用報酬排序會選到單純曝險大的組合。
"""
import sys, time
import paxg_data
from dual_engine import backtest, buy_hold, atr, dir_donchian, dir_ema_slope

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MIN_HOLD_DAYS = 5.0
MIN_TRADES = 12
MAX_CONC = 60.0


def load(tf, mins, years=6.2):
    need = int(years * 365 * 24 * 60 / mins) + 100
    return paxg_data.fetch("PAXGUSDT", tf, max_bars=need, verbose=True)


def concentration(r):
    """最大單筆獲利佔總獲利的比例。撞過三次同一個形狀：報酬全靠一兩筆。"""
    gains = [t["ret"] for t in r["trades"] if t["ret"] > 0]
    if not gains or sum(gains) <= 0:
        return None
    return max(gains) / sum(gains) * 100


def dirs_for(bars):
    out = []
    for n in [55, 100, 200, 300, 500]:
        out.append(("Donch%d" % n, dir_donchian(bars, n, max(10, n // 3))))
    for fast, slow in [(20, 60), (50, 150), (100, 300)]:
        for th in [0.25, 0.5, 1.0]:
            out.append(("EMA%d/%d±%.2f" % (fast, slow, th),
                        dir_ema_slope(bars, fast, slow, 14, th)))
    return out


def main():
    for tf, mins in [("4h", 240), ("1h", 60)]:
        bars = load(tf, mins)
        A = atr(bars, 14)
        bh = buy_hold(bars)
        bars_per_day = 1440.0 / mins
        print("\n############ %s・%s 根・買進持有 %+.1f%%／回撤 %.1f%%（報/撤 %.2f）############"
              % (tf, format(len(bars), ","), bh["net"], bh["mdd"], bh["net"] / bh["mdd"]))

        t0 = time.time()
        rows, tried = [], 0
        for dname, d in dirs_for(bars):
            for mode in ["single", "pyramid", "average"]:
                steps = [1.0] if mode == "single" else [1.0, 2.0, 3.0]
                for step in steps:
                    for stop in [3.0, 6.0, 10.0, 999.0]:
                        tried += 1
                        r = backtest(bars, d, mode=mode, segs=5, step_atr=step,
                                     stop_atr=stop, atr_arr=A)
                        if r["total"] < MIN_TRADES or r["mdd"] <= 0:
                            continue
                        hold_d = r["avg_held"] / bars_per_day
                        conc = concentration(r)
                        rows.append({
                            "dir": dname, "mode": mode, "step": step, "stop": stop,
                            "net": r["net"], "mdd": r["mdd"], "rr": r["net"] / r["mdd"],
                            "n": r["total"], "hold": hold_d, "conc": conc,
                            "win": r["win"], "worst": r["worst"], "stops": r["stops"],
                            "long_ret": r["long_ret"], "short_ret": r["short_ret"],
                        })
        print("掃了 %d 組，%.0f 秒" % (tried, time.time() - t0))

        ok = [x for x in rows if x["hold"] >= MIN_HOLD_DAYS
              and (x["conc"] is None or x["conc"] <= MAX_CONC)]
        print("持倉 >= %.0f 天且集中度 <= %.0f%%：%d 組（原本 %d 組）"
              % (MIN_HOLD_DAYS, MAX_CONC, len(ok), len(rows)))

        if not ok:
            print("沒有組合同時滿足持倉與集中度條件。")
            hold_ok = [x for x in rows if x["hold"] >= MIN_HOLD_DAYS]
            print("  只看持倉條件：%d 組" % len(hold_ok))
            if hold_ok:
                best = max(hold_ok, key=lambda x: x["rr"])
                print("  其中報/撤最高：%s %s step%.0f stop%.0f → %+.1f%%／%.1f%%（集中度 %.0f%%）"
                      % (best["dir"], best["mode"], best["step"], best["stop"],
                         best["net"], best["mdd"], best["conc"] or 0))
            continue

        ok.sort(key=lambda x: -x["rr"])
        print("\n%-14s %-8s %5s %5s │ %8s %7s %6s %5s %6s %6s %6s │ %8s %8s"
              % ("方向", "模式", "step", "stop", "報酬", "回撤", "報/撤",
                 "筆數", "持倉天", "勝率", "集中度", "多單", "空單"))
        for x in ok[:20]:
            print("%-14s %-8s %5.0f %5.0f │ %+7.1f%% %6.1f%% %6.2f %5d %6.1f %5.1f%% %5.0f%% │ %+7.1f%% %+7.1f%%"
                  % (x["dir"], x["mode"], x["step"], x["stop"], x["net"], x["mdd"],
                     x["rr"], x["n"], x["hold"], x["win"], x["conc"] or 0,
                     x["long_ret"], x["short_ret"]))

        print("\n-- 依模式看最好的一組 --")
        for m in ["single", "pyramid", "average"]:
            sub = [x for x in ok if x["mode"] == m]
            if not sub:
                print("  %-8s 沒有組合通過篩選" % m)
                continue
            b = max(sub, key=lambda x: x["rr"])
            print("  %-8s %s step%.0f stop%.0f → %+.1f%%／回撤 %.1f%%（報/撤 %.2f）"
                  "・%d 筆・持倉 %.1f 天・多 %+.1f%% 空 %+.1f%%"
                  % (m, b["dir"], b["step"], b["stop"], b["net"], b["mdd"], b["rr"],
                     b["n"], b["hold"], b["long_ret"], b["short_ret"]))


if __name__ == "__main__":
    main()
