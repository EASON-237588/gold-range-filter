/**
 * 上方策略（V2.06 起 LINE 推播改推這一組）：11 分 Donchian 三態、只做多、1 段、停損 8 ATR、24/7 不剔除休市。
 * 規則逐行對齊 index.html 的 dirDonchian() + compute()（segs=1、mode=long、reverse=false）。
 *
 * 跟 Range Filter 不同，這套是有記憶的：一筆多單可以抱三週（2026/08/05→08/27），
 * KV 只留 3,600 根（約 27 天），每次從頭重算會把窗外開的單忘掉、漏推出場。
 * 所以狀態（dir／side／avg／blocked）存進 KV，每收一根 K 往下接著算。
 */

export const TF_MIN   = 11;
export const LOOK_H   = 350;                                  // 回看小時
export const LOOK     = Math.max(20, Math.round(LOOK_H * 60 / TF_MIN));   // 1909 根
export const EXIT_N   = Math.max(10, Math.round(LOOK / 3));    // 636 根
export const STOP_ATR = 8;
export const ATR_LEN  = 14;

/* Wilder ATR，與 index.html atrWilder() 一致：前 n 根 null、第 n 根用簡單平均當種子 */
function atrWilder(bars, n){
  const tr = new Array(bars.length).fill(null);
  for(let i = 1; i < bars.length; i++){
    const h = bars[i].h, l = bars[i].l, pc = bars[i-1].c;
    tr[i] = Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc));
  }
  const out = new Array(bars.length).fill(null);
  if(bars.length <= n) return out;
  let s = 0; for(let i = 1; i <= n; i++) s += tr[i];
  out[n] = s / n;
  for(let i = n + 1; i < bars.length; i++) out[i] = (out[i-1] * (n - 1) + tr[i]) / n;
  return out;
}
/* 滑動極值（不含當根），單調佇列 */
function rollMax(x, n){
  const out = new Array(x.length).fill(null), dq = [];
  for(let i = 0; i < x.length; i++){
    if(i >= n) out[i] = x[dq[0]];
    while(dq.length && x[dq[dq.length-1]] <= x[i]) dq.pop();
    dq.push(i);
    if(dq[0] <= i - n) dq.shift();
  }
  return out;
}
function rollMin(x, n){
  const out = new Array(x.length).fill(null), dq = [];
  for(let i = 0; i < x.length; i++){
    if(i >= n) out[i] = x[dq[0]];
    while(dq.length && x[dq[dq.length-1]] >= x[i]) dq.pop();
    dq.push(i);
    if(dq[0] <= i - n) dq.shift();
  }
  return out;
}

export const freshState = () => ({t: 0, dir: 0, side: 0, avg: 0, blocked: 0});

/**
 * 從 st.t 之後的每一根已收盤 K 往下算。bars 必須全是已收盤、由舊到新。
 * st 為 null 時從頭算（第一次部署，等同網頁在這段資料上的結果）。
 * 回傳 {state, events, last}；events 是這次新發生的進出（進場做多／訊號離開／停損）。
 */
export function step(bars, st){
  const s = st ? {...st} : freshState();
  const H = bars.map(b => b.h), L = bars.map(b => b.l);
  const HH = rollMax(H, LOOK), LL = rollMin(L, LOOK);
  const HE = rollMax(H, EXIT_N), LE = rollMin(L, EXIT_N);
  const A  = atrWilder(bars, ATR_LEN);
  const events = [];

  for(let i = LOOK; i < bars.length; i++){
    const b = bars[i], c = b.c;
    if(b.t <= s.t) continue;

    // dirDonchian（三態）
    if(c > HH[i]) s.dir = 1;
    else if(c < LL[i]) s.dir = -1;
    else if(s.dir === 1 && c < LE[i]) s.dir = 0;
    else if(s.dir === -1 && c > HE[i]) s.dir = 0;
    const d = s.dir, a = A[i];

    // compute()：segs=1、只做多、非反轉
    if(a != null && a > 0){
      if(s.blocked !== 0 && d !== s.blocked) s.blocked = 0;
      if(s.side !== 0 && (s.avg - c) * s.side >= STOP_ATR * a){
        s.blocked = s.side;
        events.push({t: b.t, why: "停損", price: c, avg: s.avg});
        s.side = 0; s.avg = 0;
      }
      if(s.side !== 0 && d !== s.side){
        events.push({t: b.t, why: "訊號離開", price: c, avg: s.avg});
        s.side = 0; s.avg = 0;
      }
      if(s.side === 0 && d > 0 && d !== s.blocked){
        s.side = 1; s.avg = c;
        events.push({t: b.t, why: "進場做多", price: c, avg: c});
      }
    }
    s.t = b.t;
  }
  const n = bars.length - 1;
  const last = n >= LOOK ? {
    t: bars[n].t, c: bars[n].c,
    entryLine: HH[n],
    exitLine: LE[n], atr: A[n],
    stopLine: s.side ? s.avg - STOP_ATR * A[n] : null
  } : null;
  return {state: s, events, last};
}
