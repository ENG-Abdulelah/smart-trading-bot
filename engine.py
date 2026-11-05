#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Engine module — all runtime state, business logic, background threads, and DB helpers.
"""

import os
import json
import time
import random
import sqlite3
import threading
import traceback
import copy
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor
from collections import deque

from config import (
    DB_PATH, UA, HTTP_TIMEOUT,
    SYMBOLS, TRADEABLE_SYMBOLS, PRICE_BOUNDS, TRADE_MODES,
    ICT_STRATEGIES, STRATEGY_AR,
    ANTI_USD_SYMBOLS, PRO_USD_SYMBOLS,
    NEWS_BLACKOUT_BEFORE_MIN, NEWS_BLACKOUT_AFTER_MIN,
    CB_STATE_SEED, COT_STATE_SEED,
    CALENDAR_SEED, EVENT_TIME_MAP,
    BIAS_GUARDRAIL_THRESHOLD,
    STRATEGY_LESSONS, MODE_LESSONS,
    now_iso,
)

# ---- Ensure DB directory exists ----
_db_dir = os.path.dirname(DB_PATH)
if _db_dir:
    try:
        os.makedirs(_db_dir, exist_ok=True)
    except Exception as exc:
        print(f"[startup] could not create DB dir {_db_dir}: {exc}", flush=True)

# ---- Mutable runtime state ----
DB_LOCK = threading.RLock()
PRICE_LOCK = threading.RLock()
MACRO_LOCK = threading.RLock()
COT_LOCK = threading.RLock()
CB_LOCK = threading.RLock()
CAL_LOCK = threading.RLock()
AP_LOCK = threading.RLock()
SHUTDOWN = threading.Event()

PRICE_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="price")
LAST_FETCH = {}

AUTOPILOT_LOG = deque(maxlen=50)
_last_autopilot_trade_at = None
_last_autopilot_scan_at = None
_last_autopilot_status = "idle"

PRICES = {}
for _sym, _cfg in SYMBOLS.items():
    PRICES[_sym] = {
        "price": _cfg["base"], "prev_price": _cfg["base"],
        "open": _cfg["base"], "high": _cfg["base"], "low": _cfg["base"],
        "prev_close": _cfg["base"], "history": [_cfg["base"]] * 60,
        "last_update": now_iso(),
        "source": "init", "stale": True,
    }

MACRO = {
    "vix": 16.40, "us10y": 4.355, "regime": "Neutral",
    "safe_haven": "Gold / USD", "geo_risk": 35.0,
    "geo_risk_label": "Elevated",
    "updated_at": now_iso(), "last_ok": None,
}

CB_STATE = copy.deepcopy(CB_STATE_SEED)
COT_STATE = copy.deepcopy(COT_STATE_SEED)


def ap_log(msg: str) -> None:
    with AP_LOCK:
        AUTOPILOT_LOG.appendleft({"time": now_iso(), "msg": msg})
    print(f"[autopilot] {msg}", flush=True)


# ---- Time / session helpers ----
def active_session() -> str:
    h = datetime.now(timezone.utc).hour
    if 22 <= h or h < 1: return "Sydney"
    if 1 <= h < 7:       return "Tokyo"
    if 7 <= h < 12:      return "London"
    if 12 <= h < 16:     return "London / NY Overlap"
    if 16 <= h < 21:     return "New York"
    return "After Hours"


def is_kill_zone() -> bool:
    h = datetime.now(timezone.utc).hour
    return (7 <= h < 10) or (12 <= h < 15)


def is_silver_bullet() -> bool:
    h = datetime.now(timezone.utc).hour
    return h in (7, 14, 18)


def classify_regime(vix: float) -> str:
    if vix >= 35: return "Crisis"
    if vix >= 25: return "Risk-Off"
    if vix <= 14: return "Risk-On"
    if vix <= 18: return "Neutral-Constructive"
    return "Neutral"


def classify_safe_haven(regime: str) -> str:
    return {
        "Crisis": "USD / JPY / Gold", "Risk-Off": "USD / Gold",
        "Risk-On": "Equities / AUD", "Neutral-Constructive": "Gold",
        "Neutral": "Gold / USD",
    }.get(regime, "Gold / USD")


def geo_risk_label(v: float) -> str:
    if v >= 75: return "Extreme"
    if v >= 55: return "High"
    if v >= 35: return "Elevated"
    if v >= 20: return "Moderate"
    return "Low"


def get_next_sunday_2200(now: datetime) -> datetime:
    days_to_sunday = (6 - now.weekday()) % 7
    if days_to_sunday == 0:
        if now.hour < 22:
            days_to_sunday = 0
        else:
            days_to_sunday = 7
    target = now + timedelta(days=days_to_sunday)
    return target.replace(hour=22, minute=0, second=0, microsecond=0)


# ---- Calendar / news / market status ----
def build_calendar():
    now = datetime.now(timezone.utc)
    out = []
    for item in CALENDAR_SEED:
        h, m = EVENT_TIME_MAP.get(item["event_en"], (12, 0))
        try:
            candidate = datetime(now.year, item["month"], item["day"], h, m, 0, tzinfo=timezone.utc)
        except ValueError:
            continue
        if candidate < now - timedelta(days=1):
            try:
                candidate = datetime(now.year + 1, item["month"], item["day"], h, m, 0, tzinfo=timezone.utc)
            except ValueError:
                continue
        out.append({
            "event_en": item["event_en"], "event_ar": item["event_ar"],
            "currency": item["currency"], "impact": item["impact"],
            "forecast": item["forecast"], "previous": item["previous"],
            "when": candidate.isoformat(),
            "when_str": candidate.strftime("%Y-%m-%d %H:%M UTC"),
            "in_days": (candidate - now).days,
        })
    out.sort(key=lambda e: e["when"])
    return out[:14]


def get_news_blackout() -> dict:
    now = datetime.now(timezone.utc)
    try:
        events = build_calendar()
    except Exception:
        return {"active": False}
    for e in events:
        if e.get("impact") != "HIGH":
            continue
        try:
            when = datetime.fromisoformat(e["when"])
        except (ValueError, TypeError, KeyError):
            continue
        blackout_start = when - timedelta(minutes=NEWS_BLACKOUT_BEFORE_MIN)
        blackout_end = when + timedelta(minutes=NEWS_BLACKOUT_AFTER_MIN)
        if blackout_start <= now <= blackout_end:
            return {
                "active": True,
                "event_en": e.get("event_en", ""),
                "event_ar": e.get("event_ar", ""),
                "currency": e.get("currency", ""),
                "impact": e.get("impact", "HIGH"),
                "when": e.get("when"),
                "blackout_start": blackout_start.isoformat(),
                "blackout_end": blackout_end.isoformat(),
                "resume_in_sec": max(0, int((blackout_end - now).total_seconds())),
            }
    return {"active": False}


def compute_market_status() -> dict:
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    hour = now.hour

    is_closed = False
    is_daily_break = False
    reason = None
    next_open = None

    if weekday == 5:
        is_closed = True
        reason = "weekend"
        next_open = get_next_sunday_2200(now)
    elif weekday == 6:
        if hour < 22:
            is_closed = True
            reason = "weekend"
            next_open = get_next_sunday_2200(now)
    elif weekday == 4 and hour >= 21:
        is_closed = True
        reason = "weekend"
        next_open = get_next_sunday_2200(now)

    if not is_closed and weekday < 4 and hour == 21:
        is_daily_break = True
        next_open = now.replace(hour=22, minute=0, second=0, microsecond=0)

    news = get_news_blackout()

    if news["active"] and not is_closed and not is_daily_break:
        try:
            next_open = datetime.fromisoformat(news["blackout_end"])
        except (ValueError, KeyError):
            pass

    countdown_sec = 0
    if next_open:
        countdown_sec = max(0, int((next_open - now).total_seconds()))

    if is_closed:
        liq_level = "closed"; liq_session = "Off-Session"
    elif is_daily_break:
        liq_level = "weak"; liq_session = "Daily Break"
    elif 7 <= hour < 12:
        liq_level = "high"; liq_session = "London"
    elif 12 <= hour < 16:
        liq_level = "high"; liq_session = "London-NY Overlap"
    elif 16 <= hour < 20:
        liq_level = "moderate"; liq_session = "New York"
    elif 1 <= hour < 7:
        liq_level = "moderate"; liq_session = "Tokyo"
    elif 22 <= hour or hour < 1:
        liq_level = "moderate"; liq_session = "Sydney"
    elif 20 <= hour < 21:
        liq_level = "weak"; liq_session = "NY Close"
    else:
        liq_level = "moderate"; liq_session = "Off-Hours"

    allow_trades = liq_level in ("high", "moderate")
    allow_autopilot = liq_level == "high"

    if news["active"]:
        allow_trades = False
        allow_autopilot = False

    return {
        "is_open": (not is_closed) and (not is_daily_break) and (not news["active"]),
        "is_closed": is_closed,
        "is_daily_break": is_daily_break,
        "news_blackout": news,
        "reason": reason,
        "next_open": next_open.isoformat() if next_open else None,
        "countdown_sec": countdown_sec,
        "server_time": now.isoformat(),
        "liquidity": {
            "level": liq_level,
            "session": liq_session,
            "allow_trades": allow_trades,
            "allow_autopilot": allow_autopilot,
        },
    }


# ---- Lot sizing / SL-TP ----
def calculate_lot_size(capital, risk_percent, sl_distance, symbol):
    if sl_distance <= 0 or capital <= 0 or risk_percent <= 0:
        return 0.01
    mult = SYMBOLS.get(symbol, {}).get("mult", 100000)
    risk_amount = capital * (risk_percent / 100.0)
    raw = risk_amount / (sl_distance * mult)
    return max(0.01, round(raw, 2))


def default_sl_tp(symbol, mode, side, entry):
    cfg = SYMBOLS[symbol]
    dec = cfg["decimals"]
    if symbol == "XAU/USD":
        d = {"SCALPING_A": (3.5, 7.0), "SCALPING_B": (6.0, 12.0), "SWING": (18.0, 54.0)}
    elif symbol == "XAG/USD":
        d = {"SCALPING_A": (0.08, 0.16), "SCALPING_B": (0.15, 0.30), "SWING": (0.45, 1.35)}
    elif symbol == "DXY":
        d = {"SCALPING_A": (0.12, 0.24), "SCALPING_B": (0.20, 0.40), "SWING": (0.60, 1.80)}
    elif symbol == "USD/JPY":
        d = {"SCALPING_A": (0.12, 0.24), "SCALPING_B": (0.20, 0.40), "SWING": (0.60, 1.80)}
    else:
        d = {"SCALPING_A": (0.0012, 0.0024), "SCALPING_B": (0.0020, 0.0040), "SWING": (0.0060, 0.0180)}
    sl_d, tp_d = d.get(mode, (0.0012, 0.0024))
    if side == "BUY":
        return round(entry - sl_d, dec), round(entry + tp_d, dec)
    return round(entry + sl_d, dec), round(entry - tp_d, dec)


# ---- DB helpers ----
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
        except Exception:
            pass
    for pragma in ("PRAGMA synchronous=FULL", "PRAGMA foreign_keys=ON", "PRAGMA busy_timeout=30000"):
        try:
            conn.execute(pragma)
        except Exception:
            pass
    return conn


def db_exec(sql, params=()):
    with DB_LOCK:
        c = get_conn()
        try:
            cur = c.execute(sql, params)
            c.commit()
            try:
                last_id = cur.lastrowid
            except Exception:
                last_id = None
            return last_id or 0
        except Exception:
            try:
                c.rollback()
            except Exception:
                pass
            raise
        finally:
            c.close()


def db_query(sql, params=()):
    with DB_LOCK:
        c = get_conn()
        try:
            return c.execute(sql, params).fetchall()
        finally:
            c.close()


def db_query_one(sql, params=()):
    with DB_LOCK:
        c = get_conn()
        try:
            return c.execute(sql, params).fetchone()
        finally:
            c.close()


def init_db():
    with DB_LOCK:
        c = get_conn()
        try:
            cur = c.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    capital REAL NOT NULL DEFAULT 10000.0,
                    risk_percent REAL NOT NULL DEFAULT 1.0,
                    updated_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
                    entry_type TEXT NOT NULL CHECK (entry_type IN ('MARKET','LIMIT')),
                    mode TEXT NOT NULL,
                    htf_analysis TEXT NOT NULL,
                    entry_timeframe TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    lot_size REAL NOT NULL,
                    strategy TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING','ACTIVE','WIN','LOSS','CANCELLED')),
                    pnl REAL DEFAULT 0.0,
                    exit_price REAL,
                    confluence_score REAL DEFAULT 0.0,
                    confluence_bias TEXT DEFAULT 'neutral',
                    force_override INTEGER DEFAULT 0,
                    autopilot_origin INTEGER DEFAULT 0,
                    opened_at TEXT NOT NULL,
                    activated_at TEXT,
                    closed_at TEXT
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS strategies (
                    name TEXT PRIMARY KEY,
                    total_trades INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS self_learning (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER, symbol TEXT, strategy TEXT, mode TEXT,
                    lesson TEXT, created_at TEXT NOT NULL,
                    FOREIGN KEY (trade_id) REFERENCES trades (id)
                )
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_learning_created ON self_learning(created_at)")

            trade_cols = [r["name"] for r in cur.execute("PRAGMA table_info(trades)").fetchall()]
            for col, ddl in [
                ("confluence_score", "ALTER TABLE trades ADD COLUMN confluence_score REAL DEFAULT 0"),
                ("confluence_bias", "ALTER TABLE trades ADD COLUMN confluence_bias TEXT DEFAULT 'neutral'"),
                ("force_override", "ALTER TABLE trades ADD COLUMN force_override INTEGER DEFAULT 0"),
                ("autopilot_origin", "ALTER TABLE trades ADD COLUMN autopilot_origin INTEGER DEFAULT 0"),
            ]:
                if col not in trade_cols:
                    cur.execute(ddl)

            settings_cols = [r["name"] for r in cur.execute("PRAGMA table_info(bot_settings)").fetchall()]
            for col, ddl in [
                ("autopilot_enabled", "ALTER TABLE bot_settings ADD COLUMN autopilot_enabled INTEGER DEFAULT 0"),
                ("autopilot_cooldown_sec", "ALTER TABLE bot_settings ADD COLUMN autopilot_cooldown_sec INTEGER DEFAULT 60"),
                ("autopilot_max_concurrent", "ALTER TABLE bot_settings ADD COLUMN autopilot_max_concurrent INTEGER DEFAULT 3"),
                ("autopilot_min_score", "ALTER TABLE bot_settings ADD COLUMN autopilot_min_score REAL DEFAULT 6.0"),
            ]:
                if col not in settings_cols:
                    cur.execute(ddl)

            cur.execute("SELECT COUNT(*) AS c FROM bot_settings")
            is_first_launch = cur.fetchone()["c"] == 0

            for name in ICT_STRATEGIES:
                cur.execute("INSERT OR IGNORE INTO strategies (name, total_trades, wins, losses) VALUES (?, 0, 0, 0)", (name,))

            if is_first_launch:
                cur.execute("INSERT INTO bot_settings (id, capital, risk_percent, updated_at) VALUES (1, ?, ?, ?)",
                            (10000.0, 1.0, now_iso()))
                rng = random.Random(11)
                for name in ICT_STRATEGIES:
                    total = rng.randint(30, 80)
                    wr = rng.uniform(0.55, 0.79)
                    wins = int(total * wr)
                    cur.execute("UPDATE strategies SET total_trades=?, wins=?, losses=? WHERE name=?",
                                (total, wins, total - wins, name))
            else:
                for name in ICT_STRATEGIES:
                    row = cur.execute("SELECT total_trades FROM strategies WHERE name=?", (name,)).fetchone()
                    if row and row["total_trades"] == 0:
                        rng = random.Random(hash(name) & 0xFFFFFFFF)
                        total = rng.randint(30, 80)
                        wr = rng.uniform(0.55, 0.79)
                        wins = int(total * wr)
                        cur.execute("UPDATE strategies SET total_trades=?, wins=?, losses=? WHERE name=?",
                                    (total, wins, total - wins, name))

            c.commit()
        except Exception:
            try:
                c.rollback()
            except Exception:
                pass
            raise
        finally:
            c.close()


# ---- Price feeds ----
def fetch_metals_spot(spot_code):
    url = f"https://api.gold-api.com/price/{spot_code}"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    price = payload.get("price")
    if price is None:
        raise ValueError(f"gold-api: no price for {spot_code}")
    return float(price), None, None, None


def fetch_yahoo_quote(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json",
                                "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8")
    payload = json.loads(raw)
    result = payload["chart"]["result"][0]
    meta = result.get("meta", {})
    price = meta.get("regularMarketPrice")
    prev = meta.get("previousClose") or meta.get("chartPreviousClose")
    high = meta.get("regularMarketDayHigh")
    low = meta.get("regularMarketDayLow")
    if price is None:
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        clean = [c for c in closes if c is not None]
        if clean:
            price = clean[-1]
    if price is None:
        raise ValueError(f"no price in Yahoo for {ticker}")
    return (float(price), float(prev) if prev is not None else float(price),
            float(high) if high is not None else None,
            float(low) if low is not None else None)


def apply_tick(sym, price, prev_close, day_high, day_low, source):
    lo, hi = PRICE_BOUNDS.get(sym, (0.000001, 1e12))
    if not (lo <= price <= hi):
        print(f"[price] {sym} REJECTED {price} (bounds {lo}-{hi})", flush=True)
        return False
    with PRICE_LOCK:
        st = PRICES[sym]
        st["prev_price"] = st["price"]
        st["price"] = float(price)
        if prev_close is not None: st["prev_close"] = float(prev_close)
        if day_high is not None: st["high"] = max(st["high"], float(day_high))
        if day_low is not None: st["low"] = min(st["low"], float(day_low))
        st["high"] = max(st["high"], st["price"])
        st["low"] = min(st["low"], st["price"])
        st["last_update"] = now_iso()
        st["source"] = source
        st["stale"] = False
        h = st["history"]
        h.append(st["price"])
        if len(h) > 120:
            h.pop(0)
    return True


def should_fetch(sym):
    entry = LAST_FETCH.get(sym)
    if not entry: return True
    return (time.time() - entry["time"]) >= entry["backoff"]


def record_fetch(sym, success):
    LAST_FETCH[sym] = {"time": time.time(), "backoff": 1.0 if success else 20.0}


def fetch_one_safe(sym):
    if not should_fetch(sym):
        return
    cfg = SYMBOLS[sym]
    try:
        if cfg["metals_spot"]:
            try:
                price, _, _, _ = fetch_metals_spot(cfg["spot_code"])
                if apply_tick(sym, price, None, None, None, "gold-api-spot"):
                    record_fetch(sym, True)
                    print(f"[price] {sym} = {price:.{cfg['decimals']}f} (gold-api-spot)", flush=True)
                    return
            except Exception as spot_exc:
                print(f"[price] {sym} spot failed ({spot_exc}) — Yahoo fallback", flush=True)
        price, prev_close, hi, lo = fetch_yahoo_quote(cfg["yahoo"])
        if apply_tick(sym, price, prev_close, hi, lo, "yahoo"):
            record_fetch(sym, True)
            print(f"[price] {sym} = {price:.{cfg['decimals']}f} (yahoo)", flush=True)
        else:
            record_fetch(sym, False)
    except Exception as exc:
        print(f"[price] {sym} fetch failed: {exc}", flush=True)
        record_fetch(sym, False)


def price_feed_loop():
    while not SHUTDOWN.is_set():
        try:
            for sym in SYMBOLS.keys():
                PRICE_POOL.submit(fetch_one_safe, sym)
        except Exception as exc:
            print(f"[price_loop] {exc}", flush=True)
        SHUTDOWN.wait(1.0)


def day_rollover_loop():
    last_day = datetime.now(timezone.utc).date()
    while not SHUTDOWN.is_set():
        try:
            today = datetime.now(timezone.utc).date()
            if today != last_day:
                with PRICE_LOCK:
                    for sym in SYMBOLS:
                        st = PRICES[sym]
                        st["prev_close"] = st["price"]
                        st["open"] = st["price"]
                        st["high"] = st["price"]
                        st["low"] = st["price"]
                last_day = today
        except Exception as exc:
            print(f"[rollover] {exc}", flush=True)
        SHUTDOWN.wait(30.0)


def macro_fetch_loop():
    while not SHUTDOWN.is_set():
        try:
            vix_price, _, _, _ = fetch_yahoo_quote("%5EVIX")
            with MACRO_LOCK:
                MACRO["vix"] = round(vix_price, 2)
        except Exception as exc:
            print(f"[macro] VIX failed: {exc}", flush=True)
        try:
            tnx_price, _, _, _ = fetch_yahoo_quote("%5ETNX")
            us10y = tnx_price / 10.0 if tnx_price > 10.0 else tnx_price
            with MACRO_LOCK:
                MACRO["us10y"] = round(us10y, 3)
        except Exception as exc:
            print(f"[macro] US10Y failed: {exc}", flush=True)

        with MACRO_LOCK:
            MACRO["regime"] = classify_regime(MACRO["vix"])
            MACRO["safe_haven"] = classify_safe_haven(MACRO["regime"])
            with PRICE_LOCK:
                xau = PRICES["XAU/USD"]["price"]
                xag = PRICES["XAG/USD"]["price"]
            gsr = (xau / xag) if xag > 0 else 80.0
            geo = 0.0
            geo += min(40.0, max(0.0, (MACRO["vix"] - 12.0) * 2.2))
            geo += min(25.0, max(0.0, (gsr - 70.0) * 0.9))
            geo += min(20.0, max(0.0, (4.5 - MACRO["us10y"]) * 12.0))
            geo += min(15.0, max(0.0, abs(MACRO["vix"] - 18.0) * 0.35))
            MACRO["geo_risk"] = round(min(100.0, geo), 1)
            MACRO["geo_risk_label"] = geo_risk_label(MACRO["geo_risk"])
            MACRO["updated_at"] = now_iso()
            MACRO["last_ok"] = now_iso()

        SHUTDOWN.wait(10.0)


def central_bank_loop():
    while not SHUTDOWN.is_set():
        try:
            with CB_LOCK:
                for key in CB_STATE:
                    cb = CB_STATE[key]
                    drift = random.gauss(0.0, 0.30)
                    cb["cut"] = max(0.0, min(100.0, cb["cut"] + drift))
                    cb["hike"] = max(0.0, min(100.0, cb["hike"] - drift * 0.4))
                    cb["hold"] = max(0.0, 100.0 - cb["cut"] - cb["hike"])
                    total = cb["cut"] + cb["hold"] + cb["hike"]
                    if total > 0:
                        cb["cut"] = round(cb["cut"] * 100.0 / total, 1)
                        cb["hold"] = round(cb["hold"] * 100.0 / total, 1)
                        cb["hike"] = round(100.0 - cb["cut"] - cb["hold"], 1)
        except Exception as exc:
            print(f"[cb] {exc}", flush=True)
        SHUTDOWN.wait(8.0)


COT_KEY_CANDIDATES = {
    "Gold":   ["gold", "gold-futures", "comex-gold"],
    "Silver": ["silver", "silver-futures", "comex-silver"],
    "EUR":    ["euro-fx", "euro", "euro-futures", "eur"],
    "GBP":    ["british-pound", "gbp", "pound", "british-pound-fx"],
    "JPY":    ["japanese-yen", "jpy", "yen", "japanese-yen-fx"],
}


def fetch_cot():
    url = "https://futuresbench.com/api/v1/latest.json"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    markets = payload.get("markets") or {}
    with COT_LOCK:
        for asset, keys in COT_KEY_CANDIDATES.items():
            row = None
            for k in keys:
                if k in markets:
                    row = markets[k]; break
            if row is None: continue
            net = row.get("net_noncommercial")
            chg = row.get("net_noncommercial_change")
            oi = row.get("open_interest")
            if net is None: continue
            if oi and oi > abs(net):
                long_v = int((oi + net) / 2); short_v = int((oi - net) / 2)
            else:
                long_v = max(0, int(net) + 50000); short_v = max(0, 50000 - int(net))
            prev_net = net - (chg if chg is not None else 0)
            if chg is not None and oi and oi > abs(prev_net):
                prev_long = int((oi + prev_net) / 2); prev_short = int((oi - prev_net) / 2)
            else:
                prev_long = long_v; prev_short = short_v
            COT_STATE[asset]["long"] = long_v; COT_STATE[asset]["short"] = short_v
            COT_STATE[asset]["prev_long"] = prev_long; COT_STATE[asset]["prev_short"] = prev_short
            COT_STATE[asset]["source"] = "futuresbench"
    print("[cot] updated from FuturesBench", flush=True)


def cot_loop():
    while not SHUTDOWN.is_set():
        try:
            fetch_cot()
        except Exception as exc:
            print(f"[cot] fetch failed: {exc}", flush=True)
        SHUTDOWN.wait(300.0)


# ---- Bias / confluence ----
def compute_market_bias():
    components = []
    score = 0.0
    try:
        with PRICE_LOCK:
            dxy_now = PRICES["DXY"]["price"]; dxy_prev = PRICES["DXY"]["prev_close"]
        dxy_chg_pct = ((dxy_now - dxy_prev) / dxy_prev * 100.0) if dxy_prev > 0 else 0.0
        dxy_pts = max(-30.0, min(30.0, dxy_chg_pct * 300.0))
        score += dxy_pts
        components.append({"key": "dxy", "name_en": "DXY Momentum", "name_ar": "زخم مؤشر الدولار",
                           "value": round(dxy_chg_pct, 3), "unit": "%", "points": round(dxy_pts, 1),
                           "impact": "bullish_usd" if dxy_pts > 5 else ("bearish_usd" if dxy_pts < -5 else "neutral")})
    except Exception as exc:
        print(f"[bias] dxy: {exc}", flush=True)
    try:
        with MACRO_LOCK:
            us10y = MACRO["us10y"]
        yld_pts = max(-25.0, min(25.0, (us10y - 4.30) * 50.0))
        score += yld_pts
        components.append({"key": "us10y", "name_en": "US10Y Yield", "name_ar": "عائد السندات الأمريكية",
                           "value": round(us10y, 3), "unit": "%", "points": round(yld_pts, 1),
                           "impact": "bullish_usd" if yld_pts > 5 else ("bearish_usd" if yld_pts < -5 else "neutral")})
    except Exception as exc:
        print(f"[bias] yield: {exc}", flush=True)
    try:
        with COT_LOCK:
            foreign_net = 0
            for asset in ("Gold", "EUR", "GBP", "JPY"):
                row = COT_STATE.get(asset)
                if row: foreign_net += row["long"] - row["short"]
        cot_pts = max(-25.0, min(25.0, -foreign_net / 200000.0 * 25.0))
        score += cot_pts
        components.append({"key": "cot", "name_en": "COT Positioning", "name_ar": "مراكز المؤسسات",
                           "value": int(foreign_net), "unit": "net", "points": round(cot_pts, 1),
                           "impact": "bullish_usd" if cot_pts > 5 else ("bearish_usd" if cot_pts < -5 else "neutral")})
    except Exception as exc:
        print(f"[bias] cot: {exc}", flush=True)
    try:
        with PRICE_LOCK:
            xau = PRICES["XAU/USD"]["price"]; xag = PRICES["XAG/USD"]["price"]
        gsr = (xau / xag) if xag > 0 else 80.0
        gsr_pts = max(-20.0, min(20.0, (gsr - 80.0) * 2.0))
        score += gsr_pts
        components.append({"key": "gsr", "name_en": "Gold/Silver Ratio", "name_ar": "نسبة الذهب/الفضة",
                           "value": round(gsr, 2), "unit": "", "points": round(gsr_pts, 1),
                           "impact": "bullish_usd" if gsr_pts > 5 else ("bearish_usd" if gsr_pts < -5 else "neutral")})
    except Exception as exc:
        print(f"[bias] gsr: {exc}", flush=True)

    score = max(-100.0, min(100.0, score))
    if score >= 60:
        label_en, label_ar, direction = "Strong USD Bias", "انحياز قوي للدولار", "bullish_usd"
    elif score >= 25:
        label_en, label_ar, direction = "Mild USD Strength", "قوة معتدلة للدولار", "bullish_usd"
    elif score <= -60:
        label_en, label_ar, direction = "Strong Anti-USD Bias", "انحياز قوي ضد الدولار", "bearish_usd"
    elif score <= -25:
        label_en, label_ar, direction = "Mild USD Weakness", "ضعف معتدل للدولار", "bearish_usd"
    else:
        label_en, label_ar, direction = "Neutral", "محايد", "neutral"

    return {
        "score": round(score, 1), "direction": direction,
        "label_en": label_en, "label_ar": label_ar, "components": components,
        "guardrail_active": abs(score) >= BIAS_GUARDRAIL_THRESHOLD,
        "guardrail_threshold": BIAS_GUARDRAIL_THRESHOLD,
        "updated_at": now_iso(),
    }


def symbol_alignment(symbol, side, bias):
    score = bias.get("score", 0.0)
    guardrail = bias.get("guardrail_active", False)
    with_trend_side = None
    if symbol in ANTI_USD_SYMBOLS:
        if score < 0: with_trend_side = "BUY"
        elif score > 0: with_trend_side = "SELL"
    elif symbol in PRO_USD_SYMBOLS:
        if score > 0: with_trend_side = "BUY"
        elif score < 0: with_trend_side = "SELL"
    blocked = guardrail and with_trend_side is not None and side != with_trend_side
    return {
        "symbol": symbol, "side": side,
        "aligned": (not guardrail) or (with_trend_side == side),
        "blocked": blocked, "with_trend_side": with_trend_side,
        "guardrail_active": guardrail, "market_score": score,
    }


def macro_bias_for_symbol(symbol):
    regime = MACRO["regime"]; us10y = MACRO["us10y"]
    with PRICE_LOCK:
        dxy_rising = PRICES["DXY"]["price"] >= PRICES["DXY"]["prev_close"]
    if symbol in ("XAU/USD", "XAG/USD"):
        if regime in ("Crisis", "Risk-Off"): return "bullish"
        if regime == "Risk-On": return "bearish" if us10y > 4.2 else "neutral"
        return "bullish" if (not dxy_rising and us10y < 4.3) else "neutral"
    if symbol == "DXY":
        if regime in ("Crisis", "Risk-Off"): return "bullish"
        if regime == "Risk-On": return "bearish"
        return "bullish" if us10y > 4.3 else "neutral"
    if symbol == "EUR/USD":
        if regime == "Risk-On": return "bullish"
        if regime in ("Crisis", "Risk-Off"): return "bearish"
        return "bullish" if not dxy_rising else "bearish"
    if symbol == "GBP/USD":
        if regime == "Risk-On": return "bullish"
        if regime in ("Crisis", "Risk-Off"): return "bearish"
        return "neutral"
    if symbol == "USD/JPY":
        if regime in ("Crisis", "Risk-Off"): return "bearish"
        if regime == "Risk-On": return "bullish"
        return "bullish" if us10y > 4.3 else "bearish"
    return "neutral"


def cot_bias_for_symbol(symbol):
    if symbol == "DXY":
        total_net = 0; total_delta = 0
        with COT_LOCK:
            for asset in ("EUR", "GBP", "JPY"):
                row = COT_STATE.get(asset)
                if row:
                    total_net += row["long"] - row["short"]
                    total_delta += (row["long"] - row["prev_long"]) - (row["short"] - row["prev_short"])
        if total_net < 0 and total_delta < 0: return "bullish"
        if total_net > 0 and total_delta > 0: return "bearish"
        return "neutral"
    mapping = {"XAU/USD": "Gold", "XAG/USD": "Silver", "EUR/USD": "EUR",
               "GBP/USD": "GBP", "USD/JPY": "JPY"}
    asset = mapping.get(symbol)
    if asset is None: return "neutral"
    with COT_LOCK:
        row = COT_STATE.get(asset)
        if not row: return "neutral"
        net = row["long"] - row["short"]
        delta = (row["long"] - row["prev_long"]) - (row["short"] - row["prev_short"])
    if asset == "JPY":
        if net > 0 and delta > 0: return "bearish"
        if net < 0 and delta < 0: return "bullish"
        return "neutral"
    if net > 0 and delta >= 0: return "bullish"
    if net < 0 and delta <= 0: return "bearish"
    return "neutral"


def strategy_win_rate(strategy):
    row = db_query_one("SELECT total_trades, wins FROM strategies WHERE name=?", (strategy,))
    if not row or row["total_trades"] == 0: return 50.0
    return float(row["wins"]) * 100.0 / float(row["total_trades"])


def compute_confluence(symbol, side, mode, strategy):
    reasons = []
    score = 0
    max_score = 10

    with PRICE_LOCK:
        st = PRICES[symbol]
        price = st["price"]; prev_close = st["prev_close"]
    htf_bull = price >= prev_close
    htf_ok = (htf_bull and side == "BUY") or ((not htf_bull) and side == "SELL")
    if htf_ok:
        score += 2
        reasons.append({"key": "htf_aligned", "points": 2, "passed": True,
                        "en": f"HTF bias ({'bullish' if htf_bull else 'bearish'}) aligns with {side}",
                        "ar": f"اتجاه الإطار الأعلى ({'صاعد' if htf_bull else 'هابط'}) متوافق"})
    else:
        reasons.append({"key": "htf_conflict", "points": 0, "passed": False,
                        "en": f"HTF bias conflicts with {side}",
                        "ar": f"اتجاه الإطار الأعلى يتعارض"})

    mb = macro_bias_for_symbol(symbol)
    macro_ok = (mb == "bullish" and side == "BUY") or (mb == "bearish" and side == "SELL")
    if macro_ok:
        score += 2
        reasons.append({"key": "macro_aligned", "points": 2, "passed": True,
                        "en": f"Macro regime '{MACRO['regime']}' supports {side}",
                        "ar": f"النظام السوقي يدعم"})
    else:
        reasons.append({"key": "macro_conflict", "points": 0, "passed": False,
                        "en": f"Macro regime is {mb}",
                        "ar": f"النظام السوقي غير متوافق"})

    with PRICE_LOCK:
        dxy_down = PRICES["DXY"]["price"] < PRICES["DXY"]["prev_close"]
    dxy_ok = False
    if symbol in ("XAU/USD", "XAG/USD", "EUR/USD", "GBP/USD"):
        dxy_ok = (side == "BUY" and dxy_down) or (side == "SELL" and not dxy_down)
    elif symbol in ("USD/JPY", "DXY"):
        dxy_ok = (side == "BUY" and not dxy_down) or (side == "SELL" and dxy_down)
    if dxy_ok:
        score += 1
        reasons.append({"key": "dxy_aligned", "points": 1, "passed": True,
                        "en": "DXY direction confirms", "ar": "اتجاه الدولار يؤكد"})
    else:
        reasons.append({"key": "dxy_conflict", "points": 0, "passed": False,
                        "en": "DXY direction conflicts", "ar": "اتجاه الدولار يتعارض"})

    cb = cot_bias_for_symbol(symbol)
    cot_ok = (cb == "bullish" and side == "BUY") or (cb == "bearish" and side == "SELL")
    if cot_ok:
        score += 1
        reasons.append({"key": "cot_aligned", "points": 1, "passed": True,
                        "en": f"COT {cb}", "ar": f"COT {('صاعد' if cb == 'bullish' else 'هابط')}"})
    else:
        reasons.append({"key": "cot_neutral", "points": 0, "passed": False,
                        "en": f"COT {cb}", "ar": f"COT {('محايد' if cb == 'neutral' else 'غير متوافق')}"})

    vix = MACRO["vix"]
    vix_scored = False
    if symbol == "DXY":
        if vix >= 22 and side == "BUY":
            score += 1; vix_scored = True
            reasons.append({"key": "vix_usd_bid", "points": 1, "passed": True,
                            "en": f"VIX {vix:.1f} supports USD bid", "ar": "VIX يدعم الدولار"})
        elif vix <= 14 and side == "SELL":
            score += 1; vix_scored = True
            reasons.append({"key": "vix_usd_sell", "points": 1, "passed": True,
                            "en": f"VIX {vix:.1f} supports DXY SELL", "ar": "VIX يدعم بيع DXY"})
    elif symbol in ("XAU/USD", "XAG/USD") and side == "BUY" and vix >= 25:
        score += 1; vix_scored = True
        reasons.append({"key": "vix_haven", "points": 1, "passed": True,
                        "en": f"VIX {vix:.1f} safe-haven", "ar": "VIX يدعم الملاذ الآمن"})
    elif symbol in ("EUR/USD", "GBP/USD") and side == "BUY" and vix <= 15:
        score += 1; vix_scored = True
        reasons.append({"key": "vix_risk_on", "points": 1, "passed": True,
                        "en": f"VIX {vix:.1f} risk-on", "ar": "VIX يدعم شهية المخاطرة"})
    if not vix_scored:
        reasons.append({"key": "vix_neutral", "points": 0, "passed": False,
                        "en": f"VIX {vix:.1f} no edge", "ar": "VIX بدون أفضلية"})

    wr = strategy_win_rate(strategy)
    if wr >= 60.0:
        score += 1
        reasons.append({"key": "strategy_edge", "points": 1, "passed": True,
                        "en": f"WR {wr:.1f}%", "ar": f"نسبة النجاح {wr:.1f}%"})
    else:
        reasons.append({"key": "strategy_weak", "points": 0, "passed": False,
                        "en": f"WR {wr:.1f}%", "ar": f"نسبة النجاح {wr:.1f}%"})

    if is_kill_zone():
        score += 1
        reasons.append({"key": "kill_zone", "points": 1, "passed": True,
                        "en": "Active Kill Zone", "ar": "منطقة القتل النشطة"})
    else:
        reasons.append({"key": "no_kill_zone", "points": 0, "passed": False,
                        "en": "Outside Kill Zone", "ar": "خارج منطقة القتل"})

    us10y = MACRO["us10y"]
    if symbol in ("XAU/USD", "XAG/USD"):
        y_ok = (side == "BUY" and us10y < 4.3) or (side == "SELL" and us10y > 4.4)
    elif symbol in ("USD/JPY", "DXY"):
        y_ok = (side == "BUY" and us10y > 4.3) or (side == "SELL" and us10y < 4.2)
    else:
        y_ok = (side == "BUY" and us10y < 4.3) or (side == "SELL" and us10y > 4.3)
    if y_ok:
        score += 1
        reasons.append({"key": "yield_aligned", "points": 1, "passed": True,
                        "en": f"US10Y {us10y:.2f}% aligned", "ar": f"عائد السندات {us10y:.2f}% متوافق"})
    else:
        reasons.append({"key": "yield_conflict", "points": 0, "passed": False,
                        "en": f"US10Y {us10y:.2f}% conflicts", "ar": f"عائد السندات {us10y:.2f}% يتعارض"})

    strat_ict = {
        "Liquidity Sweep & Stop Hunt": True,
        "Fair Value Gap (FVG)": True,
        "Order Block (OB)": True,
        "Change of Character (CHoCH)": True,
        "Market Structure Shift (MSS)": True,
        "Break of Structure (BOS)": True,
        "Breaker Block": True,
        "Mitigation Block": True,
        "Balanced Price Range (BPR)": True,
        "Volume Gap": True,
        "Inducement (IDM)": True,
        "Judas Swing / ORL": is_kill_zone(),
        "Kill Zones & Power of 3": is_kill_zone(),
        "Silver Bullet Strategy": is_silver_bullet(),
        "Optimal Trade Entry (OTE)": True,
        "Premium & Discount Zones": True,
        "Inversion FVG (IFVG)": True,
        "Institutional Order Flow (IOF)": True,
        "Quarterly Theory / IPDA": True,
        "Daily Bias Framework": True,
    }
    if strat_ict.get(strategy, False):
        score += 1
        reasons.append({"key": "ict_valid", "points": 1, "passed": True,
                        "en": f"{strategy} valid", "ar": f"{STRATEGY_AR.get(strategy, strategy)} صالحة"})
    else:
        reasons.append({"key": "ict_invalid", "points": 0, "passed": False,
                        "en": f"{strategy} needs its conditions",
                        "ar": f"{STRATEGY_AR.get(strategy, strategy)} تحتاج شروطها"})

    if score >= 7: bias = "strong"
    elif score >= 5: bias = "moderate"
    elif score >= 3: bias = "weak"
    else: bias = "avoid"

    directional = "bullish" if side == "BUY" else "bearish"
    if score >= 7:
        headline_en = f"High-probability {directional} on {symbol}"
        headline_ar = f"إعداد {('صاعد' if side == 'BUY' else 'هابط')} عالي الاحتمالية على {symbol}"
    elif score >= 5:
        headline_en = f"Moderate {directional} on {symbol}"
        headline_ar = f"انحياز {('صاعد' if side == 'BUY' else 'هابط')} متوسط على {symbol}"
    else:
        headline_en = f"Low confluence on {symbol}"
        headline_ar = f"توافق منخفض على {symbol}"

    return {
        "score": score, "max_score": max_score, "threshold": 5,
        "approved": score >= 5, "bias": bias, "directional": directional,
        "headline_en": headline_en, "headline_ar": headline_ar, "reasons": reasons,
    }


def generate_lesson(trade_row, exit_price):
    sym = trade_row["symbol"]; side = trade_row["side"]
    entry = float(trade_row["entry_price"]); sl = float(trade_row["stop_loss"])
    strategy = trade_row["strategy"]; mode = trade_row["mode"]
    htf = trade_row["htf_analysis"]; entry_tf = trade_row["entry_timeframe"]
    cfg = SYMBOLS.get(sym, {})
    pip = cfg.get("pip", 0.0001); dec = cfg.get("decimals", 4)
    loss_pips = abs(entry - sl) / pip if pip > 0 else 0.0
    head = (f"[{TRADE_MODES.get(mode, {}).get('label_en', mode)}] {side} {sym} @ {entry:.{dec}f} → "
            f"SL {exit_price:.{dec}f} ({loss_pips:.1f} pips loss).")
    strat_lesson = STRATEGY_LESSONS.get(strategy, "Review entry vs HTF bias.")
    mode_lesson = MODE_LESSONS.get(mode, "Review timeframe alignment.")
    tf_line = f"Timeframe: HTF ({','.join(htf)}) ↔ Entry ({entry_tf})."
    return f"{head} {strat_lesson} {mode_lesson} {tf_line}"


# ---- Trade evaluator ----
def trade_evaluator():
    while not SHUTDOWN.is_set():
        try:
            with DB_LOCK:
                c = get_conn()
                try:
                    cur = c.cursor()
                    pending = cur.execute("SELECT * FROM trades WHERE status='PENDING' AND entry_type='LIMIT'").fetchall()
                    for t in pending:
                        with PRICE_LOCK:
                            current = PRICES.get(t["symbol"], {}).get("price")
                        if current is None: continue
                        hit = False
                        if t["side"] == "BUY" and current <= float(t["entry_price"]): hit = True
                        if t["side"] == "SELL" and current >= float(t["entry_price"]): hit = True
                        if hit:
                            cur.execute("UPDATE trades SET status='ACTIVE', activated_at=? WHERE id=?",
                                        (now_iso(), t["id"]))

                    active = cur.execute("SELECT * FROM trades WHERE status='ACTIVE'").fetchall()
                    for t in active:
                        tid = t["id"]; sym = t["symbol"]; side = t["side"]
                        entry = float(t["entry_price"]); sl = float(t["stop_loss"])
                        tp = float(t["take_profit"]); lot = float(t["lot_size"])
                        strat = t["strategy"]
                        with PRICE_LOCK:
                            current = PRICES.get(sym, {}).get("price")
                        if current is None: continue
                        outcome = None; exit_price = None
                        if side == "BUY":
                            if current <= sl: outcome, exit_price = "LOSS", sl
                            elif current >= tp: outcome, exit_price = "WIN", tp
                        else:
                            if current >= sl: outcome, exit_price = "LOSS", sl
                            elif current <= tp: outcome, exit_price = "WIN", tp
                        if outcome is None: continue
                        mult = SYMBOLS.get(sym, {}).get("mult", 100000)
                        diff = (exit_price - entry) if side == "BUY" else (entry - exit_price)
                        pnl = round(diff * mult * lot, 2)
                        iso = now_iso()
                        cur.execute("UPDATE trades SET status=?, pnl=?, exit_price=?, closed_at=? WHERE id=?",
                                    (outcome, pnl, exit_price, iso, tid))
                        if outcome == "WIN":
                            cur.execute("UPDATE strategies SET total_trades=total_trades+1, wins=wins+1 WHERE name=?", (strat,))
                        else:
                            cur.execute("UPDATE strategies SET total_trades=total_trades+1, losses=losses+1 WHERE name=?", (strat,))
                            lesson = generate_lesson(t, exit_price)
                            cur.execute("INSERT INTO self_learning (trade_id, symbol, strategy, mode, lesson, created_at) VALUES (?,?,?,?,?,?)",
                                        (tid, sym, strat, t["mode"], lesson, iso))
                    c.commit()
                except Exception:
                    try: c.rollback()
                    except Exception: pass
                    raise
                finally:
                    c.close()
        except Exception as exc:
            print(f"[evaluator] {exc}", flush=True)
            traceback.print_exc()
        SHUTDOWN.wait(0.5)


# ---- Autopilot ----
def get_autopilot_settings():
    r = db_query_one("SELECT autopilot_enabled, autopilot_cooldown_sec, autopilot_max_concurrent, autopilot_min_score FROM bot_settings WHERE id=1")
    if not r:
        return {"enabled": False, "cooldown_sec": 60, "max_concurrent": 3, "min_score": 6.0}
    return {
        "enabled": bool(r["autopilot_enabled"]),
        "cooldown_sec": int(r["autopilot_cooldown_sec"] or 60),
        "max_concurrent": int(r["autopilot_max_concurrent"] or 3),
        "min_score": float(r["autopilot_min_score"] or 6.0),
    }


def pick_top_strategy():
    if random.random() < 0.15:
        untested = db_query("SELECT name FROM strategies WHERE total_trades = 0")
        if untested:
            return random.choice([r["name"] for r in untested])
    rows = db_query("SELECT name FROM strategies WHERE total_trades > 0 ORDER BY CAST(wins AS REAL)/MAX(total_trades,1) DESC LIMIT 5")
    return random.choice([r["name"] for r in rows]) if rows else random.choice(ICT_STRATEGIES)


def find_best_autopilot_setup(bias, min_score):
    best = None; best_score = min_score
    with PRICE_LOCK:
        def vol_pct(sym):
            h = PRICES[sym]["history"]
            if len(h) < 5: return 0.0
            return (max(h) - min(h)) / max(min(h), 1e-9)
        ranked_symbols = sorted(TRADEABLE_SYMBOLS, key=vol_pct, reverse=True)

    for sym in ranked_symbols:
        existing = db_query_one(
            "SELECT COUNT(*) AS c FROM trades WHERE symbol=? AND status IN ('ACTIVE','PENDING')",
            (sym,))
        if existing and existing["c"] > 0:
            continue

        for mode in ("SCALPING_A", "SCALPING_B", "SWING"):
            for side in ("BUY", "SELL"):
                align = symbol_alignment(sym, side, bias)
                if align["blocked"]:
                    continue
                strat = pick_top_strategy()
                conf = compute_confluence(sym, side, mode, strat)
                if conf["score"] > best_score:
                    best_score = conf["score"]
                    best = {"symbol": sym, "side": side, "mode": mode,
                            "strategy": strat, "confluence": conf,
                            "alignment": align}
    return best


def execute_autopilot_trade(setup, bias):
    global _last_autopilot_trade_at
    sym = setup["symbol"]; side = setup["side"]; mode = setup["mode"]; strat = setup["strategy"]
    cfg = SYMBOLS[sym]; dec = cfg["decimals"]
    with PRICE_LOCK:
        live = PRICES[sym]["price"]
    entry = round(live, dec)
    sl, tp = default_sl_tp(sym, mode, side, entry)

    s = db_query_one("SELECT capital, risk_percent FROM bot_settings WHERE id=1")
    lot = calculate_lot_size(float(s["capital"]), float(s["risk_percent"]), abs(entry - sl), sym)

    htf_str = ",".join(TRADE_MODES[mode]["htf"])
    entry_tf = TRADE_MODES[mode]["entry_tfs"][0]

    new_id = db_exec(
        "INSERT INTO trades (symbol, side, entry_type, mode, htf_analysis, entry_timeframe, "
        "entry_price, stop_loss, take_profit, lot_size, strategy, status, "
        "confluence_score, confluence_bias, force_override, autopilot_origin, opened_at, activated_at) "
        "VALUES (?, ?, 'MARKET', ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, 0, 1, ?, ?)",
        (sym, side, mode, htf_str, entry_tf, entry, sl, tp, lot, strat,
         setup["confluence"]["score"], setup["confluence"]["directional"], now_iso(), now_iso())
    )
    _last_autopilot_trade_at = datetime.now(timezone.utc)
    ap_log(f"⚡ EXECUTED #{new_id}: {sym} {side} @ {entry} · {mode} · {strat} · score {setup['confluence']['score']}/10")
    return new_id


def autopilot_loop():
    global _last_autopilot_scan_at, _last_autopilot_status
    while not SHUTDOWN.is_set():
        try:
            ap_settings = get_autopilot_settings()
            if not ap_settings["enabled"]:
                _last_autopilot_status = "disabled"
                SHUTDOWN.wait(5.0)
                continue

            ms = compute_market_status()
            if not ms["is_open"]:
                if ms.get("news_blackout", {}).get("active"):
                    _last_autopilot_status = "news_blackout"
                else:
                    _last_autopilot_status = "market_closed"
                SHUTDOWN.wait(15.0)
                continue

            liq = ms["liquidity"]
            if not liq["allow_autopilot"]:
                _last_autopilot_status = f"liquidity_{liq['level']}"
                SHUTDOWN.wait(20.0)
                continue

            if _last_autopilot_trade_at:
                elapsed = (datetime.now(timezone.utc) - _last_autopilot_trade_at).total_seconds()
                if elapsed < ap_settings["cooldown_sec"]:
                    _last_autopilot_status = f"cooldown_{int(ap_settings['cooldown_sec'] - elapsed)}s"
                    SHUTDOWN.wait(5.0)
                    continue

            active_count = db_query_one("SELECT COUNT(*) AS c FROM trades WHERE status IN ('ACTIVE','PENDING')")
            if active_count and active_count["c"] >= ap_settings["max_concurrent"]:
                _last_autopilot_status = f"max_concurrent_{active_count['c']}/{ap_settings['max_concurrent']}"
                SHUTDOWN.wait(10.0)
                continue

            _last_autopilot_status = "scanning"
            _last_autopilot_scan_at = datetime.now(timezone.utc)
            bias = compute_market_bias()
            setup = find_best_autopilot_setup(bias, ap_settings["min_score"])
            if setup:
                execute_autopilot_trade(setup, bias)
            else:
                _last_autopilot_status = "no_setup"
            SHUTDOWN.wait(15.0)
        except Exception as exc:
            print(f"[autopilot] {exc}", flush=True)
            traceback.print_exc()
            _last_autopilot_status = "error"
            SHUTDOWN.wait(20.0)


# ---- Payload builders (for HTTP handler) ----
def get_prices_payload():
    data = {}
    with PRICE_LOCK:
        for s, c in SYMBOLS.items():
            st = PRICES[s]; open_p = st["open"]
            chg = ((st["price"] - open_p) / open_p * 100.0) if open_p else 0.0
            data[s] = {
                "price": round(st["price"], c["decimals"]),
                "prev_price": round(st["prev_price"], c["decimals"]),
                "open": round(open_p, c["decimals"]),
                "high": round(st["high"], c["decimals"]),
                "low": round(st["low"], c["decimals"]),
                "prev_close": round(st["prev_close"], c["decimals"]),
                "change_pct": round(chg, 3),
                "decimals": c["decimals"],
                "history": [round(x, c["decimals"]) for x in st["history"][-40:]],
                "last_update": st["last_update"],
                "source": st["source"], "stale": st["stale"],
                "tradeable": s in TRADEABLE_SYMBOLS,
            }
    return data


def get_summary_payload():
    r = db_query_one(
        "SELECT (SELECT COUNT(*) FROM trades) AS total, "
        "(SELECT COUNT(*) FROM trades WHERE status='PENDING') AS pending, "
        "(SELECT COUNT(*) FROM trades WHERE status='ACTIVE') AS active, "
        "(SELECT COUNT(*) FROM trades WHERE status='WIN') AS wins, "
        "(SELECT COUNT(*) FROM trades WHERE status='LOSS') AS losses, "
        "(SELECT COALESCE(SUM(pnl),0) FROM trades WHERE status IN ('WIN','LOSS')) AS realized")
    settings = db_query_one("SELECT capital, risk_percent FROM bot_settings WHERE id=1")
    total = int(r["total"]); wins = int(r["wins"]); losses = int(r["losses"])
    wr = (wins / (wins + losses) * 100.0) if (wins + losses) > 0 else 0.0
    with PRICE_LOCK:
        dxy_now = round(PRICES["DXY"]["price"], 3)
        feed_ok = sum(1 for s in SYMBOLS if not PRICES[s]["stale"])
    return {
        "capital": float(settings["capital"]), "risk_percent": float(settings["risk_percent"]),
        "total_trades": total, "pending": int(r["pending"]), "active": int(r["active"]),
        "wins": wins, "losses": losses, "win_rate": round(wr, 2),
        "realized_pnl": round(float(r["realized"]), 2),
        "session": active_session(), "kill_zone": is_kill_zone(),
        "silver_bullet": is_silver_bullet(),
        "dxy": dxy_now, "feed_ok": feed_ok, "feed_total": len(SYMBOLS),
    }


def get_macro_payload():
    with MACRO_LOCK:
        vix = round(MACRO["vix"], 2); us10y = round(MACRO["us10y"], 3)
        regime = MACRO["regime"]; haven = MACRO["safe_haven"]
        geo = MACRO["geo_risk"]; geo_label = MACRO["geo_risk_label"]; upd = MACRO["updated_at"]
    with PRICE_LOCK:
        xau = PRICES["XAU/USD"]["price"]; xag = PRICES["XAG/USD"]["price"]
        dxy = PRICES["DXY"]["price"]; dxy_prev = PRICES["DXY"]["prev_close"]
        dxy_hist = list(PRICES["DXY"]["history"][-20:])
    gsr = round(xau / xag, 2) if xag > 0 else 0.0
    flow = 0
    if dxy < dxy_prev: flow += 2
    else: flow -= 2
    if regime in ("Risk-Off", "Crisis"): flow += 3
    elif regime == "Risk-On": flow -= 1
    if us10y > 4.4: flow -= 1
    elif us10y < 4.0: flow += 1
    if vix > 25: flow += 2
    flow = max(-10, min(10, flow))
    return {
        "vix": vix, "us10y": us10y, "dxy": round(dxy, 3),
        "dxy_prev": round(dxy_prev, 3),
        "dxy_history": [round(x, 3) for x in dxy_hist],
        "gold_silver_ratio": gsr, "regime": regime, "safe_haven": haven,
        "geo_risk": geo, "geo_risk_label": geo_label,
        "dxy_flow_score": flow, "updated_at": upd,
    }


def get_cb_payload():
    with CB_LOCK:
        return {k: dict(v) for k, v in CB_STATE.items()}


def get_cot_payload():
    with COT_LOCK:
        snapshot = {k: dict(v) for k, v in COT_STATE.items()}
    out = {}
    for name, c in snapshot.items():
        total = c["long"] + c["short"]
        net = c["long"] - c["short"]
        delta_net = (c["long"] - c["prev_long"]) - (c["short"] - c["prev_short"])
        out[name] = {"long": c["long"], "short": c["short"], "net": net,
                     "delta_net": delta_net,
                     "long_pct": round(c["long"] * 100.0 / max(1, total), 2),
                     "short_pct": round(c["short"] * 100.0 / max(1, total), 2),
                     "label_ar": c.get("label_ar", name),
                     "source": c.get("source", "seed")}
    return out


def get_calendar_payload():
    with CAL_LOCK:
        return build_calendar()


def get_feed_status_payload():
    with PRICE_LOCK:
        data = {s: {"source": PRICES[s]["source"], "stale": PRICES[s]["stale"],
                    "last_update": PRICES[s]["last_update"],
                    "yahoo_ticker": c["yahoo"], "spot_code": c["spot_code"],
                    "metals_spot": c["metals_spot"],
                    "tradeable": s in TRADEABLE_SYMBOLS,
                    "price": round(PRICES[s]["price"], c["decimals"])}
                for s, c in SYMBOLS.items()}
    return data


def get_autopilot_payload():
    ap = get_autopilot_settings()
    active_count = db_query_one("SELECT COUNT(*) AS c FROM trades WHERE status IN ('ACTIVE','PENDING')")
    with AP_LOCK:
        log_snapshot = list(AUTOPILOT_LOG)
    return {
        "enabled": ap["enabled"],
        "config": {"min_score": ap["min_score"],
                   "max_concurrent": ap["max_concurrent"],
                   "cooldown_sec": ap["cooldown_sec"]},
        "stats": {
            "active_trades": int(active_count["c"]) if active_count else 0,
            "last_trade_at": _last_autopilot_trade_at.isoformat() if _last_autopilot_trade_at else None,
            "last_scan_at": _last_autopilot_scan_at.isoformat() if _last_autopilot_scan_at else None,
            "status": _last_autopilot_status,
        },
        "log": log_snapshot,
    }


def get_live_price(sym):
    with PRICE_LOCK:
        return PRICES.get(sym, {}).get("price")


# ---- Thread lifecycle ----
def start_threads():
    threads = [
        threading.Thread(target=price_feed_loop,   daemon=True, name="price_feed"),
        threading.Thread(target=day_rollover_loop, daemon=True, name="rollover"),
        threading.Thread(target=macro_fetch_loop,  daemon=True, name="macro"),
        threading.Thread(target=central_bank_loop, daemon=True, name="cb"),
        threading.Thread(target=cot_loop,          daemon=True, name="cot"),
        threading.Thread(target=trade_evaluator,   daemon=True, name="evaluator"),
        threading.Thread(target=autopilot_loop,    daemon=True, name="autopilot"),
    ]
    for th in threads:
        th.start()
    return threads


def begin_shutdown():
    SHUTDOWN.set()


def cleanup_threads(threads, timeout=3.0):
    PRICE_POOL.shutdown(wait=False)
    for th in threads:
        th.join(timeout=timeout)
