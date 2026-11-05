#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
App module — HTTP handler, frontend HTML, and main entry point.
"""

import json
import signal
import traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import config
import engine


class Handler(BaseHTTPRequestHandler):
    server_version = "ProTradingEngine/7.2"

    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

    def _json(self, payload, status=200):
        try:
            body = json.dumps(payload, default=str).encode("utf-8")
        except Exception as exc:
            body = json.dumps({"ok": False, "error": f"serialize: {exc}"}).encode("utf-8")
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try: self.wfile.write(body)
        except BrokenPipeError: pass

    def _html(self, content, status=200):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try: self.wfile.write(body)
        except BrokenPipeError: pass

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0: return {}
        raw = self.rfile.read(length)
        try: return json.loads(raw.decode("utf-8"))
        except Exception as exc: raise ValueError(f"invalid JSON: {exc}")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._html(INDEX_HTML); return

            if path == "/api/health":
                self._json({"ok": True, "time": config.now_iso(), "session": engine.active_session(),
                            "kill_zone": engine.is_kill_zone(), "silver_bullet": engine.is_silver_bullet(),
                            "version": "7.2", "db_path": config.DB_PATH})
                return

            if path == "/api/config":
                self._json({"ok": True,
                            "symbols": {s: {"decimals": c["decimals"], "mult": c["mult"], "pip": c["pip"],
                                            "label_en": c["label_en"], "label_ar": c["label_ar"],
                                            "yahoo": c["yahoo"], "spot_code": c["spot_code"],
                                            "metals_spot": c["metals_spot"]}
                                        for s, c in config.SYMBOLS.items()},
                            "tradeable_symbols": sorted(config.TRADEABLE_SYMBOLS),
                            "modes": config.TRADE_MODES, "strategies": config.ICT_STRATEGIES, "strategy_ar": config.STRATEGY_AR,
                            "anti_usd_symbols": list(config.ANTI_USD_SYMBOLS),
                            "pro_usd_symbols": list(config.PRO_USD_SYMBOLS),
                            "guardrail_threshold": config.BIAS_GUARDRAIL_THRESHOLD,
                            "news_blackout_before_min": config.NEWS_BLACKOUT_BEFORE_MIN,
                            "news_blackout_after_min": config.NEWS_BLACKOUT_AFTER_MIN})
                return

            if path == "/api/prices":
                self._json({"ok": True, "data": engine.get_prices_payload()}); return

            if path == "/api/market_status":
                self._json({"ok": True, "data": engine.compute_market_status()}); return

            if path == "/api/market_bias":
                bias = engine.compute_market_bias()
                symbol = qs.get("symbol", [None])[0]; side = qs.get("side", [None])[0]
                alignment = None
                if symbol in config.SYMBOLS and side in ("BUY", "SELL"):
                    alignment = engine.symbol_alignment(symbol, side.upper(), bias)
                self._json({"ok": True, "data": bias, "alignment": alignment}); return

            if path == "/api/autopilot":
                self._json({"ok": True, "data": engine.get_autopilot_payload()}); return

            if path == "/api/settings":
                r = engine.db_query_one("SELECT capital, risk_percent, updated_at FROM bot_settings WHERE id=1")
                if r is None:
                    self._json({"ok": False, "error": "settings missing"}, 500); return
                self._json({"ok": True, "data": {"capital": float(r["capital"]),
                                                 "risk_percent": float(r["risk_percent"]),
                                                 "updated_at": r["updated_at"]}}); return

            if path == "/api/trades":
                status_filter = qs.get("status", [None])[0]
                limit = int(qs.get("limit", ["200"])[0])
                if status_filter:
                    rows = engine.db_query("SELECT * FROM trades WHERE status=? ORDER BY id DESC LIMIT ?", (status_filter, limit))
                else:
                    rows = engine.db_query("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
                self._json({"ok": True, "count": len(rows), "data": [dict(r) for r in rows]}); return

            if path == "/api/strategies":
                rows = engine.db_query("SELECT name, total_trades, wins, losses FROM strategies ORDER BY CAST(wins AS REAL)/MAX(total_trades,1) DESC")
                out = []
                for r in rows:
                    t = int(r["total_trades"]); w = int(r["wins"]); l = int(r["losses"])
                    wr = (w / t * 100.0) if t > 0 else 0.0
                    out.append({"name": r["name"], "name_ar": config.STRATEGY_AR.get(r["name"], r["name"]),
                                "total_trades": t, "wins": w, "losses": l, "win_rate": round(wr, 2)})
                self._json({"ok": True, "data": out}); return

            if path == "/api/summary":
                self._json({"ok": True, "data": engine.get_summary_payload()}); return

            if path == "/api/macro":
                self._json({"ok": True, "data": engine.get_macro_payload()}); return

            if path == "/api/central_banks":
                self._json({"ok": True, "data": engine.get_cb_payload()}); return

            if path == "/api/cot":
                self._json({"ok": True, "data": engine.get_cot_payload()}); return

            if path == "/api/calendar":
                self._json({"ok": True, "data": engine.get_calendar_payload()}); return

            if path == "/api/self_learning":
                limit = int(qs.get("limit", ["50"])[0])
                rows = engine.db_query("SELECT id, trade_id, symbol, strategy, mode, lesson, created_at "
                                       "FROM self_learning ORDER BY id DESC LIMIT ?", (limit,))
                self._json({"ok": True, "count": len(rows), "data": [dict(r) for r in rows]}); return

            if path == "/api/confluence":
                symbol = qs.get("symbol", ["XAU/USD"])[0]
                side = qs.get("side", ["BUY"])[0].upper()
                mode = qs.get("mode", ["SCALPING_A"])[0]
                strategy = qs.get("strategy", [config.ICT_STRATEGIES[0]])[0]
                if symbol not in config.SYMBOLS: self._json({"ok": False, "error": "unknown symbol"}, 400); return
                if side not in ("BUY", "SELL"): self._json({"ok": False, "error": "side must be BUY/SELL"}, 400); return
                if mode not in config.TRADE_MODES: self._json({"ok": False, "error": "unknown mode"}, 400); return
                if strategy not in config.ICT_STRATEGIES: self._json({"ok": False, "error": "unknown strategy"}, 400); return
                self._json({"ok": True, "data": engine.compute_confluence(symbol, side, mode, strategy)}); return

            if path == "/api/feed_status":
                self._json({"ok": True, "data": engine.get_feed_status_payload()}); return

            self._json({"ok": False, "error": "not found", "path": path}, 404)
        except Exception as exc:
            traceback.print_exc()
            self._json({"ok": False, "error": str(exc)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            if path == "/api/autopilot":
                body = self._read_json()
                fields = []; params = []
                if "enabled" in body:
                    fields.append("autopilot_enabled=?"); params.append(1 if body["enabled"] else 0)
                if "min_score" in body:
                    v = max(0.0, min(10.0, float(body["min_score"])))
                    fields.append("autopilot_min_score=?"); params.append(v)
                if "max_concurrent" in body:
                    v = max(1, min(20, int(body["max_concurrent"])))
                    fields.append("autopilot_max_concurrent=?"); params.append(v)
                if "cooldown_sec" in body:
                    v = max(10, min(3600, int(body["cooldown_sec"])))
                    fields.append("autopilot_cooldown_sec=?"); params.append(v)
                if fields:
                    params.append(config.now_iso())
                    engine.db_exec(f"UPDATE bot_settings SET {', '.join(fields)}, updated_at=? WHERE id=1", tuple(params))
                    if "enabled" in body:
                        engine.ap_log("🟢 Auto-Pilot ENABLED" if body["enabled"] else "🔴 Auto-Pilot DISABLED")
                ap = engine.get_autopilot_settings()
                self._json({"ok": True, "data": {"enabled": ap["enabled"],
                                                 "config": {"min_score": ap["min_score"],
                                                            "max_concurrent": ap["max_concurrent"],
                                                            "cooldown_sec": ap["cooldown_sec"]}}})
                return

            if path == "/api/settings":
                body = self._read_json()
                cap = float(body.get("capital", 10000.0)); risk = float(body.get("risk_percent", 1.0))
                if cap <= 0: self._json({"ok": False, "error": "capital must be > 0"}, 400); return
                if risk <= 0 or risk > 100: self._json({"ok": False, "error": "risk_percent must be (0, 100]"}, 400); return
                engine.db_exec("UPDATE bot_settings SET capital=?, risk_percent=?, updated_at=? WHERE id=1",
                               (cap, risk, config.now_iso()))
                r = engine.db_query_one("SELECT capital, risk_percent, updated_at FROM bot_settings WHERE id=1")
                self._json({"ok": True, "data": {"capital": float(r["capital"]),
                                                 "risk_percent": float(r["risk_percent"]),
                                                 "updated_at": r["updated_at"]}})
                return

            if path == "/api/trades":
                body = self._read_json()
                symbol = body.get("symbol", "XAU/USD")
                side = str(body.get("side", "BUY")).upper()
                entry_type = str(body.get("entry_type", "MARKET")).upper()
                mode = body.get("mode", "SCALPING_A")
                strategy = body.get("strategy", config.ICT_STRATEGIES[0])
                entry_tf = body.get("entry_timeframe", "")
                force_override = bool(body.get("force", False))

                if symbol not in config.SYMBOLS: self._json({"ok": False, "error": f"unknown symbol {symbol}"}, 400); return
                if symbol not in config.TRADEABLE_SYMBOLS:
                    self._json({"ok": False,
                                "error": f"{symbol} is display-only — not tradeable (used only for bias calculation)"}, 400)
                    return
                if side not in ("BUY", "SELL"): self._json({"ok": False, "error": "side must be BUY/SELL"}, 400); return
                if entry_type not in ("MARKET", "LIMIT"): self._json({"ok": False, "error": "entry_type invalid"}, 400); return
                if mode not in config.TRADE_MODES: self._json({"ok": False, "error": f"unknown mode {mode}"}, 400); return
                if strategy not in config.ICT_STRATEGIES: self._json({"ok": False, "error": "unknown strategy"}, 400); return
                if not entry_tf: entry_tf = config.TRADE_MODES[mode]["entry_tfs"][0]
                if entry_tf not in config.TRADE_MODES[mode]["entry_tfs"]:
                    self._json({"ok": False, "error": f"entry tf {entry_tf} invalid"}, 400); return

                ms = engine.compute_market_status()
                if not ms["is_open"]:
                    if ms.get("news_blackout", {}).get("active"):
                        nb = ms["news_blackout"]
                        self._json({"ok": False,
                                    "error": f"News blackout active: {nb.get('event_en','')} ({nb.get('currency','')}) — resumes in {nb.get('resume_in_sec',0)//60} min",
                                    "market_status": ms}, 400)
                    else:
                        self._json({"ok": False, "error": "Market is closed — cannot open new trades",
                                    "market_status": ms}, 400)
                    return

                if not ms["liquidity"]["allow_trades"] and not force_override:
                    self._json({"ok": False,
                                "error": f"Liquidity is {ms['liquidity']['level']} — trade blocked.",
                                "market_status": ms}, 400)
                    return

                bias = engine.compute_market_bias()
                align = engine.symbol_alignment(symbol, side, bias)
                if align["blocked"] and not force_override:
                    self._json({"ok": False,
                                "error": f"Blocked by Bias Guardrail (score {bias['score']:+.1f}). Align with {align['with_trend_side']}.",
                                "bias": bias, "alignment": align, "market_status": ms}, 400)
                    return

                cfg = config.SYMBOLS[symbol]; dec = cfg["decimals"]
                live = engine.get_live_price(symbol)

                if entry_type == "MARKET":
                    entry = round(live, dec)
                else:
                    user_entry = body.get("entry_price")
                    if user_entry is None:
                        self._json({"ok": False, "error": "entry_price required for LIMIT"}, 400); return
                    entry = round(float(user_entry), dec)
                    if side == "BUY" and entry >= live:
                        self._json({"ok": False, "error": "BUY LIMIT entry must be below current"}, 400); return
                    if side == "SELL" and entry <= live:
                        self._json({"ok": False, "error": "SELL LIMIT entry must be above current"}, 400); return

                sl_user = body.get("stop_loss"); tp_user = body.get("take_profit")
                if sl_user is not None and tp_user is not None:
                    stop_loss = round(float(sl_user), dec); take_profit = round(float(tp_user), dec)
                else:
                    stop_loss, take_profit = engine.default_sl_tp(symbol, mode, side, entry)

                if side == "BUY" and not (stop_loss < entry < take_profit):
                    self._json({"ok": False, "error": "For BUY: SL < entry < TP required"}, 400); return
                if side == "SELL" and not (take_profit < entry < stop_loss):
                    self._json({"ok": False, "error": "For SELL: TP < entry < SL required"}, 400); return

                confluence = engine.compute_confluence(symbol, side, mode, strategy)
                if not confluence["approved"]:
                    self._json({"ok": False,
                                "error": f"Confluence {confluence['score']}/10 below threshold",
                                "confluence": confluence}, 400)
                    return

                s = engine.db_query_one("SELECT capital, risk_percent FROM bot_settings WHERE id=1")
                lot = engine.calculate_lot_size(float(s["capital"]), float(s["risk_percent"]),
                                                abs(entry - stop_loss), symbol)

                htf_str = ",".join(config.TRADE_MODES[mode]["htf"])
                status = "ACTIVE" if entry_type == "MARKET" else "PENDING"
                activated_at = config.now_iso() if status == "ACTIVE" else None

                new_id = engine.db_exec(
                    "INSERT INTO trades (symbol, side, entry_type, mode, htf_analysis, entry_timeframe, "
                    "entry_price, stop_loss, take_profit, lot_size, strategy, status, "
                    "confluence_score, confluence_bias, force_override, autopilot_origin, opened_at, activated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (symbol, side, entry_type, mode, htf_str, entry_tf,
                     entry, stop_loss, take_profit, lot, strategy, status,
                     confluence["score"], confluence["directional"],
                     1 if force_override else 0,
                     config.now_iso(), activated_at)
                )
                r = engine.db_query_one("SELECT * FROM trades WHERE id=?", (new_id,))
                self._json({"ok": True, "data": dict(r), "confluence": confluence,
                            "bias": bias, "alignment": align, "market_status": ms,
                            "forced": force_override})
                return

            if path == "/api/auto_dispatch":
                body = self._read_json()
                mode = body.get("mode") or random.choice(list(config.TRADE_MODES.keys()))
                if mode not in config.TRADE_MODES: mode = "SCALPING_A"

                ms = engine.compute_market_status()
                if not ms["is_open"]:
                    if ms.get("news_blackout", {}).get("active"):
                        self._json({"ok": False, "error": "News blackout active", "market_status": ms}, 400)
                    else:
                        self._json({"ok": False, "error": "Market is closed", "market_status": ms}, 400)
                    return
                if not ms["liquidity"]["allow_trades"]:
                    self._json({"ok": False, "error": f"Liquidity {ms['liquidity']['level']} — auto-dispatch blocked",
                                "market_status": ms}, 400); return

                bias = engine.compute_market_bias()
                setup = engine.find_best_autopilot_setup(bias, 5.0)
                if not setup:
                    self._json({"ok": False, "error": "No qualifying setup found at current confluence",
                                "bias": bias, "market_status": ms}, 400); return

                cfg = config.SYMBOLS[setup["symbol"]]; dec = cfg["decimals"]
                entry = round(engine.get_live_price(setup["symbol"]), dec)
                sl, tp = engine.default_sl_tp(setup["symbol"], setup["mode"], setup["side"], entry)
                s = engine.db_query_one("SELECT capital, risk_percent FROM bot_settings WHERE id=1")
                lot = engine.calculate_lot_size(float(s["capital"]), float(s["risk_percent"]),
                                                abs(entry - sl), setup["symbol"])
                htf_str = ",".join(config.TRADE_MODES[setup["mode"]]["htf"])
                entry_tf = config.TRADE_MODES[setup["mode"]]["entry_tfs"][0]
                new_id = engine.db_exec(
                    "INSERT INTO trades (symbol, side, entry_type, mode, htf_analysis, entry_timeframe, "
                    "entry_price, stop_loss, take_profit, lot_size, strategy, status, "
                    "confluence_score, confluence_bias, force_override, autopilot_origin, opened_at, activated_at) "
                    "VALUES (?, ?, 'MARKET', ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, 0, 0, ?, ?)",
                    (setup["symbol"], setup["side"], setup["mode"], htf_str, entry_tf,
                     entry, sl, tp, lot, setup["strategy"],
                     setup["confluence"]["score"], setup["confluence"]["directional"],
                     config.now_iso(), config.now_iso()))
                r = engine.db_query_one("SELECT * FROM trades WHERE id=?", (new_id,))
                self._json({"ok": True, "auto": True, "data": dict(r),
                            "confluence": setup["confluence"], "bias": bias, "market_status": ms})
                return

            if path.startswith("/api/trades/") and path.endswith("/cancel"):
                parts = path.split("/")
                try: tid = int(parts[3])
                except (IndexError, ValueError): self._json({"ok": False, "error": "invalid trade id"}, 400); return
                row = engine.db_query_one("SELECT status FROM trades WHERE id=?", (tid,))
                if row is None: self._json({"ok": False, "error": "trade not found"}, 404); return
                if row["status"] != "PENDING": self._json({"ok": False, "error": "only PENDING can be cancelled"}, 400); return
                engine.db_exec("UPDATE trades SET status='CANCELLED', closed_at=? WHERE id=?", (config.now_iso(), tid))
                self._json({"ok": True, "message": f"Trade #{tid} cancelled"}); return

            if path.startswith("/api/trades/") and path.endswith("/close"):
                parts = path.split("/")
                try: tid = int(parts[3])
                except (IndexError, ValueError): self._json({"ok": False, "error": "invalid trade id"}, 400); return
                row = engine.db_query_one("SELECT * FROM trades WHERE id=?", (tid,))
                if row is None: self._json({"ok": False, "error": "trade not found"}, 404); return
                if row["status"] != "ACTIVE": self._json({"ok": False, "error": "only ACTIVE can be closed"}, 400); return
                sym = row["symbol"]
                current = engine.get_live_price(sym)
                entry = float(row["entry_price"]); side = row["side"]; lot = float(row["lot_size"])
                mult = config.SYMBOLS[sym]["mult"]
                diff = (current - entry) if side == "BUY" else (entry - current)
                pnl = round(diff * mult * lot, 2)
                outcome = "WIN" if pnl >= 0 else "LOSS"
                engine.db_exec("UPDATE trades SET status=?, pnl=?, exit_price=?, closed_at=? WHERE id=?",
                               (outcome, pnl, round(current, config.SYMBOLS[sym]["decimals"]), config.now_iso(), tid))
                if outcome == "WIN":
                    engine.db_exec("UPDATE strategies SET total_trades=total_trades+1, wins=wins+1 WHERE name=?", (row["strategy"],))
                else:
                    engine.db_exec("UPDATE strategies SET total_trades=total_trades+1, losses=losses+1 WHERE name=?", (row["strategy"],))
                    lesson = engine.generate_lesson(row, current)
                    engine.db_exec("INSERT INTO self_learning (trade_id, symbol, strategy, mode, lesson, created_at) VALUES (?,?,?,?,?,?)",
                                   (tid, sym, row["strategy"], row["mode"], lesson, config.now_iso()))
                self._json({"ok": True, "message": f"Trade #{tid} closed ({outcome})", "pnl": pnl}); return

            if path == "/api/self_learning/reset":
                engine.db_exec("DELETE FROM self_learning")
                self._json({"ok": True, "message": "self_learning cleared"}); return

            if path == "/api/reset_all":
                engine.db_exec("DELETE FROM trades")
                engine.db_exec("DELETE FROM self_learning")
                engine.db_exec("UPDATE strategies SET total_trades=0, wins=0, losses=0")
                self._json({"ok": True, "message": "all reset"}); return

            self._json({"ok": False, "error": "not found", "path": path}, 404)
        except ValueError as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            traceback.print_exc()
            self._json({"ok": False, "error": str(exc)}, 500)


# ============================================================================
# FRONTEND (v7.2 — 20 ICT strategies)
# ============================================================================
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Pro Trading &amp; Macro Intelligence Engine v7.2</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
  html, body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: radial-gradient(1500px 750px at 12% -12%, #0b1b3d 0%, #05091a 42%, #020308 100%); }
  html[dir="rtl"] body { font-family: 'Cairo', 'Inter', sans-serif; }
  html[dir="rtl"] table { direction: rtl; }
  .tabnum { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }
  .card { background: linear-gradient(180deg, rgba(15,23,42,0.88) 0%, rgba(2,6,23,0.84) 100%);
    border: 1px solid rgba(59,130,246,0.14); box-shadow: 0 8px 32px -8px rgba(0,0,0,0.55);
    transition: border-color .2s ease, transform .2s ease; }
  .card:hover { border-color: rgba(59,130,246,0.32); }
  .flash-up { animation: flashUp .55s ease-out; }
  .flash-down { animation: flashDown .55s ease-out; }
  @keyframes flashUp { from { background-color: rgba(16,185,129,0.32); } to { background-color: transparent; } }
  @keyframes flashDown { from { background-color: rgba(244,63,94,0.32); } to { background-color: transparent; } }
  .pulse-dot { position: relative; display: inline-block; }
  .pulse-dot::before { content: ''; position: absolute; inset: -4px; border-radius: 9999px;
    background: currentColor; opacity: .4; animation: pulseRing 1.8s ease-out infinite; }
  @keyframes pulseRing { 0% { transform: scale(.55); opacity: .6; } 100% { transform: scale(2.2); opacity: 0; } }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-track { background: #0b1220; }
  ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 8px; }
  .glow-blue { box-shadow: 0 0 26px -6px rgba(56,189,248,0.70); }
  .stripe-row:nth-child(odd) { background: rgba(15,23,42,0.35); }
  .stripe-row:hover { background: rgba(30,64,175,0.14); }
  select, input { outline: none; }
  select:focus, input:focus { border-color: #38bdf8 !important; box-shadow: 0 0 0 2px rgba(56,189,248,0.22); }
  .btn-primary { background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%); transition: transform .15s, filter .15s; }
  .btn-primary:hover { filter: brightness(1.10); transform: translateY(-1px); }
  .btn-success { background: linear-gradient(135deg, #10b981 0%, #059669 100%); transition: transform .15s, filter .15s; }
  .btn-success:hover { filter: brightness(1.10); transform: translateY(-1px); }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 10px; font-weight: 700; letter-spacing: .03em; }
  .scroll-area { max-height: 480px; overflow-y: auto; }
  .feed-live { color: #34d399; }
  .feed-stale { color: #fbbf24; }
  .score-ring { background: conic-gradient(#10b981 var(--p), #1e293b 0); border-radius: 9999px; transition: background .35s ease; }
  .reason-pass { border-left: 3px solid #10b981; }
  .reason-fail { border-left: 3px solid #64748b; }
  html[dir="rtl"] .reason-pass { border-left: none; border-right: 3px solid #10b981; }
  html[dir="rtl"] .reason-fail { border-left: none; border-right: 3px solid #64748b; }
  .footer-tile { background: linear-gradient(180deg, rgba(15,23,42,0.92) 0%, rgba(2,6,23,0.88) 100%);
    border: 1px solid rgba(59,130,246,0.12); transition: border-color .2s ease; }
  .footer-tile:hover { border-color: rgba(59,130,246,0.28); }
  #biasMarker { transition: left 0.55s cubic-bezier(0.4, 0, 0.2, 1); }
  .bias-pulse-strong { animation: biasPulse 2s ease-in-out infinite; }
  @keyframes biasPulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.55); } 50% { box-shadow: 0 0 0 12px rgba(239,68,68,0); } }
  .ap-pulse { animation: apPulse 1.5s ease-in-out infinite; }
  @keyframes apPulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }
  .market-closed-banner { background: linear-gradient(135deg, rgba(127,29,29,0.85) 0%, rgba(153,27,27,0.75) 100%);
    border: 1px solid rgba(239,68,68,0.5); animation: closedPulse 3s ease-in-out infinite; }
  @keyframes closedPulse { 0%, 100% { box-shadow: 0 0 20px -8px rgba(239,68,68,0.3); }
    50% { box-shadow: 0 0 40px -8px rgba(239,68,68,0.7); } }
  .news-banner { background: linear-gradient(135deg, rgba(154,52,18,0.85) 0%, rgba(180,83,9,0.75) 100%);
    border: 1px solid rgba(251,146,60,0.6); animation: newsPulse 2.4s ease-in-out infinite; }
  @keyframes newsPulse { 0%, 100% { box-shadow: 0 0 20px -8px rgba(251,146,60,0.4); }
    50% { box-shadow: 0 0 40px -8px rgba(251,146,60,0.8); } }
</style>
</head>
<body class="text-slate-200 min-h-screen">

<div id="paperBanner" data-i18n="paper_sim_badge"
     class="sticky top-0 z-50 h-8 flex items-center justify-center bg-amber-400 text-slate-950 text-[11px] sm:text-xs font-extrabold tracking-wide px-2 border-b border-amber-600/60">
  PAPER SIMULATION — NO LIVE ORDERS
</div>

<header class="sticky top-8 z-40 backdrop-blur-xl bg-slate-950/78 border-b border-blue-500/15">
  <div class="max-w-[1750px] mx-auto px-4 py-3 flex flex-wrap items-center gap-3 justify-between">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-sky-400 via-blue-600 to-indigo-700 flex items-center justify-center font-black text-lg shadow-lg glow-blue">P</div>
      <div>
        <div class="text-[15px] font-bold tracking-tight text-white" data-i18n="app_title">Pro Trading &amp; Macro Intelligence</div>
        <div class="text-[10px] uppercase tracking-[0.22em] text-slate-500" data-i18n="app_subtitle">Institutional ICT Engine · v7.2</div>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <button id="btnLang" class="px-3 py-1.5 rounded-full border border-sky-500/40 bg-sky-950/60 text-sky-300 font-bold hover:bg-sky-900/70 transition">🌐 English</button>
      <div id="liqChip" class="flex items-center gap-2 bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span id="liqDot" class="w-2 h-2 rounded-full bg-slate-500"></span>
        <span id="liqText" class="text-slate-400 font-semibold" data-i18n="liq_unknown">—</span>
      </div>
      <div class="flex items-center gap-2 bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span id="feedDot" class="text-emerald-400 pulse-dot w-2 h-2 rounded-full bg-emerald-400"></span>
        <span id="feedStatus" class="text-emerald-300 font-semibold" data-i18n="live">LIVE</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span data-i18n="session">Session</span>: <b id="sessionLabel" class="text-sky-300">—</b>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span data-i18n="capital">Capital</span>: <b id="topCapital" class="text-emerald-300 tabnum">$0</b>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span data-i18n="win_rate">Win Rate</span>: <b id="topWinRate" class="text-amber-300 tabnum">0%</b>
      </div>
    </div>
  </div>
</header>

<div id="marketBanner" class="max-w-[1750px] mx-auto px-4 mt-4 hidden">
  <div id="marketBannerInner" class="rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
    <div class="flex items-center gap-3">
      <span id="msIcon" class="text-3xl">🟢</span>
      <div>
        <div id="msTitle" class="text-base font-bold text-white">Market Open</div>
        <div id="msSubtitle" class="text-xs text-slate-300">High Liquidity — London Session</div>
      </div>
    </div>
    <div id="msCountdownBox" class="hidden text-right">
      <div id="msCountdownLabel" class="text-[10px] uppercase tracking-widest text-slate-300" data-i18n="reopens_in">Reopens in</div>
      <div id="msCountdown" class="text-2xl font-black font-mono tabnum text-white">00:00:00</div>
    </div>
  </div>
</div>

<main class="max-w-[1750px] mx-auto px-4 py-6 space-y-6">

  <section>
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-xs font-bold uppercase tracking-[0.22em] text-slate-400" data-i18n="live_market_feed">Live Market Feed</h2>
      <div class="text-[10px] text-slate-500" data-i18n="feed_sub">Real spot feed (gold-api.com) + Yahoo Finance · 1-second refresh</div>
    </div>
    <div id="priceGrid" class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3"></div>
  </section>

  <section class="card rounded-xl p-5">
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex items-center gap-2">
        <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-amber-400" data-i18n="market_bias_title">Market Bias Index</h3>
        <span class="text-[9px] text-slate-500" data-i18n="market_bias_subtitle">DXY · US10Y · COT · GSR</span>
      </div>
      <span id="biasGuardrailBadge" class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-800 text-slate-400" data-i18n="bias_guardrail_off">GUARDRAIL: OFF</span>
    </div>
    <div class="flex flex-wrap items-center gap-4 mb-4">
      <div class="flex flex-col items-center">
        <div id="biasScoreDisplay" class="text-4xl font-black tabnum text-slate-300">0.0</div>
        <div id="biasLabelDisplay" class="text-[11px] font-bold text-slate-400 mt-1 text-center">Neutral</div>
      </div>
      <div class="flex-1 min-w-[240px]">
        <div class="relative h-4 rounded-full overflow-hidden bg-slate-900">
          <div class="absolute inset-0 flex">
            <div class="flex-1 bg-gradient-to-r from-emerald-600 to-emerald-500/60"></div>
            <div class="flex-1 bg-gradient-to-r from-emerald-500/60 to-slate-700"></div>
            <div class="flex-1 bg-gradient-to-r from-slate-700 to-rose-500/60"></div>
            <div class="flex-1 bg-gradient-to-r from-rose-500/60 to-rose-600"></div>
          </div>
          <div id="biasMarker" class="absolute top-0 bottom-0 w-1 bg-white shadow-[0_0_8px_rgba(255,255,255,0.9)]" style="left:50%;transform:translateX(-50%)"></div>
        </div>
        <div class="flex justify-between text-[9px] text-slate-500 mt-1 tabnum">
          <span>-100</span><span>-60</span><span>0</span><span>+60</span><span>+100</span>
        </div>
        <div id="biasDirectionDisplay" class="text-[10px] text-slate-500 text-center mt-1">USD Neutral</div>
      </div>
      <div class="flex flex-col items-end text-right">
        <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="bias_with_trend_hint">With-Trend Assets</div>
        <div id="biasWithTrendDisplay" class="text-[11px] font-semibold text-sky-300 mt-1">—</div>
      </div>
    </div>
    <div id="biasComponentsGrid" class="grid grid-cols-2 md:grid-cols-4 gap-2"></div>
  </section>

  <section class="grid grid-cols-1 xl:grid-cols-3 gap-4">
    <div class="card rounded-xl p-5">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-sky-400 mb-4" data-i18n="account_risk">Account &amp; Risk Control</h3>
      <div class="space-y-4">
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="capital_usd">Capital (USD)</label>
          <input id="inpCapital" type="number" step="0.01" min="1" value="10000" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white tabnum" />
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="risk_per_trade">Risk per Trade (%)</label>
          <input id="inpRisk" type="number" step="0.05" min="0.01" max="100" value="1" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white tabnum" />
        </div>
        <button id="btnSaveSettings" class="btn-primary w-full text-white font-semibold rounded-lg py-2" data-i18n="save_permanently">Save Permanently</button>
        <div id="settingsStatus" class="text-[11px] h-4"></div>
        <div class="pt-3 border-t border-slate-800 grid grid-cols-2 gap-y-1.5 text-[11px]">
          <div class="text-slate-500" data-i18n="risk_usd">Risk $/trade</div><div class="text-right text-white tabnum" id="riskUsd">—</div>
          <div class="text-slate-500" data-i18n="total_trades">Total trades</div><div class="text-right text-white tabnum" id="statTotal">—</div>
          <div class="text-slate-500" data-i18n="active_pos">Active</div><div class="text-right text-emerald-300 tabnum" id="statActive">—</div>
          <div class="text-slate-500" data-i18n="pending_orders">Pending</div><div class="text-right text-amber-300 tabnum" id="statPending">—</div>
          <div class="text-slate-500" data-i18n="realized_pnl">Realized P&amp;L</div><div class="text-right tabnum" id="statPnl">—</div>
        </div>
      </div>
    </div>

    <div class="card rounded-xl p-5 xl:col-span-2">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-sky-400 mb-4" data-i18n="trade_console">Trade Console — Multi-Timeframe Execution</h3>
      <div class="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="trading_mode">Trading Mode</label>
          <select id="selTradingMode" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white">
            <option value="manual" data-i18n="mode_manual">Manual Mode</option>
            <option value="single_click" data-i18n="mode_single_click">Single-Click Mode</option>
          </select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="auto_pilot_label">Auto-Pilot</label>
          <label class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white flex items-center gap-2 cursor-pointer hover:border-emerald-500/50 transition">
            <input type="checkbox" id="chkAutopilot" class="accent-emerald-500 w-4 h-4" />
            <span class="text-sm" data-i18n="auto_pilot_enable">Enable Continuous Auto-Pilot</span>
            <span id="apDot" class="ml-auto w-2 h-2 rounded-full bg-slate-500"></span>
          </label>
        </div>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
        <div><label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="symbol">Symbol</label>
          <select id="selSymbol" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select></div>
        <div><label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="side">Side</label>
          <select id="selSide" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white">
            <option value="BUY" data-i18n="buy">BUY</option>
            <option value="SELL" data-i18n="sell">SELL</option>
          </select></div>
        <div><label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="entry_type">Entry Type</label>
          <select id="selEntryType" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white">
            <option value="MARKET" data-i18n="market">MARKET</option>
            <option value="LIMIT" data-i18n="limit">LIMIT</option>
          </select></div>
        <div><label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="trade_mode">Trade Mode</label>
          <select id="selMode" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select></div>
        <div><label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="entry_tf">Entry Timeframe</label>
          <select id="selEntryTF" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select></div>
        <div><label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="ict_strategy">ICT Strategy</label>
          <select id="selStrategy" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select></div>
      </div>
      <div class="mt-3 grid grid-cols-3 gap-3">
        <div><label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="entry_price">Entry Price</label>
          <input id="inpEntry" type="number" step="any" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white tabnum" /></div>
        <div><label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="stop_loss">Stop Loss</label>
          <input id="inpSL" type="number" step="any" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-rose-300 tabnum" /></div>
        <div><label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="take_profit">Take Profit</label>
          <input id="inpTP" type="number" step="any" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-emerald-300 tabnum" /></div>
      </div>
      <div class="mt-3 grid grid-cols-2 gap-3">
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg px-3 py-2">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="htf_analysis">HTF Analysis</div>
          <div id="htfDisplay" class="text-sky-300 font-semibold text-sm tabnum">1W · 1D · 1H</div>
        </div>
        <div class="bg-slate-950/70 border border-sky-500/30 rounded-lg px-3 py-2">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="lot_size">Calculated Lot Size</div>
          <div id="lotDisplay" class="text-emerald-300 font-bold text-lg tabnum">0.00</div>
        </div>
      </div>
      <div id="guardrailBanner" class="hidden mt-3 bg-rose-950/60 border border-rose-700/60 rounded-lg p-3">
        <div class="flex items-start gap-2">
          <span class="text-rose-400 text-lg leading-none">⚠</span>
          <div class="flex-1">
            <div class="text-[11px] font-bold text-rose-200 mb-1" data-i18n="trade_blocked">Trade Blocked</div>
            <div id="guardrailText" class="text-[11px] text-rose-200/90 leading-relaxed"></div>
            <button id="btnForceOverride" class="hidden mt-2 text-[10px] bg-rose-700/60 hover:bg-rose-600 px-3 py-1 rounded font-semibold text-white" data-i18n="force_override">Force Override (Not Recommended)</button>
          </div>
        </div>
      </div>
      <div class="flex flex-wrap gap-2 mt-4">
        <button id="btnDispatch" class="btn-success flex-1 min-w-[180px] text-white font-semibold rounded-lg py-2.5" data-i18n="dispatch_trade">⚡ Dispatch Trade</button>
        <button id="btnAutoDispatch" class="btn-primary flex-1 min-w-[180px] text-white font-semibold rounded-lg py-2.5" data-i18n="auto_dispatch">🎲 Smart Scan (One Trade)</button>
      </div>
      <div id="dispatchStatus" class="text-[11px] mt-2 h-4"></div>
    </div>
  </section>

  <section id="autopilotPanel" class="card rounded-xl p-5 hidden">
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div class="flex items-center gap-2">
        <span class="text-2xl">🤖</span>
        <div>
          <h3 class="text-sm font-bold text-emerald-400" data-i18n="autopilot_status_title">Auto-Pilot Running</h3>
          <div class="text-[10px] text-slate-500" data-i18n="autopilot_status_subtitle">Background engine scanning for setups</div>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <span id="apStatusChip" class="text-[10px] font-bold px-2 py-1 rounded-full bg-emerald-950/70 text-emerald-300 border border-emerald-700/50">● Scanning</span>
        <button id="btnDisableAp" class="text-[10px] bg-rose-900/60 hover:bg-rose-800/80 px-3 py-1 rounded font-semibold text-white" data-i18n="disable_ap">Disable</button>
      </div>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
      <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
        <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="ap_min_score">Min Score</div>
        <input id="apMinScore" type="number" step="0.5" min="5" max="10" value="6" class="w-full mt-1 bg-slate-900/70 border border-slate-700 rounded px-2 py-1 text-white tabnum text-sm" />
      </div>
      <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
        <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="ap_max_concurrent">Max Concurrent</div>
        <input id="apMaxConcurrent" type="number" step="1" min="1" max="20" value="3" class="w-full mt-1 bg-slate-900/70 border border-slate-700 rounded px-2 py-1 text-white tabnum text-sm" />
      </div>
      <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
        <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="ap_cooldown">Cooldown (s)</div>
        <input id="apCooldown" type="number" step="5" min="10" max="3600" value="60" class="w-full mt-1 bg-slate-900/70 border border-slate-700 rounded px-2 py-1 text-white tabnum text-sm" />
      </div>
      <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3 flex flex-col justify-center">
        <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="ap_active_trades">Active Trades</div>
        <div id="apActiveCount" class="text-2xl font-bold text-emerald-300 tabnum">0</div>
      </div>
    </div>
    <button id="btnSaveApConfig" class="w-full bg-sky-600 hover:bg-sky-500 text-white font-semibold rounded-lg py-1.5 text-sm transition mb-3" data-i18n="ap_save_config">Save Auto-Pilot Config</button>
    <div class="text-[10px] uppercase tracking-widest text-slate-500 mb-1" data-i18n="ap_log_title">Activity Log</div>
    <div id="apLog" class="scroll-area bg-slate-950/60 border border-slate-800 rounded-lg p-2 text-[11px] font-mono space-y-1" style="max-height:220px"></div>
  </section>

  <section class="card rounded-xl p-5">
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-fuchsia-400" data-i18n="confluence_analysis">Technical × Macro Confluence Engine</h3>
      <div class="text-[10px] text-slate-500" data-i18n="confluence_sub">ICT structure + Macro regime + COT + Timing</div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4 items-center">
      <div class="flex flex-col items-center justify-center">
        <div id="confluenceRing" class="score-ring w-24 h-24 flex items-center justify-center" style="--p:0%">
          <div class="w-20 h-20 rounded-full bg-slate-950 flex flex-col items-center justify-center">
            <div id="confluenceScore" class="text-2xl font-black text-white tabnum">0</div>
            <div class="text-[9px] text-slate-500">/ 10</div>
          </div>
        </div>
        <div id="confluenceVerdict" class="text-[11px] mt-2 font-bold text-slate-400">—</div>
      </div>
      <div class="md:col-span-3">
        <div id="confluenceHeadline" class="text-sm text-slate-200 mb-3">—</div>
        <div id="confluenceReasons" class="grid grid-cols-1 md:grid-cols-2 gap-1.5 max-h-[260px] overflow-y-auto pr-1"></div>
      </div>
    </div>
  </section>

  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-emerald-400" data-i18n="active_positions">Active Positions</h3>
      <span id="activeCount" class="text-[11px] text-slate-500">0</span>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider">
          <tr>
            <th class="text-left px-3 py-2" data-i18n="id">ID</th>
            <th class="text-left px-3 py-2" data-i18n="symbol">Symbol</th>
            <th class="text-left px-3 py-2" data-i18n="side">Side</th>
            <th class="text-left px-3 py-2" data-i18n="mode">Mode</th>
            <th class="text-right px-3 py-2" data-i18n="entry_price">Entry</th>
            <th class="text-right px-3 py-2" data-i18n="stop_loss">SL</th>
            <th class="text-right px-3 py-2" data-i18n="take_profit">TP</th>
            <th class="text-right px-3 py-2" data-i18n="lot_size">Lot</th>
            <th class="text-right px-3 py-2" data-i18n="confluence">Confluence</th>
            <th class="text-left px-3 py-2" data-i18n="strategy_col">Strategy</th>
            <th class="text-center px-3 py-2" data-i18n="action">Action</th>
          </tr>
        </thead>
        <tbody id="tblActive"></tbody>
      </table>
    </div>
  </section>

  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-amber-400" data-i18n="pending_limit_orders">Pending Limit Orders</h3>
      <span id="pendingCountLabel" class="text-[11px] text-slate-500">0</span>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider">
          <tr>
            <th class="text-left px-3 py-2" data-i18n="id">ID</th>
            <th class="text-left px-3 py-2" data-i18n="symbol">Symbol</th>
            <th class="text-left px-3 py-2" data-i18n="side">Side</th>
            <th class="text-right px-3 py-2" data-i18n="limit_entry">Limit</th>
            <th class="text-right px-3 py-2" data-i18n="stop_loss">SL</th>
            <th class="text-right px-3 py-2" data-i18n="take_profit">TP</th>
            <th class="text-right px-3 py-2" data-i18n="lot_size">Lot</th>
            <th class="text-left px-3 py-2" data-i18n="strategy_col">Strategy</th>
            <th class="text-center px-3 py-2" data-i18n="action">Action</th>
          </tr>
        </thead>
        <tbody id="tblPending"></tbody>
      </table>
    </div>
  </section>

  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-slate-300" data-i18n="trade_history">Trade History</h3>
      <span class="text-[11px] text-slate-500" data-i18n="last_50">last 50 closed</span>
    </div>
    <div class="overflow-x-auto scroll-area">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider sticky top-0">
          <tr>
            <th class="text-left px-3 py-2" data-i18n="id">ID</th>
            <th class="text-left px-3 py-2" data-i18n="symbol">Symbol</th>
            <th class="text-left px-3 py-2" data-i18n="side">Side</th>
            <th class="text-left px-3 py-2" data-i18n="mode">Mode</th>
            <th class="text-right px-3 py-2" data-i18n="entry_price">Entry</th>
            <th class="text-right px-3 py-2" data-i18n="exit">Exit</th>
            <th class="text-right px-3 py-2" data-i18n="lot_size">Lot</th>
            <th class="text-left px-3 py-2" data-i18n="strategy_col">Strategy</th>
            <th class="text-left px-3 py-2" data-i18n="status">Status</th>
            <th class="text-right px-3 py-2" data-i18n="pnl">P&amp;L</th>
            <th class="text-left px-3 py-2" data-i18n="closed">Closed</th>
          </tr>
        </thead>
        <tbody id="tblHistory"></tbody>
      </table>
    </div>
  </section>

  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2">
      <h3 class="text-sm font-bold uppercase tracking-[0.22em] text-indigo-400" data-i18n="macro_geopolitics">Macro &amp; Geopolitics Intelligence</h3>
      <div class="flex items-center gap-2 text-[10px] text-slate-500">
        <span class="w-2 h-2 rounded-full bg-indigo-500 animate-pulse"></span>
        <span data-i18n="macro_live_note">Live · Yahoo Finance + FuturesBench COT</span>
      </div>
    </div>
    <div class="p-5 space-y-5">
      <div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">VIX</div>
          <div id="macroVix" class="text-xl font-bold text-rose-300 tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="us10y">US 10Y</div>
          <div id="macro10y" class="text-xl font-bold text-amber-300 tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">DXY</div>
          <div id="macroDxy" class="text-xl font-bold text-sky-300 tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="gsr">Gold / Silver</div>
          <div id="macroGsr" class="text-xl font-bold text-amber-200 tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="dxy_flow">DXY Flow</div>
          <div id="macroFlow" class="text-xl font-bold tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="geopolitical_risk">Geo Risk</div>
          <div id="macroGeo" class="text-xl font-bold text-fuchsia-300 tabnum mt-1">—</div>
        </div>
      </div>
      <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div class="bg-slate-950/50 border border-slate-800 rounded-lg overflow-hidden">
          <div class="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
            <h4 class="text-[11px] font-bold uppercase tracking-widest text-teal-400" data-i18n="cot_positioning">COT Positioning</h4>
            <span class="text-[9px] text-slate-500" id="cotSource">—</span>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="text-left px-3 py-2" data-i18n="asset">Asset</th>
                  <th class="text-right px-3 py-2" data-i18n="long">Long</th>
                  <th class="text-right px-3 py-2" data-i18n="short">Short</th>
                  <th class="text-right px-3 py-2" data-i18n="net">Net</th>
                  <th class="text-right px-3 py-2" data-i18n="delta_net">Δ Net</th>
                </tr>
              </thead>
              <tbody id="tblCot"></tbody>
            </table>
          </div>
        </div>
        <div class="bg-slate-950/50 border border-slate-800 rounded-lg overflow-hidden">
          <div class="px-4 py-3 border-b border-slate-800">
            <h4 class="text-[11px] font-bold uppercase tracking-widest text-purple-400" data-i18n="central_bank_probabilities">Central Bank Rates</h4>
          </div>
          <div id="cbGrid" class="grid grid-cols-1 md:grid-cols-2 gap-3 p-3"></div>
        </div>
      </div>
      <div class="bg-slate-950/50 border border-slate-800 rounded-lg overflow-hidden">
        <div class="px-4 py-3 border-b border-slate-800">
          <h4 class="text-[11px] font-bold uppercase tracking-widest text-orange-400" data-i18n="economic_calendar">Economic Calendar</h4>
        </div>
        <div class="overflow-x-auto scroll-area">
          <table class="w-full text-xs">
            <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider sticky top-0">
              <tr>
                <th class="text-left px-3 py-2" data-i18n="event">Event</th>
                <th class="text-left px-3 py-2" data-i18n="currency">Currency</th>
                <th class="text-left px-3 py-2" data-i18n="impact">Impact</th>
                <th class="text-left px-3 py-2" data-i18n="when">When</th>
                <th class="text-right px-3 py-2" data-i18n="forecast">Forecast</th>
                <th class="text-right px-3 py-2" data-i18n="previous">Previous</th>
              </tr>
            </thead>
            <tbody id="tblCalendar"></tbody>
          </table>
        </div>
      </div>
    </div>
  </section>

  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-fuchsia-400" data-i18n="ict_win_rates">ICT Strategy Win Rates (20)</h3>
    </div>
    <div class="overflow-x-auto scroll-area">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider sticky top-0">
          <tr>
            <th class="text-left px-3 py-2" data-i18n="strategy_col">Strategy</th>
            <th class="text-right px-3 py-2" data-i18n="total">Total</th>
            <th class="text-right px-3 py-2" data-i18n="wins">Wins</th>
            <th class="text-right px-3 py-2" data-i18n="losses">Losses</th>
            <th class="text-right px-3 py-2" data-i18n="win_rate">Win Rate</th>
          </tr>
        </thead>
        <tbody id="tblStrategies"></tbody>
      </table>
    </div>
  </section>

  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-amber-400" data-i18n="ai_self_learning">AI Self-Learning Journal</h3>
      <button id="btnClearLearn" class="text-[11px] text-slate-500 hover:text-rose-400 transition" data-i18n="clear_all">Clear all</button>
    </div>
    <div id="learnList" class="divide-y divide-slate-800 scroll-area"></div>
  </section>

</main>

<footer class="mt-10 border-t border-slate-800 bg-gradient-to-b from-slate-950/85 to-black/60">
  <div class="max-w-[1750px] mx-auto px-4 py-8 grid grid-cols-1 md:grid-cols-3 gap-4">
    <div class="footer-tile rounded-xl p-5">
      <div class="flex items-center gap-2 mb-3">
        <span class="text-xl">ℹ️</span>
        <h4 class="text-[11px] font-bold text-sky-400 uppercase tracking-[0.22em]" data-i18n="footer_about_title">About Engine</h4>
      </div>
      <p class="text-[12px] text-slate-400 leading-relaxed" data-i18n="footer_about_text">Institutional ICT analysis with real spot feed, 3 trading modes, live Session Liquidity filter, Market Closed countdown, High-impact News Blackout, Market Bias Index, COT positioning, AI self-learning, and 20 ICT/SMC strategies. DXY is display-only.</p>
    </div>
    <div class="footer-tile rounded-xl p-5">
      <div class="flex items-center gap-2 mb-3">
        <span class="text-xl">👨‍💻</span>
        <h4 class="text-[11px] font-bold text-fuchsia-400 uppercase tracking-[0.22em]" data-i18n="footer_dev_title">Developer</h4>
      </div>
      <div class="text-emerald-300 font-bold text-base mb-1" data-i18n="footer_dev_name">Built by Eng. Abdulelah Sadeq</div>
      <div class="text-[11px] text-slate-500 leading-relaxed" data-i18n="footer_dev_role">Quantitative FinTech &amp; Algorithmic Trading Systems Architect</div>
      <div class="mt-4 pt-3 border-t border-slate-800/60 text-[10px] text-slate-600" data-i18n="footer_dev_stack">Stack: Python stdlib · SQLite · Tailwind CSS · Vanilla JS</div>
    </div>
    <div class="footer-tile rounded-xl p-5">
      <div class="flex items-center gap-2 mb-3">
        <span class="text-xl">📖</span>
        <h4 class="text-[11px] font-bold text-amber-400 uppercase tracking-[0.22em]" data-i18n="footer_guide_title">User Guide</h4>
      </div>
      <ul class="text-[12px] text-slate-400 space-y-2">
        <li class="flex gap-2"><span class="text-sky-400 font-bold shrink-0">1.</span><span data-i18n="footer_guide_1">Set Capital and Risk% — saved permanently to SQLite.</span></li>
        <li class="flex gap-2"><span class="text-sky-400 font-bold shrink-0">2.</span><span data-i18n="footer_guide_2">Choose Manual/Single-Click mode or enable Auto-Pilot.</span></li>
        <li class="flex gap-2"><span class="text-sky-400 font-bold shrink-0">3.</span><span data-i18n="footer_guide_3">Trades are blocked on market close, weak liquidity, or high-impact news.</span></li>
        <li class="flex gap-2"><span class="text-sky-400 font-bold shrink-0">4.</span><span data-i18n="footer_guide_4">DXY is display-only (used for bias) — cannot be traded.</span></li>
        <li class="flex gap-2"><span class="text-sky-400 font-bold shrink-0">5.</span><span data-i18n="footer_guide_5">20 ICT/SMC strategies available — Silver Bullet is time-window only.</span></li>
      </ul>
    </div>
  </div>
  <div class="border-t border-slate-800/60 py-3">
    <div class="max-w-[1750px] mx-auto px-4 text-center text-[10px] text-slate-600">
      <span data-i18n="footer_copyright">All rights reserved</span> · <span data-i18n="app_title">Pro Trading &amp; Macro Intelligence Engine</span> · © <span id="year">2024</span>
    </div>
  </div>
</footer>

<script>
const I18N = {
  en: {
    paper_sim_badge: "PAPER SIMULATION — NO LIVE ORDERS",
    app_title: "Pro Trading & Macro Intelligence", app_subtitle: "Institutional ICT Engine · v7.2",
    live: "LIVE", stale: "FALLBACK", session: "Session", capital: "Capital", win_rate: "Win Rate",
    active: "ACTIVE", inactive: "INACTIVE",
    live_market_feed: "Live Market Feed", feed_sub: "Real spot feed (gold-api.com) + Yahoo Finance · 1-second refresh",
    account_risk: "Account & Risk Control", capital_usd: "Capital (USD)", risk_per_trade: "Risk per Trade (%)",
    save_permanently: "Save Permanently", risk_usd: "Risk $/trade", total_trades: "Total trades",
    active_pos: "Active", pending_orders: "Pending", realized_pnl: "Realized P&L",
    trade_console: "Trade Console — Multi-Timeframe Execution",
    symbol: "Symbol", side: "Side", buy: "BUY", sell: "SELL",
    entry_type: "Entry Type", market: "MARKET", limit: "LIMIT",
    trade_mode: "Trade Mode", entry_tf: "Entry Timeframe", ict_strategy: "ICT Strategy",
    entry_price: "Entry Price", stop_loss: "Stop Loss", take_profit: "Take Profit",
    htf_analysis: "HTF Analysis", lot_size: "Calculated Lot Size",
    dispatch_trade: "⚡ Dispatch Trade", auto_dispatch: "🎲 Smart Scan (One Trade)",
    trading_mode: "Trading Mode", mode_manual: "Manual Mode", mode_single_click: "Single-Click Mode",
    auto_pilot_label: "Auto-Pilot", auto_pilot_enable: "Enable Continuous Auto-Pilot",
    confluence_analysis: "Technical × Macro Confluence Engine", confluence_sub: "ICT + Macro + COT + Timing",
    active_positions: "Active Positions", pending_limit_orders: "Pending Limit Orders",
    trade_history: "Trade History", last_50: "last 50 closed",
    id: "ID", mode: "Mode", limit_entry: "Limit", action: "Action", close: "Close", cancel: "Cancel",
    exit: "Exit", status: "Status", pnl: "P&L", closed: "Closed", strategy_col: "Strategy",
    total: "Total", wins: "Wins", losses: "Losses", confluence: "Confluence",
    macro_geopolitics: "Macro & Geopolitics", macro_live_note: "Live · Yahoo + FuturesBench COT",
    us10y: "US 10Y", gsr: "Gold/Silver", dxy_flow: "DXY Flow", geopolitical_risk: "Geo Risk",
    cot_positioning: "COT Positioning", asset: "Asset", long: "Long", short: "Short", net: "Net", delta_net: "Δ Net",
    central_bank_probabilities: "Central Bank Rates", economic_calendar: "Economic Calendar",
    event: "Event", currency: "Currency", impact: "Impact", when: "When", forecast: "Forecast", previous: "Previous",
    ict_win_rates: "ICT Strategy Win Rates", ai_self_learning: "AI Self-Learning Journal", clear_all: "Clear all",
    no_lessons: "No lessons yet", no_active: "No active positions", no_pending: "No pending orders",
    no_history: "No closed trades yet", bullish: "Bullish", bearish: "Bearish", neutral: "Neutral",
    strong: "Strong", moderate: "Moderate", weak: "Weak", avoid: "Avoid",
    approved: "APPROVED", rejected: "REJECTED", days: "days", next_meeting: "Next",
    cut: "Cut", hold: "Hold", hike: "Hike",
    error_generic: "Error", dispatch_ok: "Trade dispatched", auto_ok: "Smart scan executed",
    settings_saved: "Settings saved permanently", settings_error: "Settings error",
    close_confirm: "Close this position at market?", cancel_confirm: "Cancel this order?",
    clear_confirm: "Clear all lessons?", risk_on: "Risk-On", risk_off: "Risk-Off", crisis: "Crisis",
    neutral_constructive: "Neutral-Constructive",
    market_bias_title: "Market Bias Index", market_bias_subtitle: "DXY · US10Y · COT · GSR",
    bias_guardrail_off: "GUARDRAIL: OFF", bias_guardrail_on: "GUARDRAIL: ACTIVE",
    bias_with_trend_hint: "With-Trend Assets",
    bias_strong_bull: "Strong USD Bias", bias_bull: "Mild USD Strength", bias_neutral: "Neutral",
    bias_bear: "Mild USD Weakness", bias_strong_bear: "Strong Anti-USD Bias",
    bias_dxy: "DXY Momentum", bias_us10y: "US10Y Yield", bias_cot: "COT Positioning", bias_gsr: "Gold/Silver Ratio",
    bias_bull_usd: "USD Bullish", bias_bear_usd: "USD Bearish", bias_neutral_impact: "Neutral",
    guardrail_blocked: "Trade Blocked", force_override: "Force Override (Not Recommended)",
    force_confirm: "Force-override? This fights the macro trend.",
    alignment_neutral: "No strong directional bias",
    dispatch_forced: "Trade dispatched with FORCE OVERRIDE",
    trade_blocked: "Trade Blocked",
    liq_unknown: "—", liq_high: "High Liquidity", liq_moderate: "Moderate Liquidity",
    liq_weak: "Weak Liquidity", liq_closed: "Market Closed",
    market_open: "Market Open", market_closed: "Market is Closed", weekend_break: "Weekend Break",
    daily_break: "Daily Break", reopens_in: "Reopens in", resumes_in: "Resumes in",
    news_blackout: "High-Impact News Blackout",
    autopilot_status_title: "Auto-Pilot Running", autopilot_status_subtitle: "Background engine scanning for setups",
    disable_ap: "Disable", ap_min_score: "Min Score", ap_max_concurrent: "Max Concurrent",
    ap_cooldown: "Cooldown (s)", ap_active_trades: "Active Trades",
    ap_save_config: "Save Auto-Pilot Config", ap_log_title: "Activity Log",
    ap_enabled_msg: "Auto-Pilot enabled", ap_disabled_msg: "Auto-Pilot disabled",
    ap_scanning: "Scanning", ap_waiting: "Waiting",
    footer_about_title: "About Engine",
    footer_about_text: "Institutional ICT analysis with real spot feed, 3 trading modes, live Session Liquidity filter, Market Closed countdown, High-impact News Blackout, Market Bias Index, COT positioning, AI self-learning, and 20 ICT/SMC strategies. DXY is display-only.",
    footer_dev_title: "Developer", footer_dev_name: "Built by Eng. Abdulelah Sadeq",
    footer_dev_role: "Quantitative FinTech & Algorithmic Trading Systems Architect",
    footer_dev_stack: "Stack: Python stdlib · SQLite · Tailwind CSS · Vanilla JS",
    footer_guide_title: "User Guide",
    footer_guide_1: "Set Capital and Risk% — saved permanently to SQLite.",
    footer_guide_2: "Choose Manual/Single-Click mode or enable Auto-Pilot.",
    footer_guide_3: "Trades are blocked on market close, weak liquidity, or high-impact news.",
    footer_guide_4: "DXY is display-only (used for bias) — cannot be traded.",
    footer_guide_5: "20 ICT/SMC strategies available — Silver Bullet is time-window only.",
    footer_copyright: "All rights reserved",
  },
  ar: {
    paper_sim_badge: "محاكاة فقط — لا تُرسل أوامر حقيقية",
    app_title: "محرك التداول والذكاء الكلي الاحترافي", app_subtitle: "محرك ICT المؤسسي · الإصدار 7.2",
    live: "مباشر", stale: "احتياطي", session: "الجلسة", capital: "رأس المال", win_rate: "نسبة النجاح",
    active: "نشط", inactive: "غير نشط",
    live_market_feed: "تغذية السوق المباشرة", feed_sub: "تغذية سبوت + Yahoo Finance · تحديث كل ثانية",
    account_risk: "الحساب وإدارة المخاطر", capital_usd: "رأس المال (دولار)", risk_per_trade: "المخاطرة لكل صفقة (%)",
    save_permanently: "حفظ بشكل دائم", risk_usd: "المخاطرة $/صفقة", total_trades: "إجمالي الصفقات",
    active_pos: "نشطة", pending_orders: "معلقة", realized_pnl: "الأرباح المحققة",
    trade_console: "منصة التداول — التنفيذ متعدد الأطر", symbol: "الرمز", side: "الاتجاه",
    buy: "شراء", sell: "بيع", entry_type: "نوع الدخول", market: "سوق", limit: "معلق",
    trade_mode: "نمط التداول", entry_tf: "إطار الدخول", ict_strategy: "استراتيجية ICT",
    entry_price: "سعر الدخول", stop_loss: "وقف الخسارة", take_profit: "جني الأرباح",
    htf_analysis: "تحليل الأطر العليا", lot_size: "حجم اللوت",
    dispatch_trade: "⚡ تنفيذ الصفقة", auto_dispatch: "🎲 مسح ذكي (صفقة واحدة)",
    trading_mode: "نمط التداول", mode_manual: "يدوي", mode_single_click: "نقرة واحدة",
    auto_pilot_label: "الطيار الآلي", auto_pilot_enable: "تفعيل الطيار الآلي المستمر",
    confluence_analysis: "محرك التوافق الفني والكلي", confluence_sub: "ICT + كلي + COT + توقيت",
    active_positions: "الصفقات النشطة", pending_limit_orders: "أوامر معلقة",
    trade_history: "سجل الصفقات", last_50: "آخر 50 مغلقة",
    id: "المعرف", mode: "النمط", limit_entry: "معلق", action: "إجراء", close: "إغلاق", cancel: "إلغاء",
    exit: "الخروج", status: "الحالة", pnl: "الربح/الخسارة", closed: "مغلق", strategy_col: "الاستراتيجية",
    total: "الإجمالي", wins: "أرباح", losses: "خسائر", confluence: "التوافق",
    macro_geopolitics: "التحليل الكلي والجيوسياسي", macro_live_note: "مباشر · Yahoo + COT",
    us10y: "السندات 10 سنوات", gsr: "ذهب/فضة", dxy_flow: "تدفق الدولار", geopolitical_risk: "مخاطر جيوسياسية",
    cot_positioning: "مراكز COT", asset: "الأصل", long: "شراء", short: "بيع", net: "صافي", delta_net: "تغير الصافي",
    central_bank_probabilities: "البنوك المركزية", economic_calendar: "التقويم الاقتصادي",
    event: "الحدث", currency: "العملة", impact: "التأثير", when: "الموعد", forecast: "المتوقع", previous: "السابق",
    ict_win_rates: "نسب نجاح ICT", ai_self_learning: "سجل التعلم الذاتي", clear_all: "مسح الكل",
    no_lessons: "لا توجد دروس بعد", no_active: "لا توجد صفقات نشطة", no_pending: "لا توجد أوامر معلقة",
    no_history: "لا توجد صفقات مغلقة", bullish: "صاعد", bearish: "هابط", neutral: "محايد",
    strong: "قوي", moderate: "متوسط", weak: "ضعيف", avoid: "تجنب",
    approved: "معتمد", rejected: "مرفوض", days: "يوم", next_meeting: "القادم",
    cut: "خفض", hold: "تثبيت", hike: "رفع",
    error_generic: "خطأ", dispatch_ok: "تم التنفيذ", auto_ok: "تم المسح الذكي",
    settings_saved: "تم حفظ الإعدادات", settings_error: "خطأ في الإعدادات",
    close_confirm: "إغلاق هذه الصفقة؟", cancel_confirm: "إلغاء هذا الأمر؟",
    clear_confirm: "مسح جميع الدروس؟", risk_on: "شهية المخاطرة", risk_off: "النفور من المخاطرة", crisis: "أزمة",
    neutral_constructive: "محايد إيجابي",
    market_bias_title: "مؤشر انحياز السوق", market_bias_subtitle: "الدولار · السندات · COT · ذهب/فضة",
    bias_guardrail_off: "الحماية: معطلة", bias_guardrail_on: "الحماية: نشطة",
    bias_with_trend_hint: "الأصول المتوافقة",
    bias_strong_bull: "انحياز قوي للدولار", bias_bull: "قوة معتدلة", bias_neutral: "محايد",
    bias_bear: "ضعف معتدل", bias_strong_bear: "انحياز قوي ضد الدولار",
    bias_dxy: "زخم الدولار", bias_us10y: "عائد السندات", bias_cot: "مراكز المؤسسات", bias_gsr: "ذهب/فضة",
    bias_bull_usd: "الدولار صاعد", bias_bear_usd: "الدولار هابط", bias_neutral_impact: "محايد",
    guardrail_blocked: "الصفقة محظورة", force_override: "تجاوز قسري (غير موصى)",
    force_confirm: "تجاوز الحماية؟ هذه الصفقة ضد الاتجاه.",
    alignment_neutral: "لا يوجد انحياز قوي",
    dispatch_forced: "تم التنفيذ بالتجاوز القسري",
    trade_blocked: "الصفقة محظورة",
    liq_unknown: "—", liq_high: "سيولة عالية", liq_moderate: "سيولة متوسطة",
    liq_weak: "سيولة ضعيفة", liq_closed: "السوق مغلق",
    market_open: "السوق مفتوح", market_closed: "السوق مغلق", weekend_break: "عطلة نهاية الأسبوع",
    daily_break: "استراحة يومية", reopens_in: "يفتح خلال", resumes_in: "يستأنف خلال",
    news_blackout: "توقف الأخبار المؤثرة",
    autopilot_status_title: "الطيار الآلي يعمل", autopilot_status_subtitle: "المحرك الخلفي يبحث عن إعدادات",
    disable_ap: "تعطيل", ap_min_score: "أدنى درجة", ap_max_concurrent: "أقصى صفقات",
    ap_cooldown: "تبريد (ث)", ap_active_trades: "الصفقات النشطة",
    ap_save_config: "حفظ إعدادات الطيار", ap_log_title: "سجل النشاط",
    ap_enabled_msg: "تم تفعيل الطيار الآلي", ap_disabled_msg: "تم تعطيل الطيار الآلي",
    ap_scanning: "جاري المسح", ap_waiting: "في الانتظار",
    footer_about_title: "عن التطبيق",
    footer_about_text: "تحليل ICT مؤسسي مع تغذية سبوت حقيقية، 3 أنماط تداول، مرشح سيولة الجلسات، عد تنازلي لإغلاق السوق، توقف الأخبار المؤثرة، مؤشر انحياز السوق، COT، تعلم ذاتي، و20 استراتيجية ICT/SMC. DXY للعرض فقط.",
    footer_dev_title: "المطور", footer_dev_name: "تم التطوير بواسطة المهندس عبدالإله صادق",
    footer_dev_role: "مهندس كوانت فينتك ومعماري أنظمة التداول الخوارزمي",
    footer_dev_stack: "التقنيات: Python stdlib · SQLite · Tailwind · JS",
    footer_guide_title: "دليل الاستخدام",
    footer_guide_1: "قم بتعيين رأس المال والمخاطرة — محفوظ في SQLite.",
    footer_guide_2: "اختر يدوي/نقرة واحدة أو فعّل الطيار الآلي.",
    footer_guide_3: "الصفقات محظورة عند إغلاق السوق أو ضعف السيولة أو الأخبار المؤثرة.",
    footer_guide_4: "DXY للعرض فقط (يستخدم للانحياز) — لا يمكن التداول عليه.",
    footer_guide_5: "20 استراتيجية ICT/SMC متاحة — Silver Bullet في نوافذ زمنية فقط.",
    footer_copyright: "جميع الحقوق محفوظة",
  }
};

const STRATEGY_AR = {
  "Liquidity Sweep & Stop Hunt": "مسح السيولة واقتناص الوقف",
  "Fair Value Gap (FVG)": "فجوة القيمة العادلة",
  "Order Block (OB)": "كتلة الأوامر",
  "Change of Character (CHoCH)": "تغير طبيعة السوق",
  "Market Structure Shift (MSS)": "انحراف هيكل السوق",
  "Break of Structure (BOS)": "كسر الهيكل",
  "Breaker Block": "كتلة الكسر العكسي",
  "Mitigation Block": "كتلة التخفيف",
  "Balanced Price Range (BPR)": "نطاق السعر المتوازن",
  "Volume Gap": "فجوة الحجم",
  "Inducement (IDM)": "الاستدراج",
  "Judas Swing / ORL": "حركة جوداس التضليلية",
  "Kill Zones & Power of 3": "مناطق القتل ونموذج 3",
  "Silver Bullet Strategy": "استراتيجية الرصاصة الفضية",
  "Optimal Trade Entry (OTE)": "الدخول الأمثل",
  "Premium & Discount Zones": "مناطق العلاوة والخصم",
  "Inversion FVG (IFVG)": "الفجوة المكسورة",
  "Institutional Order Flow (IOF)": "تدفق الأوامر المؤسسي",
  "Quarterly Theory / IPDA": "النظرية الربعية ونطاقات IPDA",
  "Daily Bias Framework": "إطار الانحياز اليومي",
};

const MODE_LABELS = {
  SCALPING_A: { en: "Scalping Mode A", ar: "سكالبينج النمط أ" },
  SCALPING_B: { en: "Scalping Mode B", ar: "سكالبينج النمط ب" },
  SWING: { en: "Swing", ar: "سوينج" },
};

const SYMBOLS = {
  "XAU/USD": { decimals: 2, mult: 100, pip: 0.01, label_en: "Gold", label_ar: "الذهب" },
  "XAG/USD": { decimals: 3, mult: 1000, pip: 0.01, label_en: "Silver", label_ar: "الفضة" },
  "EUR/USD": { decimals: 5, mult: 100000, pip: 0.0001, label_en: "Euro", label_ar: "اليورو" },
  "GBP/USD": { decimals: 5, mult: 100000, pip: 0.0001, label_en: "Sterling", label_ar: "الإسترليني" },
  "USD/JPY": { decimals: 3, mult: 1000, pip: 0.01, label_en: "Yen", label_ar: "الين" },
  "DXY": { decimals: 3, mult: 1000, pip: 0.01, label_en: "Dollar Index", label_ar: "مؤشر الدولار" },
};

const TRADEABLE_SYMBOL_KEYS = ["XAU/USD", "XAG/USD", "EUR/USD", "GBP/USD", "USD/JPY"];

const MODES = {
  SCALPING_A: { htf: ["1W", "1D", "1H"], entry_tfs: ["M5"] },
  SCALPING_B: { htf: ["1W", "1D", "4H"], entry_tfs: ["M15", "M1"] },
  SWING: { htf: ["1W", "1D"], entry_tfs: ["H1", "H4"] },
};

// ★ v7.2: 20 ICT/SMC strategies
const STRATEGIES = [
  "Liquidity Sweep & Stop Hunt", "Fair Value Gap (FVG)", "Order Block (OB)",
  "Change of Character (CHoCH)", "Market Structure Shift (MSS)", "Break of Structure (BOS)",
  "Breaker Block", "Mitigation Block", "Balanced Price Range (BPR)",
  "Volume Gap", "Inducement (IDM)", "Judas Swing / ORL",
  "Kill Zones & Power of 3", "Silver Bullet Strategy", "Optimal Trade Entry (OTE)",
  "Premium & Discount Zones", "Inversion FVG (IFVG)", "Institutional Order Flow (IOF)",
  "Quarterly Theory / IPDA", "Daily Bias Framework"
];

const DEFAULT_DISTS = {
  "XAU/USD": { SCALPING_A: [3.5, 7.0], SCALPING_B: [6.0, 12.0], SWING: [18.0, 54.0] },
  "XAG/USD": { SCALPING_A: [0.08, 0.16], SCALPING_B: [0.15, 0.30], SWING: [0.45, 1.35] },
  "DXY": { SCALPING_A: [0.12, 0.24], SCALPING_B: [0.20, 0.40], SWING: [0.60, 1.80] },
  "USD/JPY": { SCALPING_A: [0.12, 0.24], SCALPING_B: [0.20, 0.40], SWING: [0.60, 1.80] },
  "_fx": { SCALPING_A: [0.0012, 0.0024], SCALPING_B: [0.0020, 0.0040], SWING: [0.0060, 0.0180] },
};

const ANTI_USD_SYMBOLS = ["XAU/USD", "XAG/USD", "EUR/USD", "GBP/USD"];
const PRO_USD_SYMBOLS = ["USD/JPY", "DXY"];
const GUARDRAIL_THRESHOLD = 60;

const state = {
  lang: "en", prices: {}, pricesSnapshot: null,
  settings: { capital: 10000, risk_percent: 1 },
  summary: null, trades: [], strategies: [], macro: null, cot: null, cb: null,
  calendar: [], learning: [], lastConfluence: null, marketBias: null,
  marketStatus: null, autopilot: null,
};

function t(key) {
  const dict = I18N[state.lang] || I18N.en;
  return dict[key] || I18N.en[key] || key;
}
function isAr() { return state.lang === "ar"; }
function symLabel(sym) { const c = SYMBOLS[sym]; return c ? (isAr() ? c.label_ar : c.label_en) : sym; }
function strategyLabel(name) { return isAr() ? (STRATEGY_AR[name] || name) : name; }
function modeLabel(mode) { const m = MODE_LABELS[mode]; return m ? (isAr() ? m.ar : m.en) : mode; }
function fmt(sym, price) { const d = (SYMBOLS[sym] && SYMBOLS[sym].decimals) || 2; return Number(price).toFixed(d); }
function fmtUsd(n) { return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function fmtPnl(n) {
  const v = Number(n || 0);
  const cls = v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-400";
  return `<span class="${cls}">${v >= 0 ? "+" : ""}${v.toFixed(2)}</span>`;
}
function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function modeTag(mode) {
  const color = mode === "SWING" ? "bg-purple-900/60 text-purple-300" : mode === "SCALPING_B" ? "bg-cyan-900/60 text-cyan-300" : "bg-blue-900/60 text-blue-300";
  return `<span class="tag ${color}">${escapeHtml(modeLabel(mode))}</span>`;
}
async function api(path, method = "GET", body = null) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== null) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const err = (data && (data.error || data.detail)) || `HTTP ${res.status}`;
    const e = new Error(typeof err === "string" ? err : JSON.stringify(err));
    e.payload = data;
    throw e;
  }
  return data;
}
function setStatus(el, msg, type = "ok") {
  el.textContent = msg || "";
  el.className = "text-[11px] mt-2 h-4 " + (type === "err" ? "text-rose-400" : "text-emerald-400");
  if (msg) setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 5000);
}
function sparkline(history) {
  if (!history || history.length < 2) return "";
  const min = Math.min(...history), max = Math.max(...history);
  const rng = max - min || 1;
  const W = 140, H = 28;
  const pts = history.map((p, i) => `${((i / (history.length - 1)) * W).toFixed(1)},${(H - ((p - min) / rng) * H).toFixed(1)}`).join(" ");
  const up = history[history.length - 1] >= history[0];
  const stroke = up ? "#10b981" : "#f43f5e";
  return `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="opacity-90"><polyline points="${pts}" fill="none" stroke="${stroke}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>`;
}

function applyLanguage() {
  const dict = I18N[state.lang] || I18N.en;
  try {
    document.documentElement.lang = state.lang;
    document.documentElement.dir = isAr() ? "rtl" : "ltr";
    document.getElementById("btnLang").textContent = isAr() ? "🌐 عربي" : "🌐 English";
  } catch (e) { console.error(e); }
  try {
    document.querySelectorAll("[data-i18n]").forEach(el => {
      const k = el.getAttribute("data-i18n");
      if (dict[k] !== undefined) el.textContent = dict[k];
    });
  } catch (e) { console.error(e); }
  try { rebuildSymbolSelect(); } catch (e) { console.error(e); }
  try { rebuildStrategySelect(); } catch (e) { console.error(e); }
  try { rebuildModeSelect(); } catch (e) { console.error(e); }
  try { refreshEntryTFOptions(); } catch (e) { console.error(e); }
  try { if (state.pricesSnapshot) renderPrices(state.pricesSnapshot); } catch (e) { console.error(e); }
  try { if (state.marketBias) renderMarketBias(state.marketBias); } catch (e) { console.error(e); }
  try { if (state.marketStatus) renderMarketStatus(state.marketStatus); } catch (e) { console.error(e); }
  try { if (state.summary) renderSummary(state.summary); } catch (e) { console.error(e); }
  try { if (state.trades.length) { renderActive(state.trades); renderPending(state.trades); renderHistory(state.trades); } } catch (e) { console.error(e); }
  try { if (state.strategies.length) renderStrategies(state.strategies); } catch (e) { console.error(e); }
  try { if (state.macro) renderMacro(state.macro); } catch (e) { console.error(e); }
  try { if (state.cot) renderCOT(state.cot); } catch (e) { console.error(e); }
  try { if (state.cb) renderCB(state.cb); } catch (e) { console.error(e); }
  try { if (state.calendar.length) renderCalendar(state.calendar); } catch (e) { console.error(e); }
  try { if (state.learning.length) renderLearning(state.learning); } catch (e) { console.error(e); }
  try { if (state.lastConfluence) renderConfluence(state.lastConfluence); } catch (e) { console.error(e); }
  try { if (state.autopilot) renderAutopilot(state.autopilot); } catch (e) { console.error(e); }
  try { updateGuardrail(); } catch (e) { console.error(e); }
}
function toggleLanguage() { state.lang = isAr() ? "en" : "ar"; applyLanguage(); }

function rebuildSymbolSelect() {
  const sel = document.getElementById("selSymbol"); if (!sel) return;
  const cur = sel.value || "XAU/USD";
  sel.innerHTML = TRADEABLE_SYMBOL_KEYS.map(s => `<option value="${s}">${escapeHtml(s)} · ${escapeHtml(symLabel(s))}</option>`).join("");
  if (TRADEABLE_SYMBOL_KEYS.includes(cur)) sel.value = cur;
  else sel.value = "XAU/USD";
}
function rebuildStrategySelect() {
  const sel = document.getElementById("selStrategy"); if (!sel) return;
  const cur = sel.value || STRATEGIES[0];
  sel.innerHTML = STRATEGIES.map(s => `<option value="${escapeHtml(s)}">${escapeHtml(strategyLabel(s))}</option>`).join("");
  if (STRATEGIES.includes(cur)) sel.value = cur;
}
function rebuildModeSelect() {
  const sel = document.getElementById("selMode"); if (!sel) return;
  const cur = sel.value || "SCALPING_A";
  sel.innerHTML = Object.keys(MODES).map(m => `<option value="${m}">${escapeHtml(modeLabel(m))}</option>`).join("");
  sel.value = cur;
  refreshHTFDisplay();
}

function renderPrices(data) {
  const grid = document.getElementById("priceGrid");
  let html = "", liveCount = 0;
  const total = Object.keys(data).length;
  for (const sym in data) {
    const p = data[sym];
    if (!p.stale) liveCount++;
    const prevState = state.prices[sym] ? state.prices[sym].price : p.prev_close;
    let flash = "";
    if (state.prices[sym]) {
      if (p.price > prevState + 1e-12) flash = "flash-up";
      else if (p.price < prevState - 1e-12) flash = "flash-down";
    }
    const pctColor = p.change_pct > 0 ? "text-emerald-400" : p.change_pct < 0 ? "text-rose-400" : "text-slate-500";
    const arrow = p.change_pct > 0 ? "▲" : p.change_pct < 0 ? "▼" : "—";
    const srcCls = p.stale ? "feed-stale" : "feed-live";
    const srcTxt = p.stale ? t("stale") : t("live");
    const isTradeable = p.tradeable !== false;
    const tradeableBadge = isTradeable ? "" : `<span class="tag bg-slate-800/80 text-slate-400 ml-1">DISPLAY</span>`;
    html += `<div class="card rounded-xl p-3 ${flash}">
      <div class="flex items-center justify-between"><div class="text-[11px] font-bold text-slate-200 tracking-wider">${escapeHtml(sym)} ${tradeableBadge}</div><div class="text-[10px] ${pctColor} tabnum">${arrow} ${Math.abs(p.change_pct).toFixed(2)}%</div></div>
      <div class="text-xl font-bold text-white tabnum mt-1">${fmt(sym, p.price)}</div>
      <div class="text-[10px] text-slate-500 tabnum mt-1 flex justify-between"><span>H: ${fmt(sym, p.high)}</span><span>L: ${fmt(sym, p.low)}</span></div>
      <div class="mt-1">${sparkline(p.history)}</div>
      <div class="text-[9px] mt-1 flex items-center justify-between"><span class="${srcCls}">● ${srcTxt} · ${escapeHtml(p.source || "")}</span><span class="text-slate-600">${escapeHtml(symLabel(sym))}</span></div>
    </div>`;
    state.prices[sym] = p;
  }
  grid.innerHTML = html;
  const statusEl = document.getElementById("feedStatus");
  statusEl.textContent = liveCount === total ? t("live") : `${liveCount}/${total} ${t("live")}`;
  statusEl.className = liveCount > 0 ? "text-emerald-300 font-semibold" : "text-amber-300 font-semibold";
  document.getElementById("feedDot").className = liveCount > 0 ? "text-emerald-400 pulse-dot w-2 h-2 rounded-full bg-emerald-400" : "text-amber-400 w-2 h-2 rounded-full bg-amber-400";
}

function renderMarketStatus(ms) {
  state.marketStatus = ms;
  const banner = document.getElementById("marketBanner");
  const inner = document.getElementById("marketBannerInner");
  const icon = document.getElementById("msIcon");
  const title = document.getElementById("msTitle");
  const sub = document.getElementById("msSubtitle");
  const countdownBox = document.getElementById("msCountdownBox");
  const countdownLabel = document.getElementById("msCountdownLabel");
  banner.classList.remove("hidden");
  const liq = ms.liquidity;
  const newsActive = !!(ms.news_blackout && ms.news_blackout.active);

  if (ms.is_closed) {
    inner.className = "rounded-xl p-4 flex flex-wrap items-center justify-between gap-4 market-closed-banner";
    icon.textContent = "🔴";
    title.textContent = isAr() ? "السوق مغلق" : "Market is Closed";
    sub.textContent = ms.reason === "weekend" ? (isAr() ? "عطلة نهاية الأسبوع — عودة الأحد 22:00 UTC" : "Weekend Break — reopens Sunday 22:00 UTC") : (isAr() ? "استراحة يومية" : "Daily Break");
    countdownBox.classList.remove("hidden");
    if (countdownLabel) countdownLabel.textContent = t("reopens_in");
  } else if (newsActive) {
    inner.className = "rounded-xl p-4 flex flex-wrap items-center justify-between gap-4 news-banner";
    icon.textContent = "📰";
    title.textContent = isAr() ? "توقف الأخبار المؤثرة" : "High-Impact News Blackout";
    const evName = isAr() ? (ms.news_blackout.event_ar || ms.news_blackout.event_en) : ms.news_blackout.event_en;
    sub.textContent = `${evName} · ${ms.news_blackout.currency} · ${ms.news_blackout.impact}`;
    countdownBox.classList.remove("hidden");
    if (countdownLabel) countdownLabel.textContent = t("resumes_in");
  } else if (ms.is_daily_break) {
    inner.className = "rounded-xl p-4 flex flex-wrap items-center justify-between gap-4 bg-amber-950/60 border border-amber-700/60";
    icon.textContent = "🟡";
    title.textContent = isAr() ? "استراحة يومية" : "Daily Break";
    sub.textContent = isAr() ? "سيولة ضعيفة مؤقتاً" : "Weak liquidity — reopens soon";
    countdownBox.classList.remove("hidden");
    if (countdownLabel) countdownLabel.textContent = t("reopens_in");
  } else {
    const liqMap = { high: "bg-emerald-950/60 border border-emerald-700/60", moderate: "bg-sky-950/60 border border-sky-700/60", weak: "bg-rose-950/60 border border-rose-700/60" };
    inner.className = `rounded-xl p-4 flex flex-wrap items-center justify-between gap-4 ${liqMap[liq.level] || liqMap.moderate}`;
    icon.textContent = liq.level === "high" ? "🟢" : liq.level === "moderate" ? "🟡" : "🔴";
    title.textContent = isAr() ? "السوق مفتوح" : "Market Open";
    const liqLabel = t(`liq_${liq.level}`) || liq.level;
    sub.textContent = `${liqLabel} — ${liq.session}`;
    countdownBox.classList.add("hidden");
  }

  const chip = document.getElementById("liqChip");
  const dot = document.getElementById("liqDot");
  const txt = document.getElementById("liqText");
  const liqColor = liq.level === "high" ? "bg-emerald-500" : liq.level === "moderate" ? "bg-amber-500" : "bg-rose-500";
  dot.className = `w-2 h-2 rounded-full ${liqColor}`;
  txt.textContent = t(`liq_${liq.level}`) || liq.level;
  chip.className = `flex items-center gap-2 border rounded-full px-3 py-1.5 ${liq.level === "high" ? "bg-emerald-950/60 border-emerald-700/50" : liq.level === "moderate" ? "bg-sky-950/60 border-sky-700/50" : "bg-rose-950/60 border-rose-700/50"}`;
  updateCountdown();
  updateGuardrail();
}

function updateCountdown() {
  if (!state.marketStatus) return;
  let target = null;
  const ms = state.marketStatus;
  if (ms.is_closed || ms.is_daily_break) {
    if (ms.next_open) target = new Date(ms.next_open).getTime();
  } else if (ms.news_blackout && ms.news_blackout.active && ms.news_blackout.blackout_end) {
    target = new Date(ms.news_blackout.blackout_end).getTime();
  }
  const cdEl = document.getElementById("msCountdown");
  if (!cdEl) return;
  if (target === null) { cdEl.textContent = "00:00:00"; return; }
  const diff = Math.max(0, target - Date.now());
  if (diff <= 0) { cdEl.textContent = "00:00:00"; pollMarketStatus(); return; }
  const totalSec = Math.floor(diff / 1000);
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const mins = Math.floor((totalSec % 3600) / 60);
  const secs = totalSec % 60;
  cdEl.textContent = days > 0
    ? `${days}d ${String(hours).padStart(2,'0')}h ${String(mins).padStart(2,'0')}m ${String(secs).padStart(2,'0')}s`
    : `${String(hours).padStart(2,'0')}h ${String(mins).padStart(2,'0')}m ${String(secs).padStart(2,'0')}s`;
}

function renderMarketBias(bias) {
  state.marketBias = bias;
  const score = Number(bias.score);
  const scoreEl = document.getElementById("biasScoreDisplay");
  scoreEl.textContent = (score >= 0 ? "+" : "") + score.toFixed(1);
  let scoreColor;
  if (score >= 60) scoreColor = "text-rose-400";
  else if (score >= 25) scoreColor = "text-amber-400";
  else if (score <= -60) scoreColor = "text-emerald-400";
  else if (score <= -25) scoreColor = "text-emerald-300";
  else scoreColor = "text-slate-300";
  scoreEl.className = "text-4xl font-black tabnum " + scoreColor;
  const labelKey = bias.direction === "bullish_usd" ? (score >= 60 ? "bias_strong_bull" : "bias_bull") : bias.direction === "bearish_usd" ? (score <= -60 ? "bias_strong_bear" : "bias_bear") : "bias_neutral";
  document.getElementById("biasLabelDisplay").textContent = t(labelKey);
  document.getElementById("biasMarker").style.left = ((score + 100) / 2) + "%";
  document.getElementById("biasDirectionDisplay").textContent = bias.direction === "bullish_usd" ? t("bias_bull_usd") : bias.direction === "bearish_usd" ? t("bias_bear_usd") : t("bias_neutral_impact");
  const badge = document.getElementById("biasGuardrailBadge");
  if (bias.guardrail_active) {
    badge.className = "text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-950/80 text-rose-300 border border-rose-700/60 bias-pulse-strong";
    badge.textContent = t("bias_guardrail_on");
  } else {
    badge.className = "text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-800 text-slate-400";
    badge.textContent = t("bias_guardrail_off");
  }
  const trendEl = document.getElementById("biasWithTrendDisplay");
  if (bias.guardrail_active && bias.direction === "bullish_usd") {
    trendEl.textContent = isAr() ? "USD/JPY شراء" : "USD/JPY · BUY";
    trendEl.className = "text-[11px] font-semibold text-rose-300 mt-1";
  } else if (bias.guardrail_active && bias.direction === "bearish_usd") {
    trendEl.textContent = isAr() ? "XAU · XAG · EUR · GBP شراء" : "XAU · XAG · EUR · GBP · BUY";
    trendEl.className = "text-[11px] font-semibold text-emerald-300 mt-1";
  } else {
    trendEl.textContent = t("alignment_neutral");
    trendEl.className = "text-[11px] font-semibold text-slate-400 mt-1";
  }
  const grid = document.getElementById("biasComponentsGrid");
  const compI18N = { dxy: "bias_dxy", us10y: "bias_us10y", cot: "bias_cot", gsr: "bias_gsr" };
  grid.innerHTML = (bias.components || []).map(c => {
    const pts = Number(c.points);
    const ptsCls = pts > 5 ? "text-rose-400" : pts < -5 ? "text-emerald-400" : "text-slate-400";
    return `<div class="bg-slate-950/70 border border-slate-800 rounded-lg p-2">
      <div class="text-[9px] uppercase tracking-widest text-slate-500 truncate">${escapeHtml(t(compI18N[c.key] || c.key))}</div>
      <div class="flex items-baseline justify-between mt-1"><span class="text-[10px] text-slate-400 tabnum">${typeof c.value === "number" ? c.value.toLocaleString() : c.value}${escapeHtml(c.unit || "")}</span><span class="text-[12px] font-bold tabnum ${ptsCls}">${pts >= 0 ? "+" : ""}${pts.toFixed(1)}</span></div>
    </div>`;
  }).join("");
  updateGuardrail();
}

function computeAlignment(symbol, side, bias) {
  if (!bias) return { blocked: false, aligned: true, with_trend_side: null };
  const score = Number(bias.score || 0);
  const guardrail = !!bias.guardrail_active;
  let w = null;
  if (ANTI_USD_SYMBOLS.includes(symbol)) { if (score < 0) w = "BUY"; else if (score > 0) w = "SELL"; }
  else if (PRO_USD_SYMBOLS.includes(symbol)) { if (score > 0) w = "BUY"; else if (score < 0) w = "SELL"; }
  const blocked = guardrail && w !== null && side !== w;
  return { blocked, aligned: !blocked, with_trend_side: w, market_score: score };
}

function updateGuardrail() {
  const banner = document.getElementById("guardrailBanner");
  const text = document.getElementById("guardrailText");
  const btnDispatch = document.getElementById("btnDispatch");
  const btnForce = document.getElementById("btnForceOverride");
  const btnAuto = document.getElementById("btnAutoDispatch");
  let blocked = false;
  let reason = "";

  if (state.marketStatus && !state.marketStatus.is_open) {
    blocked = true;
    if (state.marketStatus.is_closed) {
      reason = isAr() ? "السوق مغلق — لا يمكن فتح صفقات جديدة" : "Market is closed — cannot open new trades";
    } else if (state.marketStatus.news_blackout && state.marketStatus.news_blackout.active) {
      const nb = state.marketStatus.news_blackout;
      const ev = isAr() ? (nb.event_ar || nb.event_en) : nb.event_en;
      const mins = Math.max(1, Math.ceil((nb.resume_in_sec || 0) / 60));
      reason = isAr() ? `توقف الأخبار المؤثرة: ${ev} — يستأنف بعد ${mins} دقيقة` : `News Blackout: ${ev} — resumes in ${mins} min`;
    } else {
      reason = isAr() ? "استراحة يومية — الصفقات محظورة مؤقتاً" : "Daily break — trades temporarily blocked";
    }
    btnForce.classList.add("hidden");
  } else if (state.marketStatus && !state.marketStatus.liquidity.allow_trades) {
    blocked = true;
    reason = isAr() ? `السيولة ${state.marketStatus.liquidity.level} — يمكن استخدام التجاوز القسري` : `Liquidity is ${state.marketStatus.liquidity.level} — force override available`;
    btnForce.classList.remove("hidden");
  } else if (state.marketBias) {
    const sym = document.getElementById("selSymbol").value;
    const side = document.getElementById("selSide").value;
    const align = computeAlignment(sym, side, state.marketBias);
    if (align.blocked) {
      blocked = true;
      reason = isAr() ? `انحياز السوق ${state.marketBias.score >= 0 ? "+" : ""}${state.marketBias.score.toFixed(1)} — اختر ${align.with_trend_side}` : `Market Bias ${state.marketBias.score >= 0 ? "+" : ""}${state.marketBias.score.toFixed(1)} — choose ${align.with_trend_side}`;
      btnForce.classList.remove("hidden");
    }
  }

  if (blocked) {
    banner.classList.remove("hidden");
    text.textContent = reason;
    btnDispatch.disabled = true; btnDispatch.classList.add("opacity-40", "cursor-not-allowed");
    btnAuto.disabled = true; btnAuto.classList.add("opacity-40", "cursor-not-allowed");
  } else {
    banner.classList.add("hidden");
    btnDispatch.disabled = false; btnDispatch.classList.remove("opacity-40", "cursor-not-allowed");
    btnAuto.disabled = false; btnAuto.classList.remove("opacity-40", "cursor-not-allowed");
    btnForce.classList.add("hidden");
  }
}

function renderAutopilot(ap) {
  state.autopilot = ap;
  const panel = document.getElementById("autopilotPanel");
  const checkbox = document.getElementById("chkAutopilot");
  const dot = document.getElementById("apDot");
  if (ap.enabled) {
    panel.classList.remove("hidden");
    checkbox.checked = true;
    dot.className = "ml-auto w-2 h-2 rounded-full bg-emerald-400 ap-pulse";
    document.getElementById("apMinScore").value = ap.config.min_score;
    document.getElementById("apMaxConcurrent").value = ap.config.max_concurrent;
    document.getElementById("apCooldown").value = ap.config.cooldown_sec;
    document.getElementById("apActiveCount").textContent = ap.stats.active_trades || 0;
    const chip = document.getElementById("apStatusChip");
    const st = ap.stats.status || "idle";
    let chipText = "● " + t("ap_scanning");
    if (st === "market_closed") chipText = "⏸ " + (isAr() ? "السوق مغلق" : "Market Closed");
    else if (st === "news_blackout") chipText = "📰 " + (isAr() ? "توقف الأخبار" : "News Blackout");
    else if (st === "no_setup") chipText = "🔍 " + (isAr() ? "لا إعداد" : "No Setup");
    else if (st.startsWith("cooldown")) chipText = "⏱ " + st;
    else if (st.startsWith("liquidity")) chipText = "💧 " + st;
    else if (st.startsWith("max_concurrent")) chipText = "🚫 " + st;
    chip.textContent = chipText;
    const logEl = document.getElementById("apLog");
    if (ap.log && ap.log.length > 0) {
      logEl.innerHTML = ap.log.map(l => {
        const time = (l.time || "").replace("T", " ").slice(11, 19);
        return `<div class="text-[11px]"><span class="text-slate-500">${time}</span> <span class="text-emerald-300">${escapeHtml(l.msg)}</span></div>`;
      }).join("");
    } else {
      logEl.innerHTML = `<div class="text-slate-500 text-[11px]">${t("ap_waiting")}...</div>`;
    }
  } else {
    panel.classList.add("hidden");
    checkbox.checked = false;
    dot.className = "ml-auto w-2 h-2 rounded-full bg-slate-500";
  }
}

function renderSummary(s) {
  document.getElementById("topCapital").textContent = fmtUsd(s.capital);
  document.getElementById("topWinRate").textContent = s.win_rate.toFixed(1) + "%";
  document.getElementById("sessionLabel").textContent = s.session || "—";
  const riskUsd = s.capital * s.risk_percent / 100.0;
  document.getElementById("riskUsd").textContent = fmtUsd(riskUsd);
  document.getElementById("statTotal").textContent = s.total_trades;
  document.getElementById("statActive").textContent = s.active;
  document.getElementById("statPending").textContent = s.pending;
  document.getElementById("statPnl").innerHTML = fmtPnl(s.realized_pnl);
  if (document.activeElement !== document.getElementById("inpCapital")) document.getElementById("inpCapital").value = s.capital;
  if (document.activeElement !== document.getElementById("inpRisk")) document.getElementById("inpRisk").value = s.risk_percent;
  state.settings.capital = s.capital;
  state.settings.risk_percent = s.risk_percent;
}

function confColor(s) { const v = Number(s || 0); return v >= 7 ? "text-emerald-400" : v >= 5 ? "text-amber-300" : "text-slate-400"; }

function renderActive(trades) {
  const active = trades.filter(x => x.status === "ACTIVE");
  document.getElementById("activeCount").textContent = active.length + " open";
  const body = document.getElementById("tblActive");
  if (active.length === 0) { body.innerHTML = `<tr><td colspan="11" class="text-center text-slate-500 py-6 text-xs">${t("no_active")}</td></tr>`; return; }
  body.innerHTML = active.map(x => `<tr class="stripe-row border-b border-slate-800/60">
    <td class="px-3 py-2 text-slate-400 tabnum">#${x.id}</td>
    <td class="px-3 py-2 font-semibold text-white">${escapeHtml(x.symbol)}</td>
    <td class="px-3 py-2 font-bold ${x.side === "BUY" ? "text-emerald-400" : "text-rose-400"}">${x.side === "BUY" ? t("buy") : t("sell")}</td>
    <td class="px-3 py-2">${modeTag(x.mode)}</td>
    <td class="px-3 py-2 text-right tabnum text-slate-200">${fmt(x.symbol, x.entry_price)}</td>
    <td class="px-3 py-2 text-right tabnum text-rose-400">${fmt(x.symbol, x.stop_loss)}</td>
    <td class="px-3 py-2 text-right tabnum text-emerald-400">${fmt(x.symbol, x.take_profit)}</td>
    <td class="px-3 py-2 text-right tabnum text-sky-300">${Number(x.lot_size).toFixed(2)}</td>
    <td class="px-3 py-2 text-right tabnum font-bold ${confColor(x.confluence_score)}">${Number(x.confluence_score || 0).toFixed(0)}/10</td>
    <td class="px-3 py-2 text-slate-400 max-w-[220px] truncate" title="${escapeHtml(x.strategy)}">${escapeHtml(strategyLabel(x.strategy))}</td>
    <td class="px-3 py-2 text-center"><button class="btn-close bg-rose-600/80 hover:bg-rose-500 text-white text-[10px] px-2 py-1 rounded" data-id="${x.id}">${t("close")}</button></td>
  </tr>`).join("");
  body.querySelectorAll(".btn-close").forEach(b => b.addEventListener("click", async () => {
    if (!confirm(t("close_confirm"))) return;
    try { await api(`/api/trades/${b.dataset.id}/close`, "POST", {}); pollTrades(); pollSummary(); pollStrategies(); pollLearning(); }
    catch (e) { alert(t("error_generic") + ": " + e.message); }
  }));
}

function renderPending(trades) {
  const pending = trades.filter(x => x.status === "PENDING");
  document.getElementById("pendingCountLabel").textContent = pending.length + " waiting";
  const body = document.getElementById("tblPending");
  if (pending.length === 0) { body.innerHTML = `<tr><td colspan="9" class="text-center text-slate-500 py-6 text-xs">${t("no_pending")}</td></tr>`; return; }
  body.innerHTML = pending.map(x => `<tr class="stripe-row border-b border-slate-800/60">
    <td class="px-3 py-2 text-slate-400 tabnum">#${x.id}</td>
    <td class="px-3 py-2 font-semibold text-white">${escapeHtml(x.symbol)}</td>
    <td class="px-3 py-2 font-bold ${x.side === "BUY" ? "text-emerald-400" : "text-rose-400"}">${x.side === "BUY" ? t("buy") : t("sell")}</td>
    <td class="px-3 py-2 text-right tabnum text-amber-300">${fmt(x.symbol, x.entry_price)}</td>
    <td class="px-3 py-2 text-right tabnum text-rose-400">${fmt(x.symbol, x.stop_loss)}</td>
    <td class="px-3 py-2 text-right tabnum text-emerald-400">${fmt(x.symbol, x.take_profit)}</td>
    <td class="px-3 py-2 text-right tabnum text-sky-300">${Number(x.lot_size).toFixed(2)}</td>
    <td class="px-3 py-2 text-slate-400 max-w-[220px] truncate">${escapeHtml(strategyLabel(x.strategy))}</td>
    <td class="px-3 py-2 text-center"><button class="btn-cancel bg-slate-700 hover:bg-slate-600 text-white text-[10px] px-2 py-1 rounded" data-id="${x.id}">${t("cancel")}</button></td>
  </tr>`).join("");
  body.querySelectorAll(".btn-cancel").forEach(b => b.addEventListener("click", async () => {
    if (!confirm(t("cancel_confirm"))) return;
    try { await api(`/api/trades/${b.dataset.id}/cancel`, "POST", {}); pollTrades(); pollSummary(); }
    catch (e) { alert(t("error_generic") + ": " + e.message); }
  }));
}

function renderHistory(trades) {
  const closed = trades.filter(x => ["WIN", "LOSS", "CANCELLED"].includes(x.status)).slice(0, 50);
  const body = document.getElementById("tblHistory");
  if (closed.length === 0) { body.innerHTML = `<tr><td colspan="11" class="text-center text-slate-500 py-6 text-xs">${t("no_history")}</td></tr>`; return; }
  body.innerHTML = closed.map(x => {
    const sc = x.status === "WIN" ? "bg-emerald-950/70 text-emerald-300" : x.status === "LOSS" ? "bg-rose-950/70 text-rose-300" : "bg-slate-800/70 text-slate-400";
    return `<tr class="stripe-row border-b border-slate-800/60">
      <td class="px-3 py-2 text-slate-400 tabnum">#${x.id}</td>
      <td class="px-3 py-2 font-semibold text-white">${escapeHtml(x.symbol)}</td>
      <td class="px-3 py-2 font-bold ${x.side === "BUY" ? "text-emerald-400" : "text-rose-400"}">${x.side === "BUY" ? t("buy") : t("sell")}</td>
      <td class="px-3 py-2">${modeTag(x.mode)}</td>
      <td class="px-3 py-2 text-right tabnum text-slate-200">${fmt(x.symbol, x.entry_price)}</td>
      <td class="px-3 py-2 text-right tabnum text-slate-200">${x.exit_price != null ? fmt(x.symbol, x.exit_price) : "—"}</td>
      <td class="px-3 py-2 text-right tabnum text-sky-300">${Number(x.lot_size).toFixed(2)}</td>
      <td class="px-3 py-2 text-slate-400 max-w-[220px] truncate">${escapeHtml(strategyLabel(x.strategy))}</td>
      <td class="px-3 py-2"><span class="tag ${sc}">${x.status}</span></td>
      <td class="px-3 py-2 text-right tabnum">${fmtPnl(x.pnl)}</td>
      <td class="px-3 py-2 text-slate-500 tabnum text-[10px]">${(x.closed_at || "").replace("T", " ").slice(0, 16)}</td>
    </tr>`;
  }).join("");
}

function renderStrategies(list) {
  const body = document.getElementById("tblStrategies");
  body.innerHTML = list.map(s => {
    const wr = s.win_rate;
    const bar = wr >= 65 ? "bg-emerald-500" : wr >= 50 ? "bg-amber-500" : "bg-rose-500";
    return `<tr class="stripe-row border-b border-slate-800/60">
      <td class="px-3 py-2 text-slate-200 max-w-[320px] truncate">${escapeHtml(strategyLabel(s.name))}</td>
      <td class="px-3 py-2 text-right tabnum text-slate-400">${s.total_trades}</td>
      <td class="px-3 py-2 text-right tabnum text-emerald-400">${s.wins}</td>
      <td class="px-3 py-2 text-right tabnum text-rose-400">${s.losses}</td>
      <td class="px-3 py-2 text-right tabnum"><div class="flex items-center gap-2 justify-end"><div class="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden"><div class="h-full ${bar}" style="width:${Math.min(100, wr)}%"></div></div><span class="font-bold text-white w-12 text-right">${wr.toFixed(1)}%</span></div></td>
    </tr>`;
  }).join("");
}

function renderMacro(d) {
  document.getElementById("macroVix").textContent = Number(d.vix).toFixed(2);
  document.getElementById("macro10y").textContent = Number(d.us10y).toFixed(3) + "%";
  document.getElementById("macroDxy").textContent = Number(d.dxy).toFixed(3);
  document.getElementById("macroGsr").textContent = Number(d.gold_silver_ratio).toFixed(2);
  const flow = Number(d.dxy_flow_score || 0);
  const flowEl = document.getElementById("macroFlow");
  flowEl.textContent = (flow >= 0 ? "+" : "") + flow;
  flowEl.className = "text-xl font-bold tabnum mt-1 " + (flow > 0 ? "text-emerald-300" : flow < 0 ? "text-rose-300" : "text-slate-300");
  document.getElementById("macroGeo").textContent = Number(d.geo_risk).toFixed(1);
}

function renderCOT(cot) {
  const body = document.getElementById("tblCot");
  let sources = new Set();
  body.innerHTML = Object.keys(cot).map(name => {
    const c = cot[name];
    if (c.source) sources.add(c.source);
    const dCls = c.delta_net > 0 ? "text-emerald-400" : c.delta_net < 0 ? "text-rose-400" : "text-slate-400";
    return `<tr class="stripe-row border-b border-slate-800/60">
      <td class="px-3 py-2 font-semibold text-white">${escapeHtml(isAr() ? (c.label_ar || name) : name)}</td>
      <td class="px-3 py-2 text-right tabnum text-emerald-300">${c.long.toLocaleString()}</td>
      <td class="px-3 py-2 text-right tabnum text-rose-300">${c.short.toLocaleString()}</td>
      <td class="px-3 py-2 text-right tabnum text-white font-bold">${c.net.toLocaleString()}</td>
      <td class="px-3 py-2 text-right tabnum ${dCls}">${c.delta_net >= 0 ? "+" : ""}${c.delta_net.toLocaleString()}</td>
    </tr>`;
  }).join("");
  document.getElementById("cotSource").textContent = sources.size ? Array.from(sources).join(", ") : "seed";
}

function renderCB(cb) {
  const el = document.getElementById("cbGrid");
  el.innerHTML = Object.keys(cb).map(key => {
    const c = cb[key];
    return `<div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
      <div class="flex items-baseline justify-between mb-1"><div class="font-bold text-white text-xs">${escapeHtml(isAr() ? c.name_ar : c.name_en)}</div><div class="text-[10px] text-slate-500">${escapeHtml(c.currency)} · ${Number(c.rate).toFixed(3)}%</div></div>
      <div class="text-[10px] text-slate-500 mb-2">${t("next_meeting")}: ${c.next_days} ${t("days")}</div>
      <div class="space-y-1">
        <div><div class="flex justify-between text-[10px] mb-0.5"><span class="text-rose-300">${t("cut")}</span><span class="text-white font-semibold tabnum">${c.cut.toFixed(1)}%</span></div><div class="h-1.5 bg-slate-800 rounded-full overflow-hidden"><div class="h-full bg-rose-500" style="width:${c.cut}%"></div></div></div>
        <div><div class="flex justify-between text-[10px] mb-0.5"><span class="text-slate-300">${t("hold")}</span><span class="text-white font-semibold tabnum">${c.hold.toFixed(1)}%</span></div><div class="h-1.5 bg-slate-800 rounded-full overflow-hidden"><div class="h-full bg-slate-500" style="width:${c.hold}%"></div></div></div>
        <div><div class="flex justify-between text-[10px] mb-0.5"><span class="text-emerald-300">${t("hike")}</span><span class="text-white font-semibold tabnum">${c.hike.toFixed(1)}%</span></div><div class="h-1.5 bg-slate-800 rounded-full overflow-hidden"><div class="h-full bg-emerald-500" style="width:${c.hike}%"></div></div></div>
      </div>
    </div>`;
  }).join("");
}

function renderCalendar(events) {
  const body = document.getElementById("tblCalendar");
  body.innerHTML = events.map(e => {
    const imp = e.impact === "HIGH" ? "bg-rose-950/70 text-rose-300" : e.impact === "MEDIUM" ? "bg-amber-950/70 text-amber-300" : "bg-slate-800/70 text-slate-400";
    return `<tr class="stripe-row border-b border-slate-800/60">
      <td class="px-3 py-2 text-slate-200 max-w-[300px] truncate">${escapeHtml(isAr() ? e.event_ar : e.event_en)}</td>
      <td class="px-3 py-2 font-semibold text-sky-300">${escapeHtml(e.currency)}</td>
      <td class="px-3 py-2"><span class="tag ${imp}">${e.impact}</span></td>
      <td class="px-3 py-2 text-slate-400 text-[11px]">${escapeHtml(e.when_str)}</td>
      <td class="px-3 py-2 text-right tabnum text-slate-300">${escapeHtml(e.forecast)}</td>
      <td class="px-3 py-2 text-right tabnum text-slate-500">${escapeHtml(e.previous)}</td>
    </tr>`;
  }).join("");
}

function renderLearning(list) {
  const el = document.getElementById("learnList");
  if (!list || list.length === 0) { el.innerHTML = `<div class="text-center text-slate-500 py-8 text-xs">${t("no_lessons")}</div>`; return; }
  el.innerHTML = list.map(l => `<div class="px-5 py-3 flex gap-3 items-start">
    <div class="shrink-0 w-2 h-2 rounded-full bg-amber-400 mt-1.5"></div>
    <div class="flex-1 min-w-0">
      <div class="flex flex-wrap items-center gap-2 text-[11px] mb-1"><span class="font-bold text-white">${escapeHtml(l.symbol || "?")}</span><span class="text-slate-600">·</span><span class="text-amber-300">${escapeHtml(strategyLabel(l.strategy || "?"))}</span>${l.mode ? `<span class="text-slate-600">·</span><span class="text-cyan-300">${escapeHtml(modeLabel(l.mode))}</span>` : ""}<span class="text-slate-600">·</span><span class="text-slate-500 tabnum">#${l.trade_id || "?"}</span><span class="text-slate-600 ml-auto">${(l.created_at || "").replace("T", " ").slice(0, 19)}</span></div>
      <div class="text-[12px] text-slate-300 leading-relaxed">${escapeHtml(l.lesson)}</div>
    </div>
  </div>`).join("");
}

function renderConfluence(c) {
  state.lastConfluence = c;
  const score = Number(c.score);
  const pct = (score / c.max_score) * 100;
  const ring = document.getElementById("confluenceRing");
  ring.style.setProperty("--p", pct + "%");
  ring.style.background = `conic-gradient(${score >= 7 ? "#10b981" : score >= 5 ? "#f59e0b" : "#ef4444"} ${pct}%, #1e293b 0)`;
  document.getElementById("confluenceScore").textContent = score;
  const verdict = document.getElementById("confluenceVerdict");
  verdict.textContent = t(c.approved ? "approved" : "rejected") + " · " + t(c.bias);
  verdict.className = "text-[11px] mt-2 font-bold " + (c.approved ? "text-emerald-400" : "text-rose-400");
  document.getElementById("confluenceHeadline").textContent = isAr() ? c.headline_ar : c.headline_en;
  const reasonsEl = document.getElementById("confluenceReasons");
  reasonsEl.innerHTML = c.reasons.map(r => `<div class="bg-slate-950/60 rounded px-2 py-1.5 ${r.passed ? "reason-pass" : "reason-fail"}"><div class="flex justify-between gap-2"><span class="text-[11px] text-slate-300">${escapeHtml(isAr() ? r.ar : r.en)}</span><span class="text-[11px] font-bold ${r.passed ? "text-emerald-400" : "text-slate-500"} tabnum">+${r.points}</span></div></div>`).join("");
}

async function refreshConfluence() {
  const sym = document.getElementById("selSymbol").value;
  const side = document.getElementById("selSide").value;
  const mode = document.getElementById("selMode").value;
  const strat = document.getElementById("selStrategy").value;
  try { const r = await api(`/api/confluence?symbol=${encodeURIComponent(sym)}&side=${encodeURIComponent(side)}&mode=${encodeURIComponent(mode)}&strategy=${encodeURIComponent(strat)}`); renderConfluence(r.data); }
  catch (e) { console.error(e); }
}

function refreshEntryTFOptions() {
  const modeEl = document.getElementById("selMode"); if (!modeEl) return;
  const tfs = MODES[modeEl.value].entry_tfs;
  const sel = document.getElementById("selEntryTF"); if (!sel) return;
  sel.innerHTML = tfs.map(tf => `<option value="${tf}">${tf}</option>`).join("");
  sel.disabled = tfs.length === 1;
}
function refreshHTFDisplay() {
  const mode = document.getElementById("selMode").value;
  document.getElementById("htfDisplay").textContent = MODES[mode].htf.join(" · ");
}
function applyDefaults() {
  const sym = document.getElementById("selSymbol").value;
  const side = document.getElementById("selSide").value;
  const mode = document.getElementById("selMode").value;
  const entryType = document.getElementById("selEntryType").value;
  const cfg = SYMBOLS[sym];
  const dist = (DEFAULT_DISTS[sym] || DEFAULT_DISTS._fx)[mode];
  const [slD, tpD] = dist;
  let entry;
  if (entryType === "MARKET" || !state.prices[sym]) {
    entry = state.prices[sym] ? state.prices[sym].price : cfg.pip * 100;
  } else {
    const cur = parseFloat(document.getElementById("inpEntry").value);
    entry = isFinite(cur) ? cur : (state.prices[sym] ? state.prices[sym].price : cfg.pip * 100);
  }
  const sl = side === "BUY" ? entry - slD : entry + slD;
  const tp = side === "BUY" ? entry + tpD : entry - tpD;
  document.getElementById("inpEntry").value = entry.toFixed(cfg.decimals);
  document.getElementById("inpSL").value = sl.toFixed(cfg.decimals);
  document.getElementById("inpTP").value = tp.toFixed(cfg.decimals);
  const inp = document.getElementById("inpEntry");
  if (entryType === "MARKET") { inp.setAttribute("readonly", "readonly"); inp.classList.add("opacity-60"); }
  else { inp.removeAttribute("readonly"); inp.classList.remove("opacity-60"); }
  updateLotPreview();
  updateGuardrail();
  refreshConfluence();
}
function updateLotPreview() {
  const sym = document.getElementById("selSymbol").value;
  const entry = parseFloat(document.getElementById("inpEntry").value);
  const sl = parseFloat(document.getElementById("inpSL").value);
  const cap = state.settings.capital;
  const risk = state.settings.risk_percent;
  const el = document.getElementById("lotDisplay");
  if (!isFinite(entry) || !isFinite(sl) || entry === sl) { el.textContent = "0.00"; return; }
  const lot = cap * (risk / 100.0) / (Math.abs(entry - sl) * SYMBOLS[sym].mult);
  el.textContent = Math.max(0.01, lot).toFixed(2);
}

async function saveSettings() {
  const cap = parseFloat(document.getElementById("inpCapital").value);
  const risk = parseFloat(document.getElementById("inpRisk").value);
  const st = document.getElementById("settingsStatus");
  if (!isFinite(cap) || cap <= 0) { setStatus(st, "capital > 0", "err"); return; }
  if (!isFinite(risk) || risk <= 0 || risk > 100) { setStatus(st, "risk (0,100]", "err"); return; }
  try { await api("/api/settings", "POST", { capital: cap, risk_percent: risk }); state.settings.capital = cap; state.settings.risk_percent = risk; setStatus(st, t("settings_saved"), "ok"); updateLotPreview(); pollSummary(); }
  catch (e) { setStatus(st, e.message, "err"); }
}

async function dispatchTrade(force = false) {
  const st = document.getElementById("dispatchStatus");
  const tradingMode = document.getElementById("selTradingMode").value;
  const sym = document.getElementById("selSymbol").value;
  const side = document.getElementById("selSide").value;
  const mode = document.getElementById("selMode").value;
  const entryType = document.getElementById("selEntryType").value;
  const entryTF = document.getElementById("selEntryTF").value;
  const strat = document.getElementById("selStrategy").value;
  const payload = { symbol: sym, side, mode, entry_type: entryType, entry_timeframe: entryTF, strategy: strat, force: !!force };
  if (tradingMode === "manual") {
    const entry = parseFloat(document.getElementById("inpEntry").value);
    const sl = parseFloat(document.getElementById("inpSL").value);
    const tp = parseFloat(document.getElementById("inpTP").value);
    if (!isFinite(entry) || !isFinite(sl) || !isFinite(tp)) { setStatus(st, t("error_generic") + ": invalid inputs", "err"); return; }
    payload.stop_loss = sl; payload.take_profit = tp;
    if (entryType === "LIMIT") payload.entry_price = entry;
  }
  try {
    const r = await api("/api/trades", "POST", payload);
    const suffix = force ? " · " + t("dispatch_forced") : "";
    setStatus(st, `${t("dispatch_ok")} #${r.data.id} · lot ${r.data.lot_size} · score ${r.confluence.score}/10${suffix}`, "ok");
    renderConfluence(r.confluence);
    if (r.bias) renderMarketBias(r.bias);
    if (r.market_status) renderMarketStatus(r.market_status);
    pollTrades(); pollSummary(); pollStrategies(); pollLearning(); pollAutopilot();
  } catch (e) {
    if (e.payload && e.payload.bias) renderMarketBias(e.payload.bias);
    if (e.payload && e.payload.market_status) renderMarketStatus(e.payload.market_status);
    setStatus(st, e.message, "err");
  }
}

async function dispatchAuto() {
  const st = document.getElementById("dispatchStatus");
  const mode = document.getElementById("selMode").value;
  try {
    const r = await api("/api/auto_dispatch", "POST", { mode });
    setStatus(st, `${t("auto_ok")} #${r.data.id} · ${r.data.symbol} ${r.data.side} · score ${r.confluence.score}/10`, "ok");
    renderConfluence(r.confluence);
    if (r.bias) renderMarketBias(r.bias);
    if (r.market_status) renderMarketStatus(r.market_status);
    pollTrades(); pollSummary(); pollStrategies(); pollLearning();
  } catch (e) {
    if (e.payload && e.payload.market_status) renderMarketStatus(e.payload.market_status);
    setStatus(st, e.message, "err");
  }
}

async function toggleAutopilot(enabled) {
  try { await api("/api/autopilot", "POST", { enabled }); pollAutopilot(); }
  catch (e) { alert(t("error_generic") + ": " + e.message); }
}
async function saveAutopilotConfig() {
  const minScore = parseFloat(document.getElementById("apMinScore").value);
  const maxConcurrent = parseInt(document.getElementById("apMaxConcurrent").value);
  const cooldown = parseInt(document.getElementById("apCooldown").value);
  try { await api("/api/autopilot", "POST", { min_score: minScore, max_concurrent: maxConcurrent, cooldown_sec: cooldown }); pollAutopilot(); }
  catch (e) { alert(t("error_generic") + ": " + e.message); }
}
async function clearLearning() {
  if (!confirm(t("clear_confirm"))) return;
  try { await api("/api/self_learning/reset", "POST", {}); pollLearning(); }
  catch (e) { alert(t("error_generic") + ": " + e.message); }
}

async function pollPrices() {
  try {
    const r = await api("/api/prices");
    state.pricesSnapshot = r.data;
    renderPrices(r.data);
    if (document.getElementById("selEntryType").value === "MARKET") {
      const sym = document.getElementById("selSymbol").value;
      if (state.prices[sym]) {
        document.getElementById("inpEntry").value = Number(state.prices[sym].price).toFixed(SYMBOLS[sym].decimals);
        updateLotPreview();
      }
    }
  } catch (e) { console.error(e); }
}
async function pollMarketStatus() { try { const r = await api("/api/market_status"); renderMarketStatus(r.data); } catch (e) { console.error(e); } }
async function pollMarketBias() { try { const r = await api("/api/market_bias"); renderMarketBias(r.data); } catch (e) { console.error(e); } }
async function pollAutopilot() { try { const r = await api("/api/autopilot"); renderAutopilot(r.data); } catch (e) { console.error(e); } }
async function pollSummary() { try { const r = await api("/api/summary"); state.summary = r.data; renderSummary(r.data); } catch (e) { console.error(e); } }
async function pollTrades() { try { const r = await api("/api/trades?limit=300"); state.trades = r.data; renderActive(r.data); renderPending(r.data); renderHistory(r.data); } catch (e) { console.error(e); } }
async function pollStrategies() { try { const r = await api("/api/strategies"); state.strategies = r.data; renderStrategies(r.data); } catch (e) { console.error(e); } }
async function pollMacro() { try { const r = await api("/api/macro"); state.macro = r.data; renderMacro(r.data); } catch (e) { console.error(e); } }
async function pollCOT() { try { const r = await api("/api/cot"); state.cot = r.data; renderCOT(r.data); } catch (e) { console.error(e); } }
async function pollCB() { try { const r = await api("/api/central_banks"); state.cb = r.data; renderCB(r.data); } catch (e) { console.error(e); } }
async function pollCalendar() { try { const r = await api("/api/calendar"); state.calendar = r.data; renderCalendar(r.data); } catch (e) { console.error(e); } }
async function pollLearning() { try { const r = await api("/api/self_learning?limit=40"); state.learning = r.data; renderLearning(r.data); } catch (e) { console.error(e); } }

async function priceLoop() {
  while (true) {
    const start = Date.now();
    await pollPrices();
    const elapsed = Date.now() - start;
    await new Promise(r => setTimeout(r, Math.max(50, 1000 - elapsed)));
  }
}

async function boot() {
  document.getElementById("year").textContent = new Date().getFullYear();
  document.getElementById("btnLang").addEventListener("click", toggleLanguage);
  rebuildSymbolSelect(); rebuildStrategySelect(); rebuildModeSelect();

  document.getElementById("selSymbol").addEventListener("change", applyDefaults);
  document.getElementById("selSide").addEventListener("change", applyDefaults);
  document.getElementById("selMode").addEventListener("change", () => { refreshEntryTFOptions(); refreshHTFDisplay(); applyDefaults(); });
  document.getElementById("selEntryType").addEventListener("change", applyDefaults);
  document.getElementById("selStrategy").addEventListener("change", () => { refreshConfluence(); });
  document.getElementById("selEntryTF").addEventListener("change", () => { refreshConfluence(); });
  document.getElementById("inpEntry").addEventListener("input", () => { updateLotPreview(); refreshConfluence(); });
  document.getElementById("inpSL").addEventListener("input", updateLotPreview);
  document.getElementById("inpTP").addEventListener("input", updateLotPreview);
  document.getElementById("btnSaveSettings").addEventListener("click", saveSettings);
  document.getElementById("btnDispatch").addEventListener("click", () => dispatchTrade(false));
  document.getElementById("btnAutoDispatch").addEventListener("click", dispatchAuto);
  document.getElementById("btnClearLearn").addEventListener("click", clearLearning);
  document.getElementById("btnForceOverride").addEventListener("click", () => { if (confirm(t("force_confirm"))) dispatchTrade(true); });
  document.getElementById("chkAutopilot").addEventListener("change", (e) => toggleAutopilot(e.target.checked));
  document.getElementById("btnDisableAp").addEventListener("click", () => toggleAutopilot(false));
  document.getElementById("btnSaveApConfig").addEventListener("click", saveAutopilotConfig);

  await Promise.all([
    pollPrices(), pollMarketStatus(), pollMarketBias(), pollAutopilot(),
    pollSummary(), pollStrategies(), pollMacro(), pollCOT(), pollCB(),
    pollCalendar(), pollTrades(), pollLearning()
  ]);
  applyDefaults();
  refreshConfluence();

  priceLoop();
  setInterval(pollMarketStatus, 5000);
  setInterval(updateCountdown, 1000);
  setInterval(pollMarketBias, 2000);
  setInterval(pollAutopilot, 3000);
  setInterval(pollSummary, 3000);
  setInterval(pollTrades, 2500);
  setInterval(pollStrategies, 5000);
  setInterval(pollMacro, 4000);
  setInterval(pollCOT, 10000);
  setInterval(pollCB, 12000);
  setInterval(pollCalendar, 30000);
  setInterval(pollLearning, 5000);
  setInterval(refreshConfluence, 5000);
}

boot();
</script>
</body>
</html>
"""


def _handle_signal(signum, frame):
    print(f"[signal] {signum} received — shutting down...", flush=True)
    engine.begin_shutdown()


def main():
    engine.init_db()
    print(f"[startup] DB: {config.DB_PATH}", flush=True)
    print(f"[startup] Listening on http://{config.HOST}:{config.PORT}", flush=True)
    print(f"[startup] Bias guardrail threshold: ±{config.BIAS_GUARDRAIL_THRESHOLD}", flush=True)
    print(f"[startup] Tradeable symbols: {sorted(config.TRADEABLE_SYMBOLS)}", flush=True)
    print(f"[startup] ICT strategies loaded: {len(config.ICT_STRATEGIES)}", flush=True)
    print(f"[startup] News blackout: -{config.NEWS_BLACKOUT_BEFORE_MIN}min / +{config.NEWS_BLACKOUT_AFTER_MIN}min", flush=True)

    threads = engine.start_threads()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[server] KeyboardInterrupt", flush=True)
    finally:
        engine.begin_shutdown()
        server.server_close()
        engine.cleanup_threads(threads)
        print("[shutdown] complete", flush=True)


if __name__ == "__main__":
    main()
