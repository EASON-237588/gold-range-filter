/**
 * LINE「黃金訊號」推播 —— Cloudflare Worker
 *
 * 2026-10-12 起只推一組：那斯達克短趨勢・Gate 版（Gate QQQ_USDT 合約 30 秒 K，Range Filter 200/23，
 * 多空反轉；與指數趨勢儀表板「短趨勢・Gate」那格同一套，算法在 gate_rf.js）。
 * 先前推過的黃金 Range Filter（9/02～10/12）、黃金上方 Donchian（10/12）與電腦端 A-1 代轉都已移除（使用者指定）。
 * 為什麼是 Gate：Binance 整個封鎖 Cloudflare（10/12 實測東京等 8 個機房全 403），A-1 的資料拿不到。
 *
 * 每分鐘：抓 Gate 最後 30 根 30 秒 K → 併進記憶的歷史 → 取最近 5,000 根算部位 →
 *        跟「上次通知的方向」不同就推 LINE。
 * KV 免費每天只能寫 1,000 次，所以 K 線每 5 分鐘才存一次（一天約 288 次），狀態只在推播後寫。
 * 只存美國期貨交易時段的 K：Gate 只能回溯約 3.5 天，週末就占 2 天，存全部會在週一被洗光。
 *
 * 端點（有設 ADMIN_KEY 時要帶 ?key=）：
 *   GET /      目前狀態（根數、方向、上次通知）
 *   GET /run   手動跑一次
 *   GET /test  發一則測試訊息
 */
import {calcRF, cmeOpen, PER, MULT} from "./gate_rf.js";

const CONTRACT = "QQQ_USDT";
const GATE     = "https://api.gateio.ws/api/v4/futures/usdt";
const KEEP     = 5200;              // 存幾根交易時段 30 秒 K（暖機 1,200 根＋計算 5,000 根）
const WINDOW   = 5000;
const K_BARS   = "gbars";
const K_STATE  = "gstate";
const SAVE_MS  = 5 * 60000;
const DASH     = "https://eason-237588.github.io/index-trend-dashboard/";

const pack   = B => B.map(b => [b.t, b.h, b.l, b.c, b.v]);
const unpack = A => A.map(a => ({t: a[0], h: a[1], l: a[2], c: a[3], v: a[4]}));
const gk = k => ({t: k.t * 1000, h: +k.h, l: +k.l, c: +k.c, v: +k.v});
const tw = t => new Date(t).toLocaleString("zh-TW", {timeZone: "Asia/Taipei", hour12: false,
  month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"});

async function jget(url, opt){
  const r = await fetch(url, Object.assign({cf: {cacheTtl: 0}}, opt || {}));
  if(!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
// 抓 [from, to] 秒之間的 30 秒 K，一頁最多 2,000 根
async function candles(from, to){
  const out = [];
  for(let a = from; a < to && out.length < 12000; a += 30 * 1999){
    const r = await jget(`${GATE}/candlesticks?contract=${CONTRACT}&interval=30s&from=${a}&to=${Math.min(to, a + 30 * 1999)}`);
    out.push(...r.map(gk));
  }
  return out;
}
function merge(old, add){
  const m = new Map(old.map(b => [b.t, b]));
  for(const b of add) if(cmeOpen(b.t)) m.set(b.t, b);
  const B = [...m.values()].sort((a, b) => a.t - b.t);
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

/* 同一個執行個體連續被叫到時，沿用記憶體裡上一輪的 K 線，省掉讀 KV＋解析 5,000 根 JSON
   （免費方案每次只有 10 毫秒 CPU，實測不沿用時每輪 7～12 毫秒）。超過 10 分鐘沒更新就回頭讀 KV。 */
let MEM = null;

async function tick(env){
  const now = Date.now(), nowS = Math.floor(now / 1000);
  const stored = MEM && now - MEM.at < 10 * 60000 ? MEM.bars
               : unpack((await env.STATE.get(K_BARS, "json")) || []);
  const lastT = stored.length ? stored[stored.length - 1].t : 0;
  // 斷太久（或第一次）就往回補；平常只抓最後 30 根（15 分鐘）
  const from = lastT && nowS - lastT / 1000 < 900 ? nowS - 900 : Math.max(nowS - 30 * 9990, Math.floor(lastT / 1000));
  const B = merge(stored, await candles(from, nowS));

  // 存檔判斷要看「KV 裡最後一根」，記憶體沿用時另外記
  const kvLast = MEM ? MEM.kvLast : lastT;
  const newestClosed = [...B].reverse().find(b => b.t + 30000 <= now);
  let saved = kvLast;
  if(newestClosed && newestClosed.t - kvLast >= SAVE_MS){
    await env.STATE.put(K_BARS, JSON.stringify(pack(B.filter(b => b.t + 30000 <= now))));
    saved = newestClosed.t;
  }
  MEM = {bars: B, at: now, kvLast: saved};

  const done = B.filter(b => b.t + 30000 <= now).slice(-WINDOW);
  if(done.length < 6 * PER + 50) return {skipped: "歷史不足", have: done.length};
  const {pos} = calcRF(done);
  const cur = pos[pos.length - 1];
  const st = (await env.STATE.get(K_STATE, "json")) || {notified: null};

  if(st.notified == null){
    await env.STATE.put(K_STATE, JSON.stringify({notified: cur, at: now}));
    return {ok: true, note: "第一次：只記方向不推", cur};
  }
  if(cur === 0 || cur === st.notified) return {ok: true, cur, bars: done.length};

  let i = pos.length - 1;
  while(i > 0 && pos[i - 1] === cur) i--;
  const b = done[i], late = now - (b.t + 30000) > 5 * 60000;
  const nd = await ndx(), q = done[done.length - 1].c;
  const price = nd ? `${Math.round(b.c * nd / q).toLocaleString("en-US")}（QQQ 合約 ${b.c.toFixed(2)}）` : `QQQ 合約 ${b.c.toFixed(2)}`;
  const text =
    `${cur > 0 ? "▲ 翻多" : "▼ 翻空"}${late ? "（延遲通知）" : ""}\n` +
    `那斯達克 短趨勢・Gate（30 秒 RF ${PER}/${MULT}）\n\n` +
    `訊號時間　${tw(b.t)}\n` +
    `訊號價　　${price}\n\n${DASH}`;
  const sent = await lineSend(env, text);
  if(sent.ok) await env.STATE.put(K_STATE, JSON.stringify({notified: cur, at: now, flip: b.t}));
  console.log(JSON.stringify({push: cur, at: tw(b.t), line: sent}));
  return {ok: sent.ok, pushed: cur, at: tw(b.t), line: sent};
}

const json = o => new Response(JSON.stringify(o, null, 2), {headers: {"content-type": "application/json; charset=utf-8"}});

export default {
  async scheduled(_e, env, ctx){ ctx.waitUntil(tick(env).catch(e => console.log("錯誤", String(e)))); },
  async fetch(req, env){
    const u = new URL(req.url);
    if(env.ADMIN_KEY && u.searchParams.get("key") !== env.ADMIN_KEY) return new Response("Not found", {status: 404});
    try{
      if(u.pathname === "/run")  return json(await tick(env));
      if(u.pathname === "/test") return json(await lineSend(env, "黃金訊號推播測試\n收到這則就代表設定成功。"));
      const B = unpack((await env.STATE.get(K_BARS, "json")) || []);
      return json({strategy: `那斯達克短趨勢・Gate：${CONTRACT} 30 秒 RF ${PER}/${MULT}`,
        bars: B.length, newest: B.length ? tw(B[B.length - 1].t) : null,
        state: await env.STATE.get(K_STATE, "json"), lineConfigured: !!env.LINE_TOKEN});
    }catch(e){ return json({error: String((e && e.message) || e)}); }
  }
};
