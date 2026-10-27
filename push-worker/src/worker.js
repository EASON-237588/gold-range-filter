/**
 * LINE「黃金訊號」推播 —— Cloudflare Worker
 *
 * 2026-10-18 起推兩組，走兩條完全不同的路：
 *
 *   ① 那斯達克 短趨勢・B2（cron 每分鐘自己算）
 *      Gate QQQ_USDT 合約「逐筆成交」合成 37 秒 K，Range Filter 450/23，多空反轉。
 *      與指數趨勢儀表板「短趨勢・B2」那格同一套，算法在 gate_rf.js。
 *      原本推的是 B（30 秒 200/23），2026-10-18 使用者指定「推播只上 B2」，B 不再推。
 *      為什麼用逐筆：Gate 的原生 K 線間隔只有 1／10／30 秒與 1 分，拼不出 37 秒（37 不是 10 或 30 的倍數）；
 *      1 秒 K 雖拼得出來但只保留最近一萬根（約 2.8 小時），不夠 B2 暖機要的約 28 小時。
 *      逐筆可依時間範圍回溯很久、每分鐘只約 31 筆，比 60 根 1 秒 K 還省。
 *      為什麼不用 Binance：Binance 整個封鎖 Cloudflare（10/12 實測東京等 8 個機房全 403），換機房沒用。
 *
 *   ② 台指期・A/B（不自己算，由 TradingView 警報打進來）
 *      TradingView 版面 848 右上那格（微台連續月 30 秒、取樣 200／倍數 24）跟儀表板吻合度 98.2%、
 *      平均只差 1.1 分鐘，是六格裡最準的。走這條一次省掉三個坑：換倉（連續月自己換約，不必處理近次月
 *      約 170 點價差）、資料拼接（期交所盤後逐筆檔＋即時 K）、台指日夜盤與休息時段判斷。
 *      LINE 要在標頭帶權杖，而 TradingView 警報只能打一個網址、不能自訂標頭，所以警報打進本 worker 的
 *      /tvalert?k=TV_KEY，由這裡代發 LINE。放在這支而不是台指即時轉接站，是因為 LINE 權杖本來就在這裡，
 *      不必再多設一份密鑰、也少一個跳點。
 *      B2 不走這條路：它在 TradingView 上吻合度只有 75.7%，還會多出 10/14 那種一分鐘假翻轉。
 *
 * B2 每分鐘做的事：抓 Gate 最近 15 分鐘逐筆 → 合成 37 秒 K → 併進記憶的歷史 → 算部位 →
 *                 跟「上次通知的方向」不同就推 LINE。
 * 歷史不足暖機時（剛部署、或 KV 被清掉）改成「往回補」模式：每分鐘往回抓半小時逐筆，
 * 要補到 2,760 根（約 28.4 小時交易時段）才開始算策略，約一個多小時；中間跨到週末時根數不會增加，
 * 所以「已往回抓到哪一秒」要自己記（bt），不能拿最早一根的時間去推，否則會卡在週末原地打轉。
 * KV 免費每天只能寫 1,000 次，所以 K 線平常每 5 分鐘才存一次（一天約 288 次），狀態只在推播後寫。
 * 只存美國期貨交易時段的 K：週末占 2 天，存全部會在週一被洗光。
 *
 * 端點（有設 ADMIN_KEY 時要帶 ?key=）：
 *   GET  /        目前狀態（根數、暖機進度、方向、上次通知）
 *   GET  /run     手動跑一次 B2
 *   GET  /test    發一則測試訊息
 *   POST /tvalert?k=TV_KEY   TradingView 警報進來的台指訊號（用自己的 TV_KEY，不是 ADMIN_KEY）
 */
/* 2026-10-27 上午改推「乙」（45 秒 576/27），傍晚使用者又改回 B2（37 秒 450/23）。上面 ① 的說明照樣適用。
   退回 B2 時視窗維持 6,000 根（不回到舊的 WARM + 1300），理由見 KEEP。
   2026-10-27 晚（HP）使用者指定「平衡板取代 B2」：同一份逐筆合成甲 30 秒、乙 45 秒兩組 K（各存一個鍵、各 6,000 根），
   各算 Range Filter（555/31.9、576/27），在甲的 30 秒時間軸上取「已收完的最後一根乙」，同向才持有、分歧或任一空手就空手
   （同期貨趨勢 recomputeBal）。進多、進空、轉空手都推。B2 的 b2bars／g2state 留在 KV 不刪。 */
import {calcRF, cmeOpen, J30, Y45} from "./gate_rf.js";

const CONTRACT = "QQQ_USDT";
const GATE     = "https://api.gateio.ws/api/v4/futures/usdt";
const SERIES   = [Object.assign({key: "baljbars", ms: J30.tf * 1000}, J30),
                  Object.assign({key: "balybars", ms: Y45.tf * 1000}, Y45)];
/* 乙改存 6,000 根（2026-10-27 本機重播對帳）：拿 10/1～10/27 的 Gate 逐筆，照本程式「每根收盤後只拿最後 KEEP 根重算」
   一根一根重播，跟紀錄程式從頭算的 24 次翻向比：4,756 根（暖機＋1,300）與 5,000 根都會在 10/13 提早 2～4 小時推「翻多」
   （視窗太短，濾網的平滑均線取樣 1,151 根還沒收斂）；5,400 根起 24 次全部同一根推出，取 6,000 留餘裕。
   這台實測 6,000 根：算策略 0.9、解析 KV 0.8、寫 KV 1.3 毫秒。下面原本 B2 的說明（有效段、不表態）照樣適用。
   2026-10-27 傍晚退回 B2 前同樣重播（10/6～10/27 Gate 逐筆合成 37 秒，35 次翻向）：6,000 與 5,400 根全部同一根推出；
   B2 舊的 4,000 根（暖機＋1,300）會在 10/19 06:40 提早 3 分鐘推「翻多」，所以不回到舊視窗。運算約 3.6 毫秒。 */
export const KEEP = 6000;
/* 要補滿到接近 KEEP 才開始算策略（B2 時代是 WARM + 60）：視窗不滿 5,400 根時會像上面那樣提早推。
   代價是剛部署（或 KV 被清掉）要往回補約 150 輪（約兩個半小時）才開始推。減 5 是因為最後一根常還沒收完。 */
export const NEED = KEEP - 5;
/* （B2 時代是 KEEP = WARM + 1300）存幾根交易時段 K。多出來的 1,300 根是「有效段」：
                                          每輪都拿最後 KEEP 根重算，暖機 2,700 根之後才算得出部位。
                                          有效段內若還沒發生過方向改變，部位會是 0（不表態），worker 對 0 就是不推播；
                                          真的翻轉時方向一定算得對（本機對帳 10 個翻轉點全對），所以不會錯推也不會漏推。
                                          原本設 600 根（6 小時），B2 平均一天才翻 1～2 次，過半時間都在不表態，故放寬。 */
const TAIL_S   = 900;               // 平常每輪往後抓幾秒的逐筆（15 分鐘，約 475 筆）
const BACK_S   = 1800;              // 暖機不足時每輪往回抓幾秒的逐筆（半小時，約 950 筆）
/* 資料版本：合成規則一改就 +1，記憶體與 KV 裡的舊資料會整個作廢、重新補。
   沒有這個的話，改完規則後舊資料會一直被沿用——cron 的執行個體只要還活著，
   模組層的 MEM 每輪都更新時間戳就永遠不過期，連把 KV 刪掉都沒用（2026-10-18 實際踩到：
   刪了 KV、重新部署，進度照樣從 294 接著跳到 342）。 */
/* 4：2026-10-27 傍晚 乙 → B2。**B2 的舊 K（g2bars）不能沿用**：它停在上午切換那一刻，
   推播程式每輪只往後抓最近 15 分鐘、往回補只從最舊那根往前，中間的空檔不會被補——
   空檔超過 2 小時會被當成休市跳過（K 線少一段），小於 2 小時又會被 fillFlat 補成假平盤 K。
   所以 K 用新鍵 b2bars 從頭補；推播方向沿用 B2 原本的 g2state（暖機期間若已翻向，補滿後會推一則「延遲通知」）。
   乙的 y45bars／y45state 留在 KV，但同樣會過期，要再改回乙也要換新鍵重補。 */
/* 5：2026-10-27 晚 B2 → 平衡板。甲、乙兩組 K 用新鍵 baljbars／balybars 從頭補，方向用新鍵 balstate
   （第一次算完只記方向不推）。 */
const DATA_VER = 5;
const K_STATE  = "balstate";
/* 平常每 10 分鐘才把 K 線寫回 KV（一天約 144 次，KV 免費一天 1,000 次）。
   本機實測一輪的運算：合成 0.05／併進歷史 1.3／算策略 2.0／讀 KV 2.0／寫 KV 3.1 毫秒，
   最壞（又讀又寫）8.4 毫秒，而免費方案每次只有 10 毫秒——所以刻意把寫入拉疏，
   降低同一輪又讀又寫撞在一起的機率。往回補歷史時每輪都寫（那時不算策略，省下 2 毫秒）。 */
const SAVE_MS  = 10 * 60000;
const DASH     = "https://eason-237588.github.io/index-trend-dashboard/";

const pack   = B => B.map(b => [b.t, b.h, b.l, b.c, b.v]);
const unpack = A => A.map(a => ({t: a[0], h: a[1], l: a[2], c: a[3], v: a[4]}));
const tw = t => new Date(t).toLocaleString("zh-TW", {timeZone: "Asia/Taipei", hour12: false,
  month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"});

async function jget(url, opt){
  const r = await fetch(url, Object.assign({cf: {cacheTtl: 0}}, opt || {}));
  if(!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

/* Gate 逐筆成交。一頁最多 1,000 筆，滿了就對半切（同 更新紀錄.py 的 gate_trades）。
   注意：create_time_ms 這個欄位名稱寫毫秒，實際是「秒」帶小數，一律用 create_time × 1000。 */
export async function trades(fromS, toS, depth){
  const j = await jget(`${GATE}/trades?contract=${CONTRACT}&limit=1000&from=${fromS}&to=${toS}`);
  if(j.length >= 1000 && toS - fromS > 10 && (depth || 0) < 6){
    const m = Math.floor((fromS + toS) / 2);
    const [a, b] = await Promise.all([trades(fromS, m, (depth || 0) + 1), trades(m, toS, (depth || 0) + 1)]);
    return a.concat(b);
  }
  return j.map(x => [Math.round(parseFloat(x.create_time) * 1000), parseFloat(x.price), Math.abs(parseFloat(x.size))]);
}

/* 逐筆 → 37 秒 K，切法同 更新紀錄.py 的 bars_G／儀表板的 GTR：
   桶從 1970 起算（成交時間 / 37 秒 取整）、交易時段用「成交時間」判斷（與 bars_G 一字不差）。
   這裡「不」補沒成交的空桶，補空桶交給 fillFlat 對整個陣列一次做，兩種做法等價，
   但這樣增量併資料才不會接錯。
   lo／hi：抓取窗口切到一半的桶不完整，整根丟掉——它在歷史裡已經是完整的（或下一輪會補回來）。 */
export function aggTrades(tr, lo, hi, TF_MS){
  const out = [];
  /* **一定要先排序**：Gate 的逐筆是「最新在前」的降序，而下面是順著掃、只認「同一根或更新的桶」，
     沒排序的話每一段只會留下最新那一根（2026-10-18 實測：839 筆逐筆只合成出 1 根 K）。
     更新紀錄.py 的 gate_trades 最後有一行 sorted()，移植時漏掉了；
     而本機對帳用的逐筆是 Python 排序後才存檔的，所以對帳全過也照樣沒抓到這個 bug。
     排序鍵要連價格、數量一起比（對應 Python 對 (時間, 價格, 數量) 這個 tuple 排序）：
     同一毫秒內有多筆成交時，只排時間的話那根 K 的收盤會取到不同的一筆，實測 11,193 根裡有 103 根對不上
     （部位不受影響，但對帳要一字不差）。注意這跟台指盤後檔的規則相反——那邊要保留檔案原順序。 */
  for(const [T, p, q] of tr.slice().sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2])){
    if(!cmeOpen(T)) continue;
    const s = Math.floor(T / TF_MS) * TF_MS;
    if(s < lo || (hi != null && s >= hi)) continue;
    const last = out.length ? out[out.length - 1] : null;
    if(!last || s > last.t) out.push({t: s, h: p, l: p, c: p, v: q});
    else if(s === last.t){ last.h = Math.max(last.h, p); last.l = Math.min(last.l, p); last.c = p; last.v += q; }
  }
  return out;
}

/* 往回找「上一個還在交易時段內的時刻」。休市（週末、每天 17～18 點）時用它一步跳過去，
   不必每輪半小時慢慢爬。1 分鐘步長、最多往回 4 天；cmeOpen 本身有小時快取，很便宜。 */
function lastOpen(t){
  for(let i = 0, x = t; i < 4 * 24 * 60; i++, x -= 60000) if(cmeOpen(x)) return x;
  return t - 4 * 86400000;
}

/* 相鄰兩根之間沒成交的桶，用前一根的收盤補平盤 K（成交量 0）。
   缺口超過 2 小時不補——那是休市，補了會生出一堆假 K。成交量過濾會讓平盤根不發訊號，與儀表板一致。 */
export function fillFlat(B, TF_MS){
  const out = [];
  for(let i = 0; i < B.length; i++){
    const b = B[i];
    if(i){
      const prev = B[i - 1], gap = b.t - prev.t;
      if(gap > TF_MS && gap <= 2 * 3600000)
        for(let x = prev.t + TF_MS; x < b.t; x += TF_MS)
          if(cmeOpen(x)) out.push({t: x, h: prev.c, l: prev.c, c: prev.c, v: 0});
    }
    out.push(b);
  }
  return out;
}

/* 併進歷史：同一個桶後到的覆蓋先到的（重抓時成交量更完整）。
   先把補出來的平盤根（成交量 0）丟掉再重補，否則平盤根會卡在真資料前面，害補洞算錯缺口。 */
export function merge(old, add, TF_MS){
  const m = new Map(old.filter(b => b.v > 0).map(b => [b.t, b]));
  for(const b of add) m.set(b.t, b);
  const B = fillFlat([...m.values()].sort((a, b) => a.t - b.t), TF_MS);
  return B.length > KEEP ? B.slice(-KEEP) : B;
}

async function lineSend(env, text){
  if(!env.LINE_TOKEN) return {ok: false, err: "沒有設定 LINE_TOKEN"};
  const to = (env.LINE_TO || "").trim();
  const url  = to ? "https://api.line.me/v2/bot/message/push" : "https://api.line.me/v2/bot/message/broadcast";
  const body = to ? {to, messages: [{type: "text", text}]} : {messages: [{type: "text", text}]};
  const r = await fetch(url, {method: "POST",
    headers: {"Authorization": `Bearer ${env.LINE_TOKEN}`, "Content-Type": "application/json"},
    body: JSON.stringify(body)});
  return {ok: r.ok, status: r.status, err: r.ok ? null : await r.text()};
}

// 那斯達克點數換算：Hyperliquid 那斯達克 100 合約 ÷ QQQ 合約（同儀表板）
async function ndx(){
  try{
    const j = await jget("https://api.hyperliquid.xyz/info", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({type: "allMids", dex: "xyz"})});
    return +j["xyz:XYZ100"] || null;
  }catch(e){ return null; }
}

/* 同一個執行個體連續被叫到時，沿用記憶體裡上一輪的 K 線，省掉讀 KV＋解析幾千根 JSON
   （免費方案每次只有 10 毫秒 CPU）。超過 10 分鐘沒更新就回頭讀 KV。 */
let MEM = null;

/* 平衡板部位（同期貨趨勢 recomputeBal）：在甲的時間軸上，取「收盤時間 ≤ 這根甲收盤」的最後一根乙；
   甲乙都過暖機後，同向就持有該方向，分歧（或任一還沒表態）就空手。回傳每根甲的部位。 */
export function balPos(J, pj, wj, Y, py, wy){
  const pos = new Array(J.length).fill(0);
  let k = -1;
  for(let i = 0; i < J.length; i++){
    const t = J[i].t + J30.tf * 1000;
    while(k + 1 < Y.length && Y[k + 1].t + Y45.tf * 1000 <= t) k++;
    if(i < wj || k < 0 || k < wy) continue;
    pos[i] = pj[i] === py[k] ? pj[i] : 0;
  }
  return pos;
}

/* 推播用的「現在」平衡板方向。視窗只有 KEEP 根，某一組在視窗內若一直沒翻向，calcRF 最後一根是 0（不表態），
   那不是空手——要沿用它上次確定的方向（存在狀態 jd／yd）。B2 時代遇 0 不推所以沒事；平衡板把 0 當分歧會一直推
   「轉空手」（2026-10-27 逐根重播實測：10/23 起乙不表態，空／空手每分鐘來回，多推 64 次）。
   回傳 cur：1 多／-1 空／0 分歧空手／null 兩組還沒都確定方向；at：甲或乙最近一次翻到現在方向的那根收盤時間（取較晚者）。 */
export function balNow(J, pj, Y, py, prev){
  const lj = pj[pj.length - 1], ly = py[py.length - 1];
  const jd = lj || prev.jd || 0, yd = ly || prev.yd || 0;
  const cur = jd && yd ? (jd === yd ? jd : 0) : null;
  let at = 0;
  if(lj){ let i = pj.length - 1; while(i > 0 && pj[i - 1] === lj) i--; at = Math.max(at, J[i].t + J30.tf * 1000); }
  if(ly){ let k = py.length - 1; while(k > 0 && py[k - 1] === ly) k--; at = Math.max(at, Y[k].t + Y45.tf * 1000); }
  return {cur, jd, yd, at};
}

async function tick(env){
  const now = Date.now(), nowS = Math.floor(now / 1000);
  const fresh = MEM && MEM.ver === DATA_VER && now - MEM.at < 10 * 60000;
  /* 補歷史期間（任一組不足）每輪都讀 KV，跟記憶體裡的合併：雲端常有兩個執行個體輪流跑，
     各自只看自己的 MEM 會各補各的、重抓同一段（2026-10-27 部署後實測：16:44 與 17:14 兩份進度交替，速度減半）。
     補滿後照舊只用 MEM（省讀 KV 與解析）。 */
  const warmingMem = fresh && SERIES.some(s => (MEM.bars[s.key] || []).length < NEED);
  const S = [];
  for(const s of SERIES){
    let stored;
    if(fresh && !warmingMem) stored = MEM.bars[s.key];
    else{
      const raw = (await env.STATE.get(s.key, "json")) || {};
      stored = raw.v === DATA_VER ? unpack(raw.b || []) : [];
      if(warmingMem) stored = merge(stored, MEM.bars[s.key] || [], s.ms);
    }
    const kvLast = fresh ? MEM.kvLast[s.key] : (stored.length ? stored[stored.length - 1].t : 0);
    S.push({s, B: stored, kvLast});
  }

  /* 每一輪都先追最新（1 個請求，兩組共用同一份逐筆）。補歷史期間也要追，否則最新端會停在部署那一刻，
     補完後與最新資料之間裂開一小時左右——那個缺口小於 2 小時，會被 fillFlat 補成近百根
     假平盤 K，價格不動會把 EMA 壓平、濾網帶寬縮小，生出假訊號。 */
  const tailFrom = nowS - TAIL_S, tailTr = await trades(tailFrom, nowS);
  for(const x of S){
    const lo = Math.ceil(tailFrom * 1000 / x.s.ms) * x.s.ms;
    x.B = merge(x.B, aggTrades(tailTr, lo, null, x.s.ms), x.s.ms);
  }

  /* 暖機不足就往回補。
     **進度不存任何地方**：手上最早那根 K 就是進度，一根都還沒有時用 lastOpen 從交易時段規則算。
     2026-10-18 踩過的教訓：原本把「已往回抓到哪一秒」記在 KV，但 KV 是最終一致、寫進去最久要一分鐘
     才讀得到，而 cron 正好每分鐘跑一次 → 下一輪常讀到寫入前的舊值，進度歸零、原地打轉
     （雲端實測 10:58 → 10:59 → 08:02 → 11:01）。改成從 K 自己推導後就完全不受影響，
     而且即使讀到舊的 K 也只是重抓同一段（冪等），不會倒退。
     休市那段用 lastOpen 一步跳過去，跨整個週末只要一輪。 */
  /* 兩組任一不足就往回補。錨點取「還不足的那組」最早那根（乙的 45 秒 K 涵蓋時間較長，通常是乙），
     抓到的逐筆兩組都併。已經滿的那組多出來的舊 K 會被 merge 切掉，不影響。 */
  const short = () => S.filter(x => x.B.length < NEED);
  const back = short().length > 0;
  let hops = 0, dbg = null;
  if(back) while(hops < 4 && short().length){
    const ref = short().reduce((a, x) => !a || !x.B.length || (a.B.length && x.B[0].t < a.B[0].t) ? x : a, null);
    let toMs = ref.B.length ? ref.B[0].t : now - TAIL_S * 1000;
    if(!cmeOpen(toMs - 60000)) toMs = lastOpen(toMs - 60000) + 60000;   // 跳過休市
    const to = Math.floor(toMs / 1000), from = to - BACK_S;
    const before = ref.B.length;
    const raw = await trades(from, to);
    for(const x of S){
      const lo = Math.ceil(from * 1000 / x.s.ms) * x.s.ms;
      x.B = merge(x.B, aggTrades(raw, lo, toMs, x.s.ms), x.s.ms);
    }
    hops++;
    dbg = {seg: `${tw(from * 1000)}→${tw(to * 1000)}`, 逐筆: raw.length, 併入後: ref.B.length - before};
    if(ref.B.length > before) break;      // 這段真的補到東西了，下一輪再往回
  }

  /* 存檔判斷要看「KV 裡最後一根」；往回補的時候每輪都存（那時不算策略），進度才跟得上。
     平常兩組都到期時一輪只存一組（存最久沒存的那組），另一組下一輪再存——
     一組 6,000 根寫 KV 約 1.3 毫秒，兩組再加兩次策略計算會逼近免費方案每次 10 毫秒的上限。 */
  const due = S.filter(x => { const nc = [...x.B].reverse().find(b => b.t + x.s.ms <= now);
    x.nc = nc; return nc && (back || nc.t - x.kvLast >= SAVE_MS); });
  const toSave = back ? due : due.sort((a, b) => a.kvLast - b.kvLast).slice(0, 1);
  for(const x of toSave){
    await env.STATE.put(x.s.key, JSON.stringify({v: DATA_VER, b: pack(x.B.filter(b => b.t + x.s.ms <= now))}));
    x.kvLast = x.nc.t;
  }
  MEM = {bars: Object.fromEntries(S.map(x => [x.s.key, x.B])), at: now,
         kvLast: Object.fromEntries(S.map(x => [x.s.key, x.kvLast])), ver: DATA_VER};

  for(const x of S) x.done = x.B.filter(b => b.t + x.s.ms <= now);
  if(S.some(x => x.done.length < NEED)){
    const y = S[1];
    return {warming: true, 甲: S[0].done.length, 乙: y.done.length, need: NEED,
            pct: Math.round(Math.min(...S.map(x => x.done.length)) / NEED * 100) + "%",
            oldest: y.done.length ? tw(y.done[0].t) : null, hops, dbg,
            eta: `約 ${Math.ceil((NEED - Math.min(...S.map(x => x.done.length))) * Y45.tf / BACK_S)} 分鐘`};
  }

  const [J, Y] = S.map(x => x.done);
  const rj = calcRF(J, J30.per, J30.mult), ry = calcRF(Y, Y45.per, Y45.mult);
  const st = (await env.STATE.get(K_STATE, "json")) || {notified: null};
  const {cur, jd, yd, at} = balNow(J, rj.pos, Y, ry.pos, st);
  const keep = {jd, yd};
  if(cur == null){       // 兩組還沒都確定方向：只把已確定的那組記下來
    if(jd !== st.jd || yd !== st.yd) await env.STATE.put(K_STATE, JSON.stringify({...st, ...keep}));
    return {ok: true, note: "甲乙方向還沒都確定", 甲: jd, 乙: yd};
  }
  if(st.notified == null){
    await env.STATE.put(K_STATE, JSON.stringify({notified: cur, at: now, ...keep}));
    return {ok: true, note: "第一次：只記方向不推", cur, 甲: jd, 乙: yd};
  }
  if(cur === st.notified){
    if(jd !== st.jd || yd !== st.yd) await env.STATE.put(K_STATE, JSON.stringify({...st, ...keep}));
    return {ok: true, cur, 甲: jd, 乙: yd};
  }

  // 訊號那根＝收盤時間不早於翻向那根的第一根甲（乙收在兩根甲之間時，要等下一根甲收盤才算進去，同 balPos）
  const b = J.find(x => x.t + J30.tf * 1000 >= at) || J[J.length - 1];
  const late = now - (b.t + J30.tf * 1000) > 5 * 60000;
  const pj = jd, py = yd, side = d => d > 0 ? "多" : d < 0 ? "空" : "未定";
  const nd = await ndx(), q = J[J.length - 1].c;
  const price = nd ? `${Math.round(b.c * nd / q).toLocaleString("en-US")}（QQQ 合約 ${b.c.toFixed(2)}）` : `QQQ 合約 ${b.c.toFixed(2)}`;
  const head = cur > 0 ? "▲ 進多" : cur < 0 ? "▼ 進空" : `◇ 轉空手（平${side(st.notified)}單）`;
  const text =
    `${head}${late ? "（延遲通知）" : ""}\n` +
    `那斯達克 平衡板（甲 30 秒 555/31.9＋乙 45 秒 576/27 同向才持有）\n` +
    `甲 ${side(pj)}／乙 ${side(py)}\n\n` +
    `訊號時間　${tw(b.t)}\n` +
    `訊號價　　${price}\n\n${DASH}`;
  const sent = await lineSend(env, text);
  if(sent.ok) await env.STATE.put(K_STATE, JSON.stringify({notified: cur, at: now, flip: b.t, ...keep}));
  console.log(JSON.stringify({push: cur, at: tw(b.t), line: sent}));
  return {ok: sent.ok, pushed: cur, at: tw(b.t), line: sent};
}

/* TradingView 警報 → LINE。警報訊息原文（Pine 的 alert() 內容）就是要發出去的字，
   這裡只加上儀表板網址。同一則內容 3 分鐘內重複進來就不再發（TradingView 偶爾會重送）。 */
const K_TV = "tvlast";
async function tvAlert(env, text){
  const msg = (text || "").trim();
  if(!msg) return {ok: false, err: "沒有內容"};
  if(msg.length > 400) return {ok: false, err: "內容過長"};
  const now = Date.now();
  const last = (await env.STATE.get(K_TV, "json")) || {};
  if(last.msg === msg && now - (last.at || 0) < 3 * 60000) return {ok: true, skipped: "3 分鐘內的重複警報"};
  const sent = await lineSend(env, `${msg}\n\n${DASH}`);
  if(sent.ok) await env.STATE.put(K_TV, JSON.stringify({msg, at: now}));
  console.log(JSON.stringify({tv: msg, line: sent}));
  return {ok: sent.ok, sent: msg, line: sent};
}

const json = o => new Response(JSON.stringify(o, null, 2), {headers: {"content-type": "application/json; charset=utf-8"}});

export default {
  async scheduled(_e, env, ctx){
    // 每輪留一行摘要，這樣 `npx.cmd wrangler tail` 不帶 ADMIN_KEY 也看得到暖機進度與錯誤
    ctx.waitUntil(tick(env).then(r => console.log(JSON.stringify(r))).catch(e => console.log("錯誤", String(e))));
  },
  async fetch(req, env){
    const u = new URL(req.url);
    // TradingView 警報走自己的 TV_KEY（警報網址存在 TradingView 上，不要把 ADMIN_KEY 放進去）
    if(u.pathname === "/tvalert"){
      if(!env.TV_KEY || u.searchParams.get("k") !== env.TV_KEY.trim()) return new Response("Not found", {status: 404});
      if(req.method !== "POST") return new Response("Not found", {status: 404});
      try{ return json(await tvAlert(env, await req.text())); }
      catch(e){ return json({error: String((e && e.message) || e)}); }
    }
    if(env.ADMIN_KEY && u.searchParams.get("key") !== env.ADMIN_KEY) return new Response("Not found", {status: 404});
    try{
      if(u.pathname === "/run")  return json(await tick(env));
      if(u.pathname === "/test") return json(await lineSend(env, "黃金訊號推播測試\n收到這則就代表設定成功。"));
      const info = {};
      for(const s of SERIES){
        const rawS = (await env.STATE.get(s.key, "json")) || {};
        const B = rawS.v === DATA_VER ? unpack(rawS.b || []) : [];
        info[s.name] = {bars: B.length, warmed: B.length >= NEED,
          oldest: B.length ? tw(B[0].t) : null, newest: B.length ? tw(B[B.length - 1].t) : null};
      }
      return json({strategy: `那斯達克平衡板：${CONTRACT} 逐筆合成 甲 30 秒 RF 555/31.9＋乙 45 秒 RF 576/27，同向才持有`,
        need: NEED, ...info,
        state: await env.STATE.get(K_STATE, "json"),
        tvLast: await env.STATE.get(K_TV, "json"),
        lineConfigured: !!env.LINE_TOKEN, tvConfigured: !!env.TV_KEY});
    }catch(e){ return json({error: String((e && e.message) || e)}); }
  }
};
