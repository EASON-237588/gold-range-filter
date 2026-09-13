# -*- coding: utf-8 -*-
"""Binance PAXG 資料（儀表板用的同一個源），供與 Range Filter 同期比較。

PAXG 只有 2020 年之後，測不到任何空頭段——長期驗證一律用 gold_data 的 GC=F。
這支的用途只有一個：讓日線策略跟儀表板的 Range Filter 在**同一段期間**比較。
"""
import io, json, os, time, urllib.request

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
BASE = "https://api.binance.com/api/v3/klines"


def _get(url, tries=4):
    """連續打幾百個請求時會遇到 WinError 10060（連線逾時），尤其在手機熱點上。
    重試 + 退避就能過；不重試的話整批會白抓。"""
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(1.5 * (k + 1))
    raise last


def fetch(symbol="PAXGUSDT", interval="1d", use_cache=True, max_bars=300000, verbose=False):
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR)
    path = os.path.join(DATA_DIR, "%s_%s.json" % (symbol, interval))
    if use_cache and os.path.exists(path):
        cached = json.load(io.open(path, encoding="utf-8"))
        if len(cached) >= max_bars * 0.95 or interval == "1d":
            return cached

    out, end = [], int(time.time() * 1000)
    while True:
        url = "%s?symbol=%s&interval=%s&limit=1000&endTime=%d" % (BASE, symbol, interval, end)
        rows = _get(url)
        if not rows:
            break
        if verbose and len(out) % 20000 < 1000:
            print("  已抓 %d 根..." % len(out))
        time.sleep(0.12)                      # 節流，避免被斷線
        batch = [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
                  "l": float(k[3]), "c": float(k[4]), "v": float(k[5])} for k in rows]
        out = batch + out
        if len(rows) < 1000:
            break
        end = int(rows[0][0]) - 1
        if len(out) >= max_bars:
            break
    # 去重並排序
    seen, uniq = set(), []
    for b in sorted(out, key=lambda x: x["t"]):
        if b["t"] not in seen:
            seen.add(b["t"])
            uniq.append(b)
    io.open(path, "w", encoding="utf-8").write(json.dumps(uniq))
    return uniq


def aggregate(bars1m, minutes):
    """把 1 分 K 聚合成 N 分（11 分、2 分不是 Binance 原生週期，只能這樣來）。

    bucket 以 epoch 對齊，跟 index.html 的 aggregate() 一致。
    儀表板的處理順序是 **聚合 → session 過濾 → 取尾段**，順序換了結果就不同。
    """
    ms = minutes * 60000
    out, cur = [], None
    for b in bars1m:
        bucket = (b["t"] // ms) * ms
        if cur is None or cur["t"] != bucket:
            if cur is not None:
                out.append(cur)
            cur = {"t": bucket, "o": b["o"], "h": b["h"],
                   "l": b["l"], "c": b["c"], "v": b.get("v", 0.0)}
        else:
            cur["h"] = max(cur["h"], b["h"])
            cur["l"] = min(cur["l"], b["l"])
            cur["c"] = b["c"]
            cur["v"] += b.get("v", 0.0)
    if cur is not None:
        out.append(cur)
    return out


if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    from gold_data import ymd
    b = fetch()
    print("PAXGUSDT 1d  %d 根  %s ~ %s  收 %.2f -> %.2f"
          % (len(b), ymd(b[0]["t"]), ymd(b[-1]["t"]), b[0]["c"], b[-1]["c"]))
