# 黃金訊號 LINE 推播

手機關掉、App 沒開，訊號一樣送得到你手上。跑在 Cloudflare Workers 上，每分鐘偵測一次，
有新訊號就用 LINE Messaging API 推一則訊息給你。

**費用：0 元。** Cloudflare Workers 免費方案每天 10 萬次呼叫（這裡一天用 1,440 次），
KV 免費方案每天 1,000 次寫入（這裡一天約 131 次），
LINE 官方帳號免費方案每月 200 則訊息（這個策略一年才 20 幾則訊號）。

---

## 一、開 LINE 官方帳號，拿金鑰

1. 到 <https://developers.line.biz/console/> 用 LINE 帳號登入
2. 建立 **Provider**（隨便取名，例如「個人」）
3. 在該 Provider 底下建立 **Messaging API channel**
   - 頻道名稱就是你在 LINE 裡看到的帳號名稱，取「黃金訊號」之類
4. 進入該 channel → **Messaging API** 分頁
   - 最下面 **Channel access token (long-lived)** 按 **Issue**，把那串長字串複製起來 → 這就是 `LINE_TOKEN`
   - 上面有個 **QR code**，用手機 LINE 掃它，把這個官方帳號**加為好友**（這步不做就收不到）
5. 同一頁把 **Auto-reply messages** 關掉，免得它每次都回罐頭訊息

> 網路上舊教學會叫你用 LINE Notify —— 那個服務 2025/3/31 已經停止，別走那條。

## 二、部署到 Cloudflare

需要 Node.js。在這個 `push-worker` 資料夾底下依序執行：

```bash
npx wrangler login
```

```bash
npx wrangler kv namespace create STATE
```

上一行會印出一段 `id = "xxxxxxxx"`，把那個 id 貼進 `wrangler.toml` 的
`[[kv_namespaces]]` 區塊，取代 `貼上你的_KV_namespace_id`。

```bash
npx wrangler secret put LINE_TOKEN
```

貼上第一步拿到的 Channel access token（輸入時不會顯示，貼完按 Enter）。

```bash
npx wrangler deploy
```

部署完會給你一個網址，像 `https://gold-rf-line.你的帳號.workers.dev`。

## 三、補歷史、測試

Range Filter 是遞迴的，要有足夠歷史才算得準（暖機 1,800 根）。實測 2,200 根以上算出來的最新訊號就與網頁完全一致，這裡取 3,600 根（剔除休市後約 2,450 根）留餘裕。
第一次要把 3,600 根 11 分 K 補進 KV，一次呼叫最多抓 25 頁，所以要打**兩次**：

```
https://你的網址/bootstrap
```

每次回傳 `bars` 會往上加，看到 `"done": true` 就完成了。

然後測試 LINE 通不通：

```
https://你的網址/test
```

手機應該立刻收到一則測試訊息。收不到就檢查：有沒有加官方帳號好友、token 是不是貼錯。

最後看狀態：

```
https://你的網址/
```

`bars` 應該是 3600、`lineConfigured` 是 true。想手動跑一次偵測打 `/run`。

## 四、把端點鎖起來

網址是公開的，不鎖的話任何人都能打 `/test` 讓你的 LINE 響。設一組通關碼：

```bash
npx wrangler secret put ADMIN_KEY
```

自己想一組密碼輸入，然後重新 `npx wrangler deploy`。

之後所有網址都要加 `?key=你的密碼`，沒帶或帶錯一律回 `Not found`。
**每分鐘的自動偵測走 cron，不經過網址，不受影響。**

---

## 這台實際部署的樣子（2026/09/02）

- 網址：`https://gold-rf-line.eason-237588.workers.dev`（要帶 `?key=`）
- KV namespace：`df63427b45a5403c8bf2f62f8cafee64`
- LINE 官方帳號：黃金訊號 `@232kxcwb`，用 broadcast 發給好友
- 資料源：**Gate.io**（見下）
- 已驗證：Gate 的資料算出來的最新訊號（2026/8/28 22:20 賣出）與網頁用 Binance 算的完全一致

### Windows 上的兩個坑

1. PowerShell 的執行原則會擋掉 `npx.ps1`，指令要打 **`npx.cmd`**
2. `wrangler deploy` 一定要在 `push-worker` 資料夾裡跑。在上層 `CC\` 跑的話，
   它會抓到隔壁的 `員工績效考核系統` 當靜態網站要你部署 —— **那份含真實個資，絕對不能按 y**

---

## 設計說明

**資料源不是 Binance。** Cloudflare 的出口 IP 被 Binance 擋（`451`）、被 Bybit 擋（`403`），
所以改用 **Gate.io**（每頁 1000 根），OKX 當備援（每頁只有 100 根，補歷史會很慢）。
`/probe` 端點可以一次試遍所有資料源，看當下誰通得了。
PAXG 是同一種資產，兩家報價差在 0.1% 以內，實測訊號完全一致。

**為什麼不每次重抓兩萬根。** Cloudflare 免費方案一次呼叫最多 50 個子請求，
重抓兩萬根 11 分 K 要 330 個請求，直接超標。而且 KV 免費方案一天只有 1,000 次寫入，
每分鐘寫一次就是 1,440 次，也超標。

所以歷史存在 KV，每分鐘只抓最後 88 根 1 分 K（1 個請求）併進去，
而且**只有在又收完一根 11 分 K 時才寫回 KV** —— 一天約 131 次寫入，用掉免費額度的 13%。

**指標與網頁完全一致。** `ema` / `smoothrng` / `rngfilt` 與訊號條件是從 `index.html`
逐行搬過來的，暖機區同樣丟掉前 6×300 = 1,800 根，休市時段同樣剔除。
兩邊算出來的訊號會是同一個。

**只推已收盤確認的訊號。** 盤中訊號會反悔，推了又縮回去很煩。
`ONLY_CONFIRMED = true` 表示等那根 11 分 K 收完、訊號定案才推。
想要早一步知道就把它改成 `false`。

**同一根 K 只推一次**，記在 KV 的 `alerted`。開始跑之後三根以內的新訊號才推，
避免第一次部署時把幾天前的舊訊號翻出來吵你。

## 要改參數

`src/worker.js` 最上面那幾行常數（`SYMBOL`、`TF_MIN`、`PER`、`MULT`）要跟網頁保持一致，
改完重新 `npx wrangler deploy`。兩邊不一致的話，推播講的訊號跟你在網頁上看到的會對不起來。
