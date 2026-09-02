/**
 * 黃金 Range Filter 訊號推播 —— Cloudflare Worker
 *
 * 每分鐘跑一次：抓最後幾根 1 分 K → 合成 11 分 K → 併進 KV 裡的歷史 →
 * 重算 Range Filter → 有新訊號就用 LINE Messaging API 推給你。
 *
 * 為什麼不是每次重抓兩萬根：Cloudflare 免費方案一次呼叫最多 50 個子請求，
 * 而且 KV 免費方案一天只有 1,000 次寫入。所以歷史存在 KV，每分鐘只抓尾巴（1 個請求），
 * 而且只有在「又收完一根 K」時才寫回 KV（一天約 131 次）。
 *
 * 端點：
 *   GET /            看目前狀態（歷史根數、最後訊號、上次推播）
 *   GET /bootstrap   第一次用要打幾次，把歷史補到 KEEP 根為止
 *   GET /test        發一則測試訊息到 LINE
 *   GET /run         手動跑一次偵測（不必等 cron）
 */

const SYMBOL   = "PAXGUSDT";
const TF_MIN   = 11;                 // 11 分 K
const PER      = 300;                // 取樣週期
const MULT     = 23;                 // 範圍乘數
const SESSION  = true;               // 剔除休市時段
const KEEP     = 3600;               // KV 保留幾根 11 分 K；剔除休市後約 2,450 根，暖機 1,800 之外還有餘裕
const WARM     = 6 * PER;            // 暖機區，與網頁一致
const ONLY_CONFIRMED = true;         // 只在那根 K 收完、訊號定案後才推

const TF_MS   = TF_MIN * 60000;
const K_BARS  = "bars";

// KV 只存訊號用得到的四個欄位，並用陣列而不是物件——
// 免費方案每次呼叫只有 10ms CPU，JSON.parse 的大小要斤斤計較
const pack   = bars => bars.map(b => [b.t, b.h, b.l, b.c]);
const unpack = arr  => arr.map(a => ({t: a[0], h: a[1], l: a[2], c: a[3]}));
const K_ALERT = "alerted";

/* ---------- 指標（與網頁 index.html 逐行等價） ---------- */
function ema(src, len){
  const a = 2 / (len + 1), out = new Array(src.length);
  let prev = null;
  for(let i = 0; i < src.length; i++){
    const v = src[i];
    if(v == null || !isFinite(v)){ out[i] = prev; continue; }
    prev = (prev === null) ? v : a * v + (1 - a) * prev;
    out[i] = prev;
  }
  return out;
}
function smoothrng(x, t, m){
  const diff = x.map((v, i) => i === 0 ? 0 : Math.abs(v - x[i - 1]));
  const avrng = ema(diff, t);
  return ema(avrng, t * 2 - 1).map(v => v == null ? null : v * m);
}
function rngfilt(x, r){
  const out = new Array(x.length);
  let prev = 0;
  for(let i = 0; i < x.length; i++){
    const xi = x[i], ri = (r[i] == null ? 0 : r[i]);
    out[i] = prev = xi > prev
      ? (xi - ri < prev ? prev : xi - ri)
      : (xi + ri > prev ? prev : xi + ri);
  }
  return out;
}
// 只需要最後一個訊號，圖表用不到的東西一律不算
function lastSignal(bars){
  const n = bars.length;
  const src = bars.map(b => (b.h + b.l) / 2);       // (H+L)/2
  const smrng = smoothrng(src, PER, MULT);
  const filt  = rngfilt(src, smrng);

  let up = 0, dn = 0, condIni = 0, found = null;
  for(let i = 0; i < n; i++){
    const pf = i ? filt[i - 1] : filt[0];
    const pu = up, pd = dn;
    up = filt[i] > pf ? pu + 1 : filt[i] < pf ? 0 : pu;
    dn = filt[i] < pf ? pd + 1 : filt[i] > pf ? 0 : pd;

    const moved = i > 0 && src[i] !== src[i - 1];
    const L = src[i] > filt[i] && moved && up > 0;
    const S = src[i] < filt[i] && moved && dn > 0;

    const prevIni = condIni;
    if(L) condIni = 1; else if(S) condIni = -1;

    if(i >= WARM){
      if(L && prevIni === -1) found = {i, dir:  1};
      if(S && prevIni ===  1) found = {i, dir: -1};
    }
  }
  return found;
}

/* ---------- 資料 ---------- */
function goldOpen(t){
  const d = new Date(t), day = d.getUTCDay(), h = d.getUTCHours();
  if(day === 6) return false;
  if(day === 0 && h < 22) return false;
  if(day === 5 && h >= 21) return false;
  if(h === 21) return false;
  return true;
}
function aggregate(bars1m, minutes){
  const ms = minutes * 60000, out = [];
  let cur = null;
  for(const b of bars1m){
    const bucket = Math.floor(b.t / ms) * ms;
    if(!cur || cur.t !== bucket){
      if(cur) out.push(cur);
      cur = {t: bucket, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v};
    }else{
      cur.h = Math.max(cur.h, b.h);
      cur.l = Math.min(cur.l, b.l);
      cur.c = b.c;
      cur.v += b.v;
    }
  }
  if(cur) out.push(cur);
  return out;
}
async function klines(limit, endTime){
  let url = `https://api.binance.com/api/v3/klines?symbol=${SYMBOL}&interval=1m&limit=${limit}`;
  if(endTime) url += `&endTime=${endTime}`;
  const r = await fetch(url, {cf: {cacheTtl: 0}});
  if(!r.ok) throw new Error(`Binance ${r.status}`);
  return (await r.json()).map(k => ({t: +k[0], o: +k[1], h: +k[2], l: +k[3], c: +k[4], v: +k[5]}));
}
function merge(oldBars, tail){
  if(!tail.length) return oldBars;
  const cut = tail[0].t;
  const out = oldBars.filter(b => b.t < cut).concat(tail);
  return out.length > KEEP ? out.slice(-KEEP) : out;
}

/* ---------- LINE ---------- */
async function lineSend(env, text){
  if(!env.LINE_TOKEN) return {ok: false, err: "沒有設定 LINE_TOKEN"};
  const to = (env.LINE_TO || "").trim();
  const url  = to ? "https://api.line.me/v2/bot/message/push"
                  : "https://api.line.me/v2/bot/message/broadcast";
  const body = to ? {to, messages: [{type: "text", text}]}
                  : {messages: [{type: "text", text}]};
  const r = await fetch(url, {
    method: "POST",
    headers: {"Authorization": `Bearer ${env.LINE_TOKEN}`, "Content-Type": "application/json"},
    body: JSON.stringify(body)
  });
  return {ok: r.ok, status: r.status, err: r.ok ? null : await r.text()};
}

const tw = t => new Date(t).toLocaleString("zh-TW", {timeZone: "Asia/Taipei", hour12: false});

/* ---------- 主流程 ---------- */
async function tick(env){
  const packed = await env.STATE.get(K_BARS, "json");
  const stored = packed ? unpack(packed) : null;
  if(!stored || stored.length < WARM + 400)
    return {skipped: "歷史不足，請先打 /bootstrap", have: stored ? stored.length : 0};

  // 抓最後 8 個時間桶的 1 分 K；聚合後第一桶會被截半，丟掉
  const raw = await klines(TF_MIN * 8);
  const tail = aggregate(raw, TF_MIN).slice(1);
  const merged = merge(stored, tail);

  const bars = SESSION ? merged.filter(b => goldOpen(b.t)) : merged;
  const sig  = lastSignal(bars);

  // 只有又收完一根 K 才寫回 KV，省 KV 寫入額度
  const isClosed = t => t + TF_MS <= Date.now();
  const newClosed = [...merged].reverse().find(b => isClosed(b.t));
  const oldClosed = [...stored].reverse().find(b => isClosed(b.t));
  if(newClosed && (!oldClosed || newClosed.t !== oldClosed.t))
    await env.STATE.put(K_BARS, JSON.stringify(pack(merged)));

  if(!sig) return {ok: true, note: "目前沒有訊號", bars: bars.length};

  const age = bars.length - 1 - sig.i;
  const bar = bars[sig.i];
  const key = String(bar.t);
  const alerted = await env.STATE.get(K_ALERT);

  if(alerted === key)              return {ok: true, note: "訊號已推播過", at: tw(bar.t)};
  if(age > 3)                      return {ok: true, note: "舊訊號，不推", at: tw(bar.t), age};
  if(ONLY_CONFIRMED && age < 1)    return {ok: true, note: "等這根 K 收完再推", at: tw(bar.t)};

  const now = bars[bars.length - 1].c;
  const since = (now / bar.c - 1) * 100 * sig.dir;
  const text =
    `${sig.dir > 0 ? "▲ 買進訊號" : "▼ 賣出訊號"}\n` +
    `黃金 ${SYMBOL.replace("USDT", "")} ${TF_MIN} 分\n\n` +
    `訊號時間　${tw(bar.t)}\n` +
    `訊號價　　${bar.c.toFixed(2)}\n` +
    `目前價　　${now.toFixed(2)}（${since >= 0 ? "+" : ""}${since.toFixed(2)}%）\n` +
    `狀態　　　已收盤確認\n\n` +
    `https://eason-237588.github.io/gold-range-filter/`;

  const sent = await lineSend(env, text);
  if(sent.ok) await env.STATE.put(K_ALERT, key);
  return {ok: sent.ok, pushed: sent.ok, at: tw(bar.t), dir: sig.dir, line: sent};
}

/* ---------- 分批補歷史（一次最多 25 個請求，免得撞到 50 子請求上限） ---------- */
async function bootstrap(env){
  const packed0 = (await env.STATE.get(K_BARS, "json")) || [];
  let bars = unpack(packed0);
  let endTime = bars.length ? bars[0].t - 1 : null;
  let pages = 0;

  while(bars.length < KEEP && pages < 25){
    const raw = await klines(1000, endTime);
    if(!raw.length) break;
    // 這一批最舊的那桶可能被截半，丟掉
    const chunk = aggregate(raw, TF_MIN).slice(1);
    if(!chunk.length) break;
    const edge = chunk[chunk.length - 1].t;
    bars = chunk.concat(bars.filter(b => b.t > edge));
    endTime = raw[0].t - 1;
    pages++;
    if(raw.length < 1000) break;
  }
  if(bars.length > KEEP) bars = bars.slice(-KEEP);
  await env.STATE.put(K_BARS, JSON.stringify(pack(bars)));
  return {bars: bars.length, need: KEEP, done: bars.length >= KEEP, pages,
          from: bars.length ? tw(bars[0].t) : null};
}

const json = o => new Response(JSON.stringify(o, null, 2),
  {headers: {"content-type": "application/json; charset=utf-8"}});

export default {
  async scheduled(_event, env, ctx){ ctx.waitUntil(tick(env)); },

  async fetch(req, env){
    const path = new URL(req.url).pathname;
    try{
      if(path === "/bootstrap") return json(await bootstrap(env));
      if(path === "/run")       return json(await tick(env));
      if(path === "/test")      return json(await lineSend(env,
        "黃金訊號推播測試\n收到這則就代表設定成功，之後只有真的出訊號才會再吵你。"));

      const bars = unpack((await env.STATE.get(K_BARS, "json")) || []);
      return json({
        symbol: SYMBOL, tf: `${TF_MIN}m`, per: PER, mult: MULT,
        bars: bars.length, need: KEEP,
        newest: bars.length ? tw(bars[bars.length - 1].t) : null,
        alerted: await env.STATE.get(K_ALERT),
        lineConfigured: !!env.LINE_TOKEN,
        mode: env.LINE_TO ? "push（指定對象）" : "broadcast（發給所有好友）"
      });
    }catch(e){
      return json({error: String((e && e.message) || e)});
    }
  }
};
