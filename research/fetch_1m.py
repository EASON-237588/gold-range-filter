# -*- coding: utf-8 -*-
"""抓 PAXG 1 分 K（11 分面板要靠它合成）。

11 分不是 Binance 原生週期，得由 1 分聚合；而 1 分 K 只回溯約 312 天，
所以 11 分面板的歷史深度結構上就卡在 312 天，拉大根數也拿不到更多。

約 450 個請求、數分鐘。中途每 50 個請求存一次檔，斷了也不用整批重抓。
"""
import io, json, os, sys, time
from paxg_data import DATA_DIR, BASE, _get

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SYM, INTERVAL, TARGET = "PAXGUSDT", "1m", 460000
path = os.path.join(DATA_DIR, "%s_%s.json" % (SYM, INTERVAL))

out = []
if os.path.exists(path):
    out = json.load(io.open(path, encoding="utf-8"))
    print("已有快取 %d 根，從最早處往前續抓" % len(out))

end = (out[0]["t"] - 1) if out else int(time.time() * 1000)
t0, k = time.time(), 0

while len(out) < TARGET:
    url = "%s?symbol=%s&interval=%s&limit=1000&endTime=%d" % (BASE, SYM, INTERVAL, end)
    try:
        rows = _get(url)
    except Exception as e:
        print("中止於 %d 根：%s" % (len(out), str(e)[:60]))
        break
    if not rows:
        print("已到最早可得資料，共 %d 根" % len(out))
        break
    batch = [{"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
              "l": float(r[3]), "c": float(r[4]), "v": float(r[5])} for r in rows]
    out = batch + out
    end = int(rows[0][0]) - 1
    k += 1
    if k % 50 == 0:
        io.open(path, "w", encoding="utf-8").write(json.dumps(out))
        print("  %d 根（%.0f 秒）" % (len(out), time.time() - t0))
    if len(rows) < 1000:
        print("回傳不足 1000 根，已到底，共 %d 根" % len(out))
        break
    time.sleep(0.1)

seen, uniq = set(), []
for b in sorted(out, key=lambda x: x["t"]):
    if b["t"] not in seen:
        seen.add(b["t"])
        uniq.append(b)
io.open(path, "w", encoding="utf-8").write(json.dumps(uniq))
fmt = lambda ms: time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))
print("完成 %d 根  %s ~ %s  耗時 %.0f 秒"
      % (len(uniq), fmt(uniq[0]["t"]), fmt(uniq[-1]["t"]), time.time() - t0))
