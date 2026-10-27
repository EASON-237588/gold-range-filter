/**
 * 那斯達克短趨勢・B2：Gate QQQ_USDT 合約逐筆成交合成 37 秒 K，Range Filter 450/23，多空反轉。
 * 以下函式逐行照搬 指數趨勢儀表板 index.html（cmeOpen、pineMA、calcRF），兩邊算出來的方向才會一樣。
 * 2026-10-18 由 B（30 秒 200/23）改成 B2（37 秒 450/23）。
 * 2026-10-27 上午使用者指定「乙取代 B2」：改成乙（45 秒 576/27）。
 * 2026-10-27 傍晚使用者說「改」：退回 B2（37 秒 450/23）。乙的參數：576／27／45 秒。
 * 37 秒不是 Gate 的原生間隔（只有 1／10／30 秒與 1 分），一律用逐筆成交合成，切法見 worker.js。
 * 2026-10-27 晚（HP）使用者指定「平衡板取代 B2」：甲 30 秒 555/31.9 與乙 45 秒 576/27 同向才持有，
 * 兩組都用下面的 calcRF，取樣與倍數改成參數傳入（不傳時照舊用 B2 的 450/23）。
 */
export const PER = 450, MULT = 23, ATR_LEN = 12, ATR_MULT = 1.5, VOL_LEN = 20;
export const TF_SEC = 37, TF_MS = TF_SEC * 1000;
export const NAME = "B2";
// 平衡板的兩組（同期貨趨勢 j30、y45 兩格）
export const J30 = {name: "甲", per: 555, mult: 31.9, tf: 30};
export const Y45 = {name: "乙", per: 576, mult: 27,   tf: 45};

/* 美國期貨交易時段：美東週日 18:00 開盤、週五 17:00 收盤，每天 17:00～18:00 休息 */
const ETF = new Intl.DateTimeFormat("en-US", {timeZone:"America/New_York", weekday:"short", hour:"2-digit", hourCycle:"h23"});
const ETC = new Map();
function et(t){
  const key = Math.floor(t/3600000);
  let v = ETC.get(key);
  if(!v){
    const ps = ETF.formatToParts(new Date(key*3600000));
    v = {wd: ps.find(x => x.type === "weekday").value, h: +ps.find(x => x.type === "hour").value % 24};
    ETC.set(key, v);
  }
  return v;
}
export function cmeOpen(t){
  const {wd, h} = et(t);
  if(wd === "Sat") return false;
  if(wd === "Sun") return h >= 18;
  if(wd === "Fri") return h < 17;
  return h !== 17;
}

function pineMA(src, len, alpha){
  const out = new Array(src.length).fill(null);
  let prev = null, sum = 0, cnt = 0;
  for(let i = 0; i < src.length; i++){
    const v = src[i];
    if(v == null){ out[i] = prev; continue; }
    if(prev === null){
      sum += v; cnt++;
      if(cnt === len){ prev = sum/len; out[i] = prev; }
    }else{
      prev = alpha*v + (1-alpha)*prev;
      out[i] = prev;
    }
  }
  return out;
}
const pineEma = (s, n) => pineMA(s, n, 2/(n+1));
const pineRma = (s, n) => pineMA(s, n, 1/n);
function pineSma(src, len){
  const out = new Array(src.length).fill(null); let s = 0;
  for(let i = 0; i < src.length; i++){
    s += src[i];
    if(i >= len) s -= src[i-len];
    if(i >= len-1) out[i] = s/len;
  }
  return out;
}
function trueRange(B){
  return B.map((b, i) => i === 0 ? b.h - b.l
    : Math.max(b.h - b.l, Math.abs(b.h - B[i-1].c), Math.abs(b.l - B[i-1].c)));
}

/* 回傳每根的部位（1 多／-1 空／0 尚未有訊號） */
export function calcRF(B, per = PER, mult = MULT){
  const n = B.length;
  const src = B.map(b => (b.h + b.l) / 2);
  const diff = src.map((v, i) => i === 0 ? null : Math.abs(v - src[i-1]));
  const avrng = pineEma(diff, per);
  const smrng = pineEma(avrng, per*2 - 1).map(v => v == null ? null : v * mult);
  const filt = new Array(n).fill(null);
  let prev = null;
  for(let i = 0; i < n; i++){
    const x = src[i], r = smrng[i];
    if(r == null){ prev = null; continue; }
    const pv = prev == null ? 0 : prev;
    filt[i] = prev = x > pv ? (x - r < pv ? pv : x - r) : (x + r > pv ? pv : x + r);
  }
  const atr = pineRma(trueRange(B), ATR_LEN);
  const volMa = pineSma(B.map(b => b.v || 0), VOL_LEN);
  const pos = new Array(n).fill(0);
  let up = 0, dn = 0, ci = null, cur = 0;
  for(let i = 0; i < n; i++){
    const f = filt[i], pf = i ? filt[i-1] : null;
    if(f != null && pf != null){
      up = f > pf ? up + 1 : f < pf ? 0 : up;
      dn = f < pf ? dn + 1 : f > pf ? 0 : dn;
    }
    const s = src[i], ps = i ? src[i-1] : null, moved = ps != null && s !== ps;
    const longCond  = f != null && s > f && moved && up > 0;
    const shortCond = f != null && s < f && moved && dn > 0;
    const c = B[i].c, a = atr[i];
    const longF  = a != null && c > c - a * ATR_MULT;
    const shortF = a != null && c < c + a * ATR_MULT;
    const volOK  = volMa[i] != null && (B[i].v || 0) > volMa[i] * 0.8;
    const longSig = longCond && longF && volOK, shortSig = shortCond && shortF && volOK;
    const pci = ci;
    ci = longSig ? 1 : shortSig ? -1 : pci;
    if(longSig && pci === -1) cur = 1;
    else if(shortSig && pci === 1) cur = -1;
    pos[i] = cur;
  }
  return {pos, warm: 6 * per};
}
