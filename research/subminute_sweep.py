# -*- coding: utf-8 -*-
"""1~20 分鐘週期：把 K 線切細到底有沒有用。

設計上的關鍵：**回看長度固定成「時間」而不是「根數」**。
如果各週期都用 Donchian 300 根，1 分線的回看是 5 小時、20 分線是 100 小時，
等於同時改了解析度與回看長度兩個變數，跑出來的差異無法歸因。
這裡固定回看 24/50/100/200/400 小時，各週期換算成自己的根數，
唯一的變數就只剩「同一段時間切成幾根」。

cost_floor.py 已經量到：可捕捉的幅度只取決於持有多久，跟切多細無關。
所以這支要驗證的是它的推論——切細只會增加決策次數（成本），不會增加可賺的幅度。
如果推論錯了，這裡會看到某個短週期明顯勝出。

限制：1 分 K 只回溯約 312 天，所以全部週期都只能用這 300 天，
不是六年。這段是震盪市（買進持有約 +6%），結論不能外推到單邊行情。
"""
import sys, time
import paxg_data
from dual_engine import backtest, buy_hold, atr, dir_donchian

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DAYS = 300
TFS = [1, 2, 3, 5, 10, 15, 20]          # 分鐘
LOOKBACK_H = [24, 50, 100, 200, 400]    # 回看小時數
COST = 0.115


def aggregate(m1, k):
    """1 分 K 聚合成 k 分 K。時間桶用整除對齊，跟儀表板的做法一致。"""
    if k == 1:
        return m1
    out, cur, bucket = [], None, None
    for b in m1:
        bk = b["t"] - (b["t"] % (k * 60000))
        if bk != bucket:
            if cur:
                out.append(cur)
            bucket = bk
            cur = {"t": bk, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]}
        else:
            cur["h"] = max(cur["h"], b["h"])
            cur["l"] = min(cur["l"], b["l"])
            cur["c"] = b["c"]
            cur["v"] += b["v"]
    if cur:
        out.append(cur)
    return out


def main():
    need = DAYS * 24 * 60 + 100
    m1 = paxg_data.fetch("PAXGUSDT", "1m", max_bars=need, verbose=True)
    cut = m1[-1]["t"] - DAYS * 86400 * 1000
    m1 = [b for b in m1 if b["t"] >= cut]
    bh = buy_hold(m1)
    d0 = time.strftime("%Y-%m-%d", time.gmtime(m1[0]["t"] / 1000))
    d1 = time.strftime("%Y-%m-%d", time.gmtime(m1[-1]["t"] / 1000))
    print("PAXG 1 分 K %s 根・%s ~ %s" % (format(len(m1), ","), d0, d1))
    print("買進持有 %+.1f%%／回撤 %.1f%%（報/撤 %.2f）\n"
          % (bh["net"], bh["mdd"], bh["net"] / bh["mdd"]))

    best_overall = []
    for k in TFS:
        bars = aggregate(m1, k)
        A = atr(bars, 14)
        print("=== %d 分・%s 根 ===" % (k, format(len(bars), ",")))
        print("  %-10s %-8s %8s %7s %6s %6s %7s %7s"
              % ("回看", "模式", "報酬", "回撤", "報/撤", "筆數", "持倉天", "空單"))
        for H in LOOKBACK_H:
            n = int(H * 60 / k)
            if n < 20 or n > len(bars) // 4:
                continue
            d = dir_donchian(bars, n, max(10, n // 3))
            for mode in ["single", "average"]:
                r = backtest(bars, d, mode=mode, segs=5, step_atr=1.0,
                             stop_atr=3.0, cost=COST, atr_arr=A)
                if r["total"] < 5:
                    continue
                hold = r["avg_held"] * k / 1440.0
                rr = r["net"] / r["mdd"] if r["mdd"] else 0
                print("  %-10s %-8s %+7.1f%% %6.1f%% %6.2f %6d %7.1f %+6.1f%%"
                      % ("%d 小時" % H, mode, r["net"], r["mdd"], rr,
                         r["total"], hold, r["short_ret"]))
                best_overall.append((rr, r["net"], k, H, mode, r["total"], hold))
        print()

    print("=== 全部組合依報酬÷回撤排序（前 12）===")
    best_overall.sort(reverse=True)
    print("  %-6s %-8s %-8s %8s %6s %6s %7s" % ("週期", "回看", "模式", "報酬", "報/撤", "筆數", "持倉天"))
    for rr, net, k, H, mode, n, hold in best_overall[:12]:
        print("  %-6s %-8s %-8s %+7.1f%% %6.2f %6d %7.1f"
              % ("%d 分" % k, "%d 小時" % H, mode, net, rr, n, hold))

    print("\n=== 同一個回看時間，換週期會怎樣（average 模式）===")
    print("  如果切細有用，同一列往左（週期變小）應該要變好。")
    print("  %-10s" % "回看" + "".join(("%d分" % k).rjust(9) for k in TFS))
    for H in LOOKBACK_H:
        cells = []
        for k in TFS:
            hit = [x for x in best_overall if x[3] == H and x[2] == k and x[4] == "average"]
            cells.append(("%+.1f%%" % hit[0][1]) if hit else "—")
        print("  %-10s" % ("%d 小時" % H) + "".join(c.rjust(9) for c in cells))


if __name__ == "__main__":
    main()
