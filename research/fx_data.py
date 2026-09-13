# -*- coding: utf-8 -*-
"""外匯資料（HistData.com，免費、無需註冊、1 分鐘、2000 年起）。

為什麼是這個源（四個都實測過）：
  HistData    1 分鐘、2000 年起、可程式化下載，一個月檔約 5 秒 → 六年 6 分鐘。採用。
  Dukascopy   tick、2003 年起、含真實買賣報價，但一小時一個檔，六年三萬多檔不實際。
              留著量點差用（實測 EURUSD 現在平均 0.0023%）。
  Yahoo       15/30 分只給 81 天，回測樣本不足。
  Stooq       反爬 JS 挑戰，程式化拿不到。

兩個必須處理的細節：
  時區   HistData 的時間戳是 **EST/EDT（美東）**，不是 UTC。不轉的話跟其他資料源
         對不起來，而且「一天」的邊界會錯位。這裡一律轉成 UTC 存。
  成交量 外匯沒有集中市場，V 欄一律是 0。任何吃成交量的指標在外匯上都不能用。

儲存用 npz：六年 1 分鐘約 220 萬根，存 json 會膨脹到數百 MB，
而且載入後若展開成 dict list 會吃掉 1GB 以上記憶體。
所以 1 分鐘只以 numpy 陣列存取，要餵給回測引擎時先聚合到目標週期再展開。
"""
import io, os, re, sys, time, zipfile, urllib.request, urllib.parse
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fx")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
PAGE = ("https://www.histdata.com/download-free-forex-historical-data/"
        "?/ascii/1-minute-bar-quotes/%s/%d/%d")
PAGE_Y = ("https://www.histdata.com/download-free-forex-historical-data/"
          "?/ascii/1-minute-bar-quotes/%s/%d")
POST = "https://www.histdata.com/get.php"


def _download(pair, y, m=None, tries=3):
    """抓 1 分鐘 CSV。要先 GET 頁面取隱藏 token，才能 POST 下載。

    m=None 表示整年打包。HistData 對**往年**只提供整年 ZIP，月份頁面拿不到東西
    （實測 2020~2024 逐月全部落空，2025 起才有月檔）。整年反而更快：
    一年 37 萬根只要 8~14 秒，逐月要跑 12 次。
    """
    page = (PAGE % (pair.lower(), y, m)) if m else (PAGE_Y % (pair.lower(), y))
    last = None
    for k in range(tries):
        try:
            html = urllib.request.urlopen(
                urllib.request.Request(page, headers=UA), timeout=30
            ).read().decode("utf-8", "replace")
            f = {}
            for name in ["tk", "date", "datemonth", "platform", "timeframe", "fxpair"]:
                mm = re.search(r'id="%s"[^>]*value="([^"]*)"' % name, html)
                if mm:
                    f[name] = mm.group(1)
            if "tk" not in f:
                return None                      # 該月沒有資料（例如未來的月份）
            req = urllib.request.Request(
                POST, data=urllib.parse.urlencode(f).encode(),
                headers=dict(UA, **{"Referer": page,
                                    "Content-Type": "application/x-www-form-urlencoded"}))
            blob = urllib.request.urlopen(req, timeout=90).read()
            if not blob.startswith(b"PK"):
                return None
            z = zipfile.ZipFile(io.BytesIO(blob))
            csv = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not csv:
                return None
            return z.read(csv[0]).decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(2.0 * (k + 1))
    raise last


def _parse(text):
    """YYYYMMDD HHMMSS;O;H;L;C;V → (t_utc_ms, o, h, l, c)，時區 EST→UTC。

    HistData 標的是 EST 且**不做日光節約調整**（他們的說明如此），
    所以固定 +5 小時轉 UTC。用固定偏移而不是 tz 資料庫，是為了可重現。
    """
    out = []
    for line in text.strip().split("\n"):
        p = line.split(";")
        if len(p) < 5:
            continue
        d, t = p[0].split(" ")
        tm = (int(d[0:4]), int(d[4:6]), int(d[6:8]),
              int(t[0:2]), int(t[2:4]), int(t[4:6]), 0, 0, 0)
        import calendar
        ts = (calendar.timegm(tm) + 5 * 3600) * 1000
        out.append((ts, float(p[1]), float(p[2]), float(p[3]), float(p[4])))
    return out


def fetch_m1(pair="EURUSD", years=6.2, use_cache=True, verbose=True):
    """抓 1 分鐘資料，回傳 numpy 結構陣列（t, o, h, l, c）。"""
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR)
    path = os.path.join(DATA_DIR, "%s_m1.npz" % pair)

    # 已抓過的不重抓：npz 裡存了完成清單，逐年／逐月都以 key 記錄
    if use_cache and os.path.exists(path):
        z = np.load(path)
        have = {"arr": z["bars"],
                "done": set(z["months"].tolist()) if "months" in z else set()}
        if verbose:
            print("  快取：%s 根、%d 段" % (format(len(have["arr"]), ","), len(have["done"])))
    else:
        have = {"arr": np.empty((0, 5)), "done": set()}

    now = time.gmtime()
    this_year = now.tm_year
    start_year = int(this_year - years) if years < 90 else 2000

    # 往年抓整年、今年與去年抓月檔（HistData 只對最近一兩年提供月檔）
    jobs = []
    for y in range(start_year, this_year - 1):
        jobs.append((y, None, "%04d" % y))
    for y in range(max(start_year, this_year - 1), this_year + 1):
        for m in range(1, 13):
            if y == this_year and m > now.tm_mon:
                break
            jobs.append((y, m, "%04d%02d" % (y, m)))

    rows = [have["arr"]] if len(have["arr"]) else []
    done = set(have["done"])
    fetched = 0
    for (yy, mm, key) in jobs:
        if key in done:
            continue
        t0 = time.time()
        txt = _download(pair, yy, mm)
        if txt is None:
            if verbose:
                print("  %s 無資料，跳過" % key)
            continue
        p = _parse(txt)
        if not p:
            continue
        rows.append(np.array(p, dtype=np.float64))
        done.add(key)
        fetched += 1
        if verbose:
            print("  %s → %s 根（%.1f 秒）" % (key, format(len(p), ","), time.time() - t0))
            sys.stdout.flush()

    if not rows:
        raise RuntimeError("沒有抓到任何資料")
    arr = np.concatenate(rows) if len(rows) > 1 else rows[0]
    arr = arr[np.argsort(arr[:, 0])]
    _, uniq = np.unique(arr[:, 0], return_index=True)
    arr = arr[np.sort(uniq)]
    if fetched:
        np.savez_compressed(path, bars=arr, months=np.array(sorted(done)))
    return arr


def aggregate(m1, minutes):
    """1 分鐘陣列聚合成 k 分鐘，回傳回測引擎吃的 dict list。

    外匯週末休市，時間軸本來就有洞；這裡按時間桶聚合，不補空 K——
    補出來的平盤 K 會稀釋波動率估計，讓通道被壓窄、假訊號暴增。
    """
    if len(m1) == 0:
        return []
    ms = minutes * 60000
    bucket = (m1[:, 0] // ms * ms).astype(np.int64)
    out = []
    i = 0
    n = len(m1)
    while i < n:
        j = i
        b = bucket[i]
        while j < n and bucket[j] == b:
            j += 1
        seg = m1[i:j]
        out.append({"t": int(b), "o": float(seg[0, 1]),
                    "h": float(seg[:, 2].max()), "l": float(seg[:, 3].min()),
                    "c": float(seg[-1, 4]), "v": 0.0})
        i = j
    return out


if __name__ == "__main__":
    pair = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    yrs = float(sys.argv[2]) if len(sys.argv) > 2 else 6.2
    print("抓 %s 的 1 分鐘資料（%.1f 年）..." % (pair, yrs))
    t0 = time.time()
    a = fetch_m1(pair, yrs)
    print("\n完成：%s 根・%.0f 秒" % (format(len(a), ","), time.time() - t0))
    print("期間 %s ~ %s（UTC）"
          % (time.strftime("%Y-%m-%d %H:%M", time.gmtime(a[0, 0] / 1000)),
             time.strftime("%Y-%m-%d %H:%M", time.gmtime(a[-1, 0] / 1000))))
    for k in [10, 15, 30]:
        bars = aggregate(a, k)
        C = [b["c"] for b in bars]
        mv = sum(abs(C[i + 1] / C[i] - 1) for i in range(len(C) - 1)) / (len(C) - 1) * 100
        print("  %2d 分 → %s 根・每根平均絕對報酬 %.4f%%" % (k, format(len(bars), ","), mv))
