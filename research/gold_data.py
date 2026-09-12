# -*- coding: utf-8 -*-
"""黃金長期日線資料源（Yahoo Finance，免金鑰）。

坑（2026-09-13 實測）：
  * 必須帶瀏覽器 User-Agent，否則一律 429（curl 預設 UA 連三次都被擋）。
  * 要全歷史得用 period1=0&period2=<now>；range=max 會被降成月線只給 268 根。
  * interval=15m 配 period1/period2 會回 422，短週期要改用 range=60d。

可用代號：
  GC=F  黃金期貨連續  6,532 根 / 26.0 年 / 2000-08-30 起  ← 主樣本，含 2011-2015 大空頭
  GLD   SPDR 黃金 ETF 5,487 根 / 21.8 年 / 2004-11-18 起  ← 獨立驗證源（有管理費侵蝕）
  ^XAU  費城金銀指數                                      ← 是礦業股指數不是金價，不要用

Binance 的 PAXGUSDT 只有 2020 年之後的資料，測不到任何空頭段，
不能單獨用來驗證擇時策略——那段是純多頭，任何偏多的結構都會被獎勵。
"""
import io, json, os, time, urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def fetch(symbol, interval="1d", use_cache=True):
    """回傳 [{t(ms), o, h, l, c}, ...]，依 symbol 快取到 research/data/。"""
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR)
    safe = symbol.replace("=", "").replace("^", "")
    path = os.path.join(DATA_DIR, "%s_%s.json" % (safe, interval))
    if use_cache and os.path.exists(path):
        return json.load(io.open(path, encoding="utf-8"))

    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?interval=%s&period1=0&period2=%d" % (symbol, interval, int(time.time())))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode("utf-8"))

    res = d["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res["timestamp"]):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):          # Yahoo 會夾雜 null，直接丟掉
            continue
        out.append({"t": t * 1000, "o": o, "h": h, "l": l, "c": c})
    io.open(path, "w", encoding="utf-8").write(json.dumps(out))
    return out


def ymd(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def ym(ms):
    return time.strftime("%Y-%m", time.gmtime(ms / 1000))


def describe(bars, name=""):
    yrs = (bars[-1]["t"] - bars[0]["t"]) / 864e5 / 365
    return ("%-6s %5d 根  %s ~ %s  (%.1f 年)  收 %.2f -> %.2f"
            % (name, len(bars), ymd(bars[0]["t"]), ymd(bars[-1]["t"]),
               yrs, bars[0]["c"], bars[-1]["c"]))


if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    for s in ["GC=F", "GLD"]:
        print(describe(fetch(s), s))
