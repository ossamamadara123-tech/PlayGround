#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت التحكم بالنظام من تلجرام 🤖 — نسخة التتبع الحي الحقيقي
كل توصية تُجمّد لحظة صدورها (سعر الدخول + الوقت) ثم نراقب السعر الحي:
لا يُعتبر الهدف مضروباً إلا إذا لمسه السعر فعلياً AFTER صدور التوصية.

الأوامر:
  🔍 حلل الآن | 🔥 الصفقات | 🟢 الشراء فقط | 📊 الملخص | 📊 الحالة
  /حلل /صفقات /شراء /ملخص /coin btc /شغل /وقف /الحالة /الفاصل 15 /العدد 7
  /active — الصفقات النشطة المُتتبعة حياً

التشغيل:
  TELEGRAM_TOKEN="..." TELEGRAM_CHAT_ID="..." python3 telegram_bot.py
  تجربة: python3 telegram_bot.py --demo
"""
import json
import math
import os
import sys
import time
import threading
import urllib.request
import urllib.parse

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
ADMIN_ID = os.environ.get("TELEGRAM_ADMIN_ID", "") or CHAT_ID

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "bot_state.json")
SIGNALS_FILE = os.path.join(BASE, "signals_latest.json")
STORE_FILE = os.path.join(BASE, "signal_store.json")  # التوصيات المجمّدة + تتبع حي
MAX_AGE_H = 24  # تنتهي التوصية بعد 24 ساعة وتتولد جديدة

API = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=30&page=1&sparkline=true&price_change_percentage=1h,24h,7d"
BINANCE_TICKER = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_PRICE = "https://api.binance.com/api/v3/ticker/price"
# Symbol mapping: CoinGecko ID -> Binance symbol
SYMBOL_MAP = {
    "bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "tether": "USDTUSDT", "binancecoin": "BNBUSDT",
    "ripple": "XRPUSDT", "solana": "SOLUSDT", "tron": "TRXUSDT", "usd-coin": "USDCUSDT",
    "staked-ether": "STETHUSDT", "dogecoin": "DOGEUSDT", "cardano": "ADAUSDT",
    "avalanche-2": "AVAXUSDT", "shiba-inu": "SHIBUSDT", "polkadot": "DOTUSDT",
    "chainlink": "LINKUSDT", "polygon": "MATICUSDT", "litecoin": "LTCUSDT",
    "bitcoin-cash": "BCHUSDT", "near": "NEARUSDT", "uniswap": "UNIUSDT",
    "internet-computer": "ICPUSDT", "ethereum-classic": "ETCUSDT", "stellar": "XLMUSDT",
    "filecoin": "FILUSDT", "cosmos": "ATOMUSDT", "vechain": "VETUSDT",
    "theta-token": "THETAUSDT", "hedera-hashgraph": "HBARUSDT", "the-graph": "GRTUSDT",
    "aave": "AAVEUSDT"
}


def load_state():
    s = {"auto_enabled": True,
         "interval_min": int(os.environ.get("INTERVAL_MIN", "30")),
         "top_n": int(os.environ.get("TOP_N", "5")),
         "min_score": 0, "last_run": ""}
    try:
        if os.path.exists(STATE_FILE):
            s.update(json.load(open(STATE_FILE, encoding="utf-8")))
    except Exception:
        pass
    return s


def save_state(s):
    try:
        json.dump(s, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception as e:
        print("state save error:", e)


STATE = load_state()


def load_store():
    try:
        if os.path.exists(STORE_FILE):
            return json.load(open(STORE_FILE, encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_store(store):
    try:
        json.dump(store, open(STORE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception as e:
        print("store save error:", e)


def ensure_entry(store, cid, a, live):
    """ضمان أن للتوصية Entry ثابت ولا يتغير ما لم تتغير الإشارة."""
    old = store.get(cid)
    if old and old.get("dir") == dir_class(a["sig"]):
        return old  # الإبقاء على Entry القديم
    # Entry جديد
    entry = live
    atr = a["atr"]
    if a["is_buy"]:
        tp1 = entry * (1 + atr / 100)
        tp2 = entry * (1 + atr * 1.9 / 100)
        sl = entry * (1 - atr * 0.8 / 100)
    else:
        tp1 = entry * (1 - atr * 0.7 / 100)
        tp2 = entry * (1 - atr * 1.4 / 100)
        sl = entry * (1 + atr * 0.8 / 100)
    t = {"dir": dir_class(a["sig"]), "sig": a["sig"], "sig_ar": a["sig_ar"],
         "score": a["score"], "entry": entry, "tp1": tp1, "tp2": tp2, "sl": sl,
         "profit1": abs((tp1 - entry) / entry * 100) if entry else 0,
         "profit2": abs((tp2 - entry) / entry * 100) if entry else 0,
         "loss": abs((sl - entry) / entry * 100) if entry else 0,
         "created_ts": time.time(), "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
         "hit1_at": "", "hit2_at": "", "sl_at": ""}
    store[cid] = t
    return t


def load_store():
    try:
        if os.path.exists(STORE_FILE):
            return json.load(open(STORE_FILE, encoding="utf-8"))
    except Exception:
        pass
    return {}


save_store = staticmethod(save_store)
load_store = staticmethod(load_store)
def fmt_usd(n):
    if n is None:
        return "—"
    try:
        n = float(n)
    except Exception:
        return "—"
    if n < 1:
        return f"${n:,.4f}"
    if n < 100:
        return f"${n:,.2f}"
    return f"${n:,.0f}"


def fmt_big(n):
    if not n:
        return "—"
    n = float(n)
    if n >= 1e12:
        return f"${n/1e12:.2f}T"
    if n >= 1e9:
        return f"${n/1e9:.2f}B"
    if n >= 1e6:
        return f"${n/1e6:.1f}M"
    return f"${n:,.0f}"


def now_ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def ema(arr, p):
    k = 2 / (p + 1)
    e = arr[0]
    for v in arr[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    g = l = 0.0
    for i in range(len(prices) - period, len(prices)):
        d = prices[i] - prices[i - 1]
        if d > 0:
            g += d
        else:
            l -= d
    if l == 0:
        return 100.0
    return 100 - 100 / (1 + g / l)


def stdev(a):
    m = sum(a) / len(a)
    return math.sqrt(sum((v - m) ** 2 for v in a) / len(a))


# ---------- محرك AI ----------
def analyze(c):
    sp = (c.get("sparkline_in_7d") or {}).get("price") or []
    ch1 = c.get("price_change_percentage_1h_in_currency") or 0
    ch24 = c.get("price_change_percentage_24h") or 0
    ch7 = c.get("price_change_percentage_7d_in_currency") or 0
    price = c.get("current_price") or 0
    score = 50.0
    reasons = []
    mom = ch1 * 0.25 + ch24 * 0.55 + ch7 * 0.2
    score += max(-18, min(18, mom * 2.2))
    if ch24 > 3:
        reasons.append(f"زخم صعودي قوي +{ch24:.1f}% خلال 24 ساعة")
    elif ch24 < -3:
        reasons.append(f"ضغط بيعي {ch24:.1f}% خلال 24 ساعة")
    else:
        reasons.append(f"حركة متوازنة {ch24:+.1f}% (24س)")
    if len(sp) > 30:
        e12, e26 = ema(sp[-30:], 12), ema(sp[-30:], 26)
        if e12 > e26 * 1.002:
            score += 9
            reasons.append("السعر فوق المتوسطات — اتجاه صاعد")
        elif e12 < e26 * 0.998:
            score -= 9
            reasons.append("السعر تحت المتوسطات — اتجاه هابط")
        else:
            reasons.append("السعر حول المتوسطات — اتجاه عرضي")
        r = rsi(sp, 14)
        if r < 30:
            score += 10
            reasons.append(f"RSI عند {r:.0f} (تشبع بيعي — ارتداد محتمل)")
        elif r > 70:
            score -= 9
            reasons.append(f"RSI عند {r:.0f} (تشبع شرائي — جني أرباح)")
        elif r >= 50:
            score += 4
            reasons.append(f"RSI عند {r:.0f} (قوة شرائية)")
        else:
            score -= 3
            reasons.append(f"RSI عند {r:.0f} (ضعف نسبي)")
        if stdev(sp[-48:]) / (sp[-1] or 1) > 0.05:
            score -= 4
            reasons.append("تقلب عالي — مخاطرة مرتفعة")
        mn, mx = min(sp[-72:]), max(sp[-72:])
        pos = (price - mn) / ((mx - mn) or 1)
        if pos < 0.2:
            score += 7
            reasons.append("السعر قرب قاع 3 أيام — فرصة دخول")
        elif pos > 0.85:
            score -= 6
            reasons.append("السعر قرب قمة 3 أيام — احذر المطاردة")
    mc = c.get("market_cap") or 0
    vol24 = c.get("total_volume") or 0
    liq = (vol24 / mc) if mc else 0
    if liq > 0.15:
        score += 5
        reasons.append("سيولة متفجرة — اهتمام حيتان")
    elif liq > 0.05:
        score += 2
        reasons.append("سيولة جيدة تدعم الحركة")
    if mc > 2e10:
        score += 3
        reasons.append(f"قيمة سوقية ضخمة ({fmt_big(mc)}) — أمان عالي")
    elif mc and mc < 1e9:
        score -= 3
        reasons.append(f"قيمة سوقية صغيرة ({fmt_big(mc)}) — مخاطرة عالية")
    if c.get("symbol") == "btc":
        score += 2
        reasons.append("البيتكوين يقود السوق")
    score = max(5, min(97, round(score)))
    if score >= 78:
        sig, sig_ar = "buy-strong", "شراء قوي 🔥"
    elif score >= 62:
        sig, sig_ar = "buy", "شراء ✅"
    elif score >= 45:
        sig, sig_ar = "neutral", "محايد ⚖️"
    elif score >= 32:
        sig, sig_ar = "sell", "بيع ⚠️"
    else:
        sig, sig_ar = "sell-strong", "بيع قوي 🔴"
    is_buy = sig not in ("sell", "sell-strong")
    is_sell = sig in ("sell", "sell-strong")
    atr = min(12, max(2, abs(ch24) * 0.9 + 3))
    direction = "sell" if is_sell else "buy"  # المحايد يُتابع كشراء
    return dict(score=score, sig=sig, sig_ar=sig_ar, direction=direction,
                is_buy=is_buy, is_sell=is_sell, atr=atr,
                opp=round(min(96, score + 4) if is_buy else max(4, 100 - score - 8)),
                risk="عالية 🔴" if (mc and mc < 1e9) or abs(ch24) > 10 else ("متوسطة 🟡" if (mc and mc < 1e10) or abs(ch24) > 6 else "منخفضة 🟢"),
                reasons=reasons, ch24=ch24)


def dir_class(sig):
    return "sell" if sig in ("sell", "sell-strong") else "buy"


# ---------- التتبع الحي الحقيقي (مُحسّن) ----------
def track_signals(coins, an, store, live_override=None):
    """يجمّد التوصية لحظة صدورها ويلاحق السعر الحي دون إعادة إنشائها."""
    now = time.time()
    by_id = {c["id"]: c for c in coins}
    # نظّف المنتهية (24 ساعة)
    for cid in list(store.keys()):
        s = store[cid]
        if cid not in by_id or (now - s.get("created_ts", now)) > MAX_AGE_H * 3600:
            del store[cid]
    tracked = {}
    for c in coins:
        cid = c["id"]
        a = an[cid]
        live = float((live_override or {}).get(cid, c.get("current_price") or 0))
        old = store.get(cid)
        # الإبقاء على التوصية القديمة نفسها (لا ن recreate) - التعديل فقط بالسعر الحي
        if old and old.get("dir") == dir_class(a["sig"]):
            t = old  # الإبقاء على نفس Entry + TP/SL
        else:
            # توصية جديدة: تجميد الدخول والأهداف الآن
            entry = live
            atr = a["atr"]
            if a["is_buy"]:
                tp1 = entry * (1 + atr / 100)
                tp2 = entry * (1 + atr * 1.9 / 100)
                sl = entry * (1 - atr * 0.8 / 100)
            else:
                tp1 = entry * (1 - atr * 0.7 / 100)
                tp2 = entry * (1 - atr * 1.4 / 100)
                sl = entry * (1 + atr * 0.8 / 100)
            t = {"dir": dir_class(a["sig"]), "sig": a["sig"], "sig_ar": a["sig_ar"],
                 "score": a["score"], "entry": entry, "tp1": tp1, "tp2": tp2, "sl": sl,
                 "profit1": abs((tp1 - entry) / entry * 100) if entry else 0,
                 "profit2": abs((tp2 - entry) / entry * 100) if entry else 0,
                 "loss": abs((sl - entry) / entry * 100) if entry else 0,
                 "created_ts": now, "created_at": now_ts(),
                 "hit1_at": "", "hit2_at": "", "sl_at": ""}
            store[cid] = t
        t = store[cid]  # reference
        # تحديث البيانات الحالية + فحص حي (دون تغيير entry)
        t["sig"], t["sig_ar"], t["score"] = a["sig"], a["sig_ar"], a["score"]
        t["live"] = live
        if t["entry"] and live > 0:
            raw = (live - t["entry"]) / t["entry"] * 100
            t["live_pnl"] = -raw if t["dir"] == "sell" else raw
            if t["dir"] == "buy":
                if not t["hit1_at"] and live >= t["tp1"]:
                    t["hit1_at"] = now_ts()
                if not t["hit2_at"] and live >= t["tp2"]:
                    t["hit2_at"] = now_ts()
                if not t["hit1_at"] and not t["hit2_at"] and not t["sl_at"] and live <= t["sl"]:
                    t["sl_at"] = now_ts()
            else:
                if not t["hit1_at"] and live <= t["tp1"]:
                    t["hit1_at"] = now_ts()
                if not t["hit2_at"] and live <= t["tp2"]:
                    t["hit2_at"] = now_ts()
                if not t["hit1_at"] and not t["hit2_at"] and not t["sl_at"] and live >= t["sl"]:
                    t["sl_at"] = now_ts()
        else:
            t["live_pnl"] = 0.0
        if t["hit2_at"]:
            t["status"] = f"تم ضرب الهدفين ✅✅ — {t['hit2_at']}"
        elif t["hit1_at"]:
            t["status"] = f"تم ضرب الهدف الأول ✅ ({t['hit1_at']}) — بانتظار الثاني"
        elif t["sl_at"]:
            t["status"] = f"ضرب وقف الخسارة 🛑 ({t['sl_at']})"
        else:
            age_m = int((now - t["created_ts"]) / 60)
            t["status"] = f"⏳ تتبع حي منذ {age_m} د — لم يُلمس هدف بعد"
        t["age_min"] = int((now - t["created_ts"]) / 60)
        tracked[cid] = t
    save_store(store)
    return tracked


def fetch_coingecko():
    """جلب بيانات السوق من CoinGecko (مصدر أساسي: قيمة سوقية، حجم، شرارات)."""
    req = urllib.request.Request(API, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def fetch_binance_24hr():
    """جلب بيانات 24h من Binance (مصدر ثانوي: سعر، حجم، تغيير، عالي/منخفض)."""
    try:
        req = urllib.request.Request(BINANCE_TICKER, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        # تحويل إلى dict بالرمز
        return {d["symbol"].replace("USDT", "").lower(): {
            "price": float(d["lastPrice"]),
            "high_24h": float(d["highPrice"]),
            "low_24h": float(d["lowPrice"]),
            "volume": float(d["volume"]),
            "price_change_pct": float(d["priceChangePercent"]),
            "count": int(d["count"])
        } for d in data if d["symbol"].endswith("USDT")}
    except Exception as e:
        print("[binance 24hr] error:", e)
        return {}


def merge_market_data(cg_coins, binance_24hr):
    """دمج بيانات CoinGecko + Binance: نأخذ الأفضل من كل مصدر."""
    merged = []
    for c in cg_coins:
        sym = c.get("symbol", "").lower()
        cid = c.get("id", "")
        # بيانات Binance للرمز
        b = binance_24hr.get(sym) or binance_24hr.get(SYMBOL_MAP.get(cid, "").replace("USDT", "").lower())
        merged.append({
            "id": cid,
            "symbol": sym,
            "name": c.get("name"),
            "image": c.get("image"),
            "current_price": b["price"] if b else (c.get("current_price") or 0),
            "market_cap": c.get("market_cap"),
            "total_volume": b["volume"] * (b["price"] if b else 0) if b else c.get("total_volume"),
            "market_cap_rank": c.get("market_cap_rank"),
            "price_change_percentage_24h": b["price_change_pct"] if b else c.get("price_change_percentage_24h"),
            "price_change_percentage_1h_in_currency": c.get("price_change_percentage_1h_in_currency"),
            "price_change_percentage_7d_in_currency": c.get("price_change_percentage_7d_in_currency"),
            "high_24h": b["high_24h"] if b else None,
            "low_24h": b["low_24h"] if b else None,
            "sparkline_in_7d": c.get("sparkline_in_7d"),
            "source": "coingecko+binance" if b else "coingecko"
        })
    return merged


def fetch_markets():
    """جلب السوق من مصادرتين مع دمج ذكي."""
    cg = fetch_coingecko()
    bn = fetch_binance_24hr()
    if bn:
        print(f"[data] دمج CoinGecko ({len(cg)}) + Binance ({len(bn)} رموز)")
    else:
        print(f"[data] CoinGecko فقط ({len(cg)} عملة) - Binance غير متاح")
    return merge_market_data(cg, bn)


def fetch_binance_lives(symbols):
    """أسعار لحظية من Binance - أسرع للتتبع الحي."""
    try:
        # تحويل الرموز لرموز Binance
        binance_syms = []
        for s in symbols:
            if not s:
                continue
            mapped = SYMBOL_MAP.get(s.lower(), s.upper() + "USDT")
            if mapped not in binance_syms:
                binance_syms.append(mapped)
        if not binance_syms:
            return {}
        url = BINANCE_PRICE + "?symbols=" + urllib.parse.quote(json.dumps(binance_syms))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        out = {}
        for d in data:
            sym = d.get("symbol", "")
            if sym.endswith("USDT"):
                # عكس الـ mapping
                base = sym[:-4].lower()
                out[base] = float(d["price"])
        return out
    except Exception as e:
        print("[binance live] error:", e)
        return {}


def scan(track=True):
    coins = fetch_markets()
    an = {c["id"]: analyze(c) for c in coins}
    tracked = None
    if track:
        try:
            lives = fetch_binance_lives([c["symbol"] for c in coins])
            by_sym = {c["symbol"].lower(): c["id"] for c in coins}
            override = {by_sym[s]: p for s, p in lives.items() if s in by_sym}
        except Exception:
            override = {}
        tracked = track_signals(coins, an, load_store(), override)
    # Ensure all coins have entries in store
    store = load_store()
    for c in coins:
        cid = c["id"]
        if cid not in store:
            a = an[cid]
            live = c.get("current_price") or 0
            ensure_entry(store, cid, a, live)
        if cid not in tracked and cid in store:
            tracked[cid] = store[cid]
    save_store(store)
    return coins, an, tracked


def save_signals_file(coins, an, tracked):
    try:
        data = {"updated_at": now_ts(), "source": "telegram-live-tracking", "live": True,
                "signals": [
                    {"id": c["id"], "name": c["name"], "symbol": c["symbol"],
                     "image": c.get("image"), "price": c.get("current_price"),
                     "mcap": c.get("market_cap"), "volume": c.get("total_volume"),
                     "rank": c.get("market_cap_rank"), "chg24": c.get("price_change_percentage_24h"),
                     "a": an[c["id"]], "t": (tracked or {}).get(c["id"], {})} for c in coins]}
        json.dump(data, open(SIGNALS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"[control] حُفظت {len(coins)} إشارة حية في {SIGNALS_FILE}")
    except Exception as e:
        print("save signals error:", e)


# ---------- رسائل ----------
def format_signal(c, a, t):
    t = t or {}
    entry = t.get("entry", c.get("current_price"))
    live = t.get("live", c.get("current_price"))
    pnl = t.get("live_pnl", 0)
    h1 = f"✅ ضُرب {t['hit1_at']}" if t.get("hit1_at") else "⏳ لم يُلمس بعد"
    h2 = f"✅ ضُرب {t['hit2_at']}" if t.get("hit2_at") else "⏳ لم يُلمس بعد"
    pnl_s = f"{pnl:+.2f}%"
    return "\n".join([
        f"📊 <b>{c['name']} ({c['symbol'].upper()})</b> — {a['sig_ar']}",
        f"🕐 صدرت: {t.get('created_at', 'الآن')} | الثقة {a['score']}% | فرصة الصعود {a['opp']}%",
        f"💵 الدخول (مجمّد): <b>{fmt_usd(entry)}</b>",
        f"📍 السعر الحي الآن: <b>{fmt_usd(live)}</b> ({pnl_s} {'🟢' if pnl >= 0 else '🔴'})",
        f"🎯 الهدف 1: <b>{fmt_usd(t.get('tp1', a.get('tp1')))}</b> (+{t.get('profit1', 0):.2f}%) — {h1}",
        f"🎯 الهدف 2: <b>{fmt_usd(t.get('tp2', a.get('tp2')))}</b> (+{t.get('profit2', 0):.2f}%) — {h2}",
        f"🛑 الوقف: <b>{fmt_usd(t.get('sl', a.get('sl')))}</b> (-{t.get('loss', 0):.2f}%)",
        f"📌 {t.get('status', '')}",
        f"💰 القيمة السوقية: {fmt_big(c.get('market_cap'))}"])


def format_summary(coins, an, tracked):
    s = sorted(coins, key=lambda c: an[c["id"]]["score"], reverse=True)
    best, worst = s[0], s[-1]
    ab = an[best["id"]]
    avg = sum((c.get("price_change_percentage_24h") or 0) for c in coins) / len(coins)
    mood = "صاعد 🚀" if avg > 2 else ("هابط 🩸" if avg < -2 else "عرضي ⚖️")
    buys = sum(1 for c in coins if an[c["id"]]["sig"] in ("buy", "buy-strong"))
    real_hits = sum(1 for c in coins if (tracked or {}).get(c["id"], {}).get("hit1_at"))
    return (f"🤖 <b>ملخص المحلل الذكي — تتبع حي 📡</b>\n"
            f"الحالة: {mood} (متوسط {avg:+.1f}%)\n"
            f"🔥 فرص شراء: {buys} | العملات: {len(coins)}\n"
            f"✅ أهداف ضُربت فعلياً: {real_hits}\n"
            f"🏆 الأقوى: {best['name']} — {ab['sig_ar']} (ثقة {ab['score']}%)\n"
            f"🕐 آخر تشغيل: {STATE.get('last_run', '—')}")


HELP = ("🎛 <b>لوحة تحكم النظام من تلجرام — تتبع حي 📡</b>\n"
        "———————\n"
        "🔍 /حلل — تشغيل التحليل الآن (يحدّث الموقع)\n"
        "🔥 /صفقات — أقوى الصفقات الحية\n"
        "🟢 /شراء — فرص الشراء فقط\n"
        "📡 /active — الصفقات النشطة المُتتبعة\n"
        "📊 /ملخص — ملخص السوق\n"
        "🪙 /coin btc — تحليل عملة\n"
        "⏯ /شغل و /وقف — البث التلقائي\n"
        "📊 /الحالة — حالة النظام\n"
        "⚙️ /الفاصل 15 — الفاصل (دقائق)\n"
        "⚙️ /العدد 7 — عدد الصفقات\n"
        "———————\n"
        "✅ الضرب حقيقي 100%: الهدف لا يُحتسب إلا إذا لمسه السعر الحي بعد صدور التوصية.")


def main_menu():
    auto = "⏸ إيقاف البث" if STATE["auto_enabled"] else "▶️ تشغيل البث"
    return {"keyboard": [
        [{"text": "🔍 حلل الآن"}, {"text": "🔥 الصفقات"}],
        [{"text": "🟢 الشراء فقط"}, {"text": "📡 النشطة"}],
        [{"text": auto}, {"text": "📊 الحالة"}],
        [{"text": "❓ المساعدة"}]], "resize_keyboard": True}


def tg_call(method, params):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    if "reply_markup" in params and isinstance(params["reply_markup"], dict):
        params = dict(params)
        params["reply_markup"] = json.dumps(params["reply_markup"], ensure_ascii=False)
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=25) as r:
        return json.loads(r.read().decode())


def send(chat, text, menu=True):
    try:
        p = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
        if menu:
            p["reply_markup"] = main_menu()
        tg_call("sendMessage", p)
        return True
    except Exception as e:
        print("send error:", e)
        return False


def is_admin(chat):
    return (not ADMIN_ID) or (str(chat) == str(ADMIN_ID))


def do_scan(chat, announce=True):
    if announce:
        send(chat, "🔍 <b>جاري تشغيل النظام... أحلل السوق حياً الآن</b>", menu=False)
    try:
        coins, an, tracked = scan()
        STATE["last_run"] = now_ts()
        save_state(STATE)
        save_signals_file(coins, an, tracked)
        send(chat, format_summary(coins, an, tracked))
        top = sorted(coins, key=lambda c: an[c["id"]]["score"], reverse=True)[:STATE["top_n"]]
        for c in top:
            if an[c["id"]]["score"] >= STATE["min_score"]:
                send(chat, format_signal(c, an[c["id"]], (tracked or {}).get(c["id"])), menu=False)
                time.sleep(0.3)
        send(chat, f"✅ <b>اكتمل التشغيل الحي</b> — {len(coins)} عملة 🕐 {STATE['last_run']}")
        return coins, an, tracked
    except Exception as e:
        send(chat, f"⚠️ تعذر التشغيل: {e}")
        return None, None, None


def send_active(chat):
    store = load_store()
    if not store:
        send(chat, "لا توجد توصيات نشطة بعد — نفّذ 🔍 حلل الآن أولاً")
        return
    try:
        coins, an, tracked = scan()
        save_signals_file(coins, an, tracked)
        act = [(c, an[c["id"]], tracked[c["id"]]) for c in coins if c["id"] in tracked]
        act.sort(key=lambda x: x[2].get("live_pnl", 0), reverse=True)
        send(chat, f"📡 <b>الصفقات النشطة المُتتبعة حياً ({len(act)})</b>")
        for c, a, t in act[:10]:
            send(chat, format_signal(c, a, t), menu=False)
            time.sleep(0.3)
    except Exception as e:
        send(chat, f"⚠️ خطأ: {e}")


def status_text():
    store = load_store()
    hits = sum(1 for v in store.values() if v.get("hit1_at"))
    return ("📡 <b>حالة النظام الحي</b>\n"
            f"⏱ البث التلقائي: {'يعمل ✅' if STATE['auto_enabled'] else 'متوقف ⏸'}\n"
            f"⏳ الفاصل: كل {STATE['interval_min']} دقيقة\n"
            f"🔢 عدد الصفقات: {STATE['top_n']}\n"
            f"📡 توصيات مُتتبعة: {len(store)} | أهداف ضُربت فعلياً: {hits}\n"
            f"🕐 آخر تشغيل: {STATE.get('last_run') or 'لم يعمل بعد'}")


def handle_text(chat, text):
    t = text.strip()
    low = t.lower()
    if t in ("🔍 حلل الآن", "/حلل", "/run", "/start", "/help", "❓ المساعدة", "/مساعدة"):
        if t in ("/start", "❓ المساعدة", "/help", "/مساعدة"):
            send(chat, HELP)
        else:
            do_scan(chat)
        return
    if t in ("🔥 الصفقات", "/صفقات", "/signals"):
        try:
            coins, an, tracked = scan()
            save_signals_file(coins, an, tracked)
            for c in sorted(coins, key=lambda c: an[c["id"]]["score"], reverse=True)[:STATE["top_n"]]:
                send(chat, format_signal(c, an[c["id"]], (tracked or {}).get(c["id"])), menu=False)
                time.sleep(0.3)
        except Exception as e:
            send(chat, f"⚠️ خطأ: {e}")
        return
    if t in ("🟢 الشراء فقط", "/شراء", "/buys", "/buy"):
        try:
            coins, an, tracked = scan()
            s = [c for c in sorted(coins, key=lambda c: an[c["id"]]["score"], reverse=True)
                 if an[c["id"]]["sig"] in ("buy", "buy-strong")]
            for c in (s or sorted(coins, key=lambda c: an[c["id"]]["score"], reverse=True))[:STATE["top_n"]]:
                send(chat, format_signal(c, an[c["id"]], (tracked or {}).get(c["id"])), menu=False)
                time.sleep(0.3)
        except Exception as e:
            send(chat, f"⚠️ خطأ: {e}")
        return
    if t in ("📡 النشطة", "/active", "/النشطة"):
        send_active(chat)
        return
    if t in ("📊 الملخص", "/ملخص", "/top", "/summary"):
        try:
            coins, an, tracked = scan()
            send(chat, format_summary(coins, an, tracked))
        except Exception as e:
            send(chat, f"⚠️ خطأ: {e}")
        return
    if t in ("📊 الحالة", "/الحالة", "/status"):
        send(chat, status_text())
        return
    if t in ("▶️ تشغيل البث", "/شغل", "/auto_on"):
        if not is_admin(chat):
            send(chat, "⛔ هذا الزر للمشغّل فقط")
            return
        STATE["auto_enabled"] = True
        save_state(STATE)
        send(chat, "▶️ <b>تم تشغيل البث التلقائي</b>")
        return
    if t in ("⏸ إيقاف البث", "/وقف", "/auto_off"):
        if not is_admin(chat):
            send(chat, "⛔ هذا الزر للمشغّل فقط")
            return
        STATE["auto_enabled"] = False
        save_state(STATE)
        send(chat, "⏸ <b>تم إيقاف البث التلقائي</b>")
        return
    if low.startswith("/الفاصل") or low.startswith("/interval"):
        if not is_admin(chat):
            send(chat, "⛔ للمشغّل فقط")
            return
        try:
            v = int(t.split()[1])
            STATE["interval_min"] = max(5, min(180, v))
            save_state(STATE)
            send(chat, f"⏳ الفاصل: كل {STATE['interval_min']} دقيقة")
        except Exception:
            send(chat, "مثال: /الفاصل 15")
        return
    if low.startswith("/العدد") or low.startswith("/topn"):
        try:
            v = int(t.split()[1])
            STATE["top_n"] = max(1, min(15, v))
            save_state(STATE)
            send(chat, f"🔢 عدد الصفقات: {STATE['top_n']}")
        except Exception:
            send(chat, "مثال: /العدد 7")
        return
    if low.startswith("/coin"):
        parts = t.split()
        sym = parts[1].lower() if len(parts) > 1 else ""
        try:
            coins, an, tracked = scan()
            hit = next((c for c in coins if c["symbol"].lower() == sym), None)
            send(chat, format_signal(hit, an[hit["id"]], (tracked or {}).get(hit["id"])) if hit else "لم أجد العملة. مثال: /coin btc")
        except Exception as e:
            send(chat, f"⚠️ خطأ: {e}")
        return
    send(chat, HELP)


def auto_loop():
    while True:
        try:
            if STATE["auto_enabled"] and CHAT_ID:
                try:
                    coins, an, tracked = scan()
                    STATE["last_run"] = now_ts()
                    save_state(STATE)
                    save_signals_file(coins, an, tracked)
                    tg_call("sendMessage", {"chat_id": CHAT_ID, "text": format_summary(coins, an, tracked), "parse_mode": "HTML"})
                    top = [c for c in sorted(coins, key=lambda c: an[c["id"]]["score"], reverse=True)
                           if an[c["id"]]["sig"] in ("buy", "buy-strong")][:STATE["top_n"]]
                    for c in top:
                        tg_call("sendMessage", {"chat_id": CHAT_ID, "text": format_signal(c, an[c["id"]], (tracked or {}).get(c["id"])), "parse_mode": "HTML"})
                        time.sleep(0.4)
                    print(f"[auto] بُثّ {len(top)} صفقة حية 🕐 {STATE['last_run']}")
                except Exception as e:
                    print("[auto] scan error:", e)
        except Exception:
            pass
        for _ in range(max(1, STATE["interval_min"] * 60 // 5)):
            time.sleep(5)


def mode_run():
    if not TOKEN:
        print("خطأ: ضع TELEGRAM_TOKEN أولاً")
        return
    print("البوت يعمل: " + tg_call("getMe", {}).get("result", {}).get("username", "?"))
    print(f"البث: {'مفعّل' if STATE['auto_enabled'] else 'متوقف'} كل {STATE['interval_min']} دقيقة — تتبع حي 📡")
    threading.Thread(target=auto_loop, daemon=True).start()
    offset = 0
    while True:
        try:
            res = tg_call("getUpdates", {"offset": offset, "timeout": 25})
            for u in res.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                chat = str((msg.get("chat") or {}).get("id", ""))
                if msg.get("text") and chat:
                    handle_text(chat, msg["text"])
        except KeyboardInterrupt:
            print("\nإيقاف")
            break
        except Exception as e:
            print("polling retry:", e)
            time.sleep(3)


def mode_demo():
    print("— تجربة التتبع الحي (بدون تلجرام) —")
    coins, an, tracked = scan()
    save_signals_file(coins, an, tracked)
    print(format_summary(coins, an, tracked).replace("<b>", "").replace("</b>", ""))
    print("-" * 60)
    for c in sorted(coins, key=lambda c: an[c["id"]]["score"], reverse=True)[:STATE["top_n"]]:
        a = an[c["id"]]
        t = (tracked or {}).get(c["id"], {})
        print(f"{c['name']}: {a['sig_ar']} | دخول {fmt_usd(t.get('entry'))} ({t.get('created_at')}) | حي {fmt_usd(t.get('live'))} ({t.get('live_pnl',0):+.2f}%) | TP1 {'✅ '+t['hit1_at'] if t.get('hit1_at') else '⏳ حي'} | TP2 {'✅ '+t['hit2_at'] if t.get('hit2_at') else '⏳ حي'}")


def mode_getid():
    if not TOKEN:
        print("ضع التوكن: TELEGRAM_TOKEN='...' python3 telegram_bot.py --getid")
        return
    print("أرسل أي رسالة للبوت... (Ctrl+C للإيقاف)")
    seen, offset = set(), 0
    while True:
        try:
            res = tg_call("getUpdates", {"offset": offset, "timeout": 25})
            for u in res.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                cid = (msg.get("chat") or {}).get("id")
                if cid and cid not in seen:
                    seen.add(cid)
                    print(f"📩 chat_id = {cid} | رسالة: {msg.get('text', '')}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print("retry...", e)
            time.sleep(3)


if __name__ == "__main__":
    if "--demo" in sys.argv:
        mode_demo()
    elif "--getid" in sys.argv:
        mode_getid()
    else:
        mode_run()
