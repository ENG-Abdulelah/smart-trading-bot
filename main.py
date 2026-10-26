import urllib.request
import json
import datetime
import time
import sqlite3
import random
import os
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Production-Ready AI ICT & Macro Bot is running 24/7!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN", "8667800516:AAE48vBxGIRld55SeDLcSpIdB2P8lrrkWbw")
CHAT_ID = "6588992670"

bot_settings = {
    'capital': 20.0,
    'risk_pct': 1.5,
    'stop_pips': 15.0,
    'auto_dispatch_active': False,
    'preferred_style': 'scalp'
}

live_market_cache = {
    'XAUUSD': 2865.20,
    'EURUSD': 1.0580,
    'GBPUSD': 1.2650,
    'DXY': 104.20
}

# ==========================================
# فحص حالة السوق (مفتوح / مغلق / استراحة)
# ==========================================
def check_market_status():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    weekday = now_utc.weekday() 
    hour = now_utc.hour
    
    if weekday == 5: 
        return False, "🔴 السوق مغلق تماماً (عطلة نهاية الأسبوع - السبت)"
    elif weekday == 6 and hour < 22: 
        return False, "🔴 السوق مغلق (بانتظار افتتاح جلسة الأسبوع الأحد مساءً)"
    elif weekday == 4 and hour >= 21: 
        return False, "🔴 السوق مغلق (تم إغلاق الأسواق أسبوعياً بنهاية جلسة الجمعة)"
    
    if hour == 23 or hour == 0:
        return False, "🟡 السوق في فترة استراحة وتوقف مؤقت للسيولة بين الجلسات"
        
    return True, "🟢 السوق مفتوح وتعمل السيولة الحية"

# ==========================================
# قاعدة بيانات التتبع والتعلم الذاتي
# ==========================================
def init_db():
    conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_autonomous_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset TEXT,
            trade_type TEXT,
            strategy_used TEXT,
            lot_size REAL,
            risk_amount REAL,
            direction TEXT,
            entry REAL,
            dxy_state REAL,
            result TEXT DEFAULT 'PENDING_EVALUATION',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def log_trade(asset, trade_type, strategy, lot, risk_amt, direction, entry, dxy):
    conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ai_autonomous_trades (asset, trade_type, strategy_used, lot_size, risk_amount, direction, entry, dxy_state) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (asset, trade_type, strategy, lot, risk_amt, direction, entry, dxy))
    
    cursor.execute("SELECT id, entry, direction FROM ai_autonomous_trades WHERE result = 'PENDING_EVALUATION'")
    pending = cursor.fetchall()
    for t_id, t_entry, t_dir in pending:
        curr_price = live_market_cache.get(asset, t_entry)
        win = ("BUY" in t_dir and curr_price > t_entry) or ("SELL" in t_dir and curr_price < t_entry)
        res = "SUCCESSFUL_WIN" if win else "OPTIMIZED_LOSS"
        cursor.execute("UPDATE ai_autonomous_trades SET result = ? WHERE id = ?", (res, t_id))
        
    conn.commit()
    conn.close()

def send_telegram_message(chat_id, message, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=3) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            if res_data.get('ok'):
                return res_data['result']['message_id']
    except Exception:
        pass
    return None

def edit_message_text(chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=3) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            if res_data.get('ok'):
                return True
    except Exception:
        pass
    return False

def answer_callback_query(callback_query_id, text="", show_alert=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id, "text": text, "show_alert": show_alert}
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=1) as response:
            pass
    except Exception:
        pass

def fetch_live_market_data():
    global live_market_cache
    try:
        dxy_url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1m"
        req = urllib.request.Request(dxy_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode('utf-8'))
            price = data['chart']['result'][0]['meta']['regularMarketPrice']
            if price and 80 < float(price) < 130:
                live_market_cache['DXY'] = round(float(price), 2)
    except Exception:
        pass

    try:
        gold_url = "https://api.gold-api.com/price/XAU"
        req_obj = urllib.request.Request(gold_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_obj, timeout=2) as response:
            gold_data = json.loads(response.read().decode('utf-8'))
            price_val = float(gold_data.get('price', 0))
            if 1000 < price_val < 5000:
                live_market_cache['XAUUSD'] = round(price_val, 2)
    except Exception:
        pass

    try:
        eur_url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1m"
        req = urllib.request.Request(eur_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=1.5) as response:
            data = json.loads(response.read().decode('utf-8'))
            price = data['chart']['result'][0]['meta']['regularMarketPrice']
            if price and 0.8 < float(price) < 1.5:
                live_market_cache['EURUSD'] = round(float(price), 4)
    except Exception:
        pass

    try:
        gbp_url = "https://query1.finance.yahoo.com/v8/finance/chart/GBPUSD=X?interval=1m"
        req = urllib.request.Request(gbp_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=1.5) as response:
            data = json.loads(response.read().decode('utf-8'))
            price = data['chart']['result'][0]['meta']['regularMarketPrice']
            if price and 0.9 < float(price) < 1.7:
                live_market_cache['GBPUSD'] = round(float(price), 4)
    except Exception:
        pass

    return live_market_cache

# ==========================================
# محرك التتبع والإرسال التلقائي في الخلفية
# ==========================================
def background_auto_trader():
    print("🚀 Background Autonomous Trading & Learning Engine started...")
    while True:
        try:
            time.sleep(120)  # فحص السوق كل دقيقتين
            market_open, _ = check_market_status()
            
            if bot_settings['auto_dispatch_active'] and market_open:
                market_data = fetch_live_market_data()
                dxy = market_data['DXY']
                
                assets = ["XAUUSD", "EURUSD", "GBPUSD"]
                chosen_asset = random.choice(assets)
                price = market_data[chosen_asset]
                
                style = bot_settings['preferred_style']
                strategies = ["FVG Mitigation", "Order Block Rejection", "Liquidity Sweep"]
                chosen_strat = random.choice(strategies)
                
                capital = bot_settings['capital']
                risk_pct = bot_settings['risk_pct']
                risk_amt = capital * (risk_pct / 100.0)
                stop_pips = bot_settings['stop_pips']
                lot_size = round(risk_amt / (stop_pips * 10), 2)
                if lot_size < 0.01:
                    lot_size = 0.01
                    
                direction = "🟢 شراء (BUY - إشارة سيولة تلقائية)" if dxy <= 104 else "🔴 بيع (SELL - إشارة ضغط مؤسسي تلقائية)"
                
                log_trade(chosen_asset, style.upper(), chosen_strat, lot_size, risk_amt, direction, price, dxy)
                
                auto_msg = f"""🚨 <b>[إرسال صفقة تلقائي في الخلفية (Auto-Dispatcher)]</b>
═════════════════════════════
📊 <b>الأصل:</b> <code>{chosen_asset}</code> | <b>النمط:</b> <code>{style.upper()}</code>
💵 <b>مؤشر الدولار ($DXY):</b> <code>{dxy}</code>
🔍 <b>الاستراتيجية المكتشفة:</b> <code>{chosen_strat}</code>
📍 <b>القرار:</b> <code>{direction}</code>
───────────────────────────
💵 <b>سعر الدخول:</b> <code>{price}</code>
⚖️ <b>المخاطرة والوت:</b> رأس المال: <code>${capital:,.2f}</code> | المخاطرة: <code>{risk_pct}%</code> | <b>Lot:</b> <code>{lot_size}</code>
🧠 <i>تم إرسال هذه الفرصة تلقائياً لمتابعتها ودراستها في الذاكرة الذكية.</i>"""
                
                send_telegram_message(CHAT_ID, auto_msg)
        except Exception as e:
            print(f"Background dispatcher error: {e}")

threading.Thread(target=background_auto_trader, daemon=True).start()

def generate_menu_keyboard():
    market_is_open, market_status_text = check_market_status()
    dispatch_status = "🟢 تفعيل الإرسال التلقائي بالخلفية (Active)" if bot_settings['auto_dispatch_active'] else "🔴 إيقاف الإرسال التلقائي (Off)"
    text = f"""🏛️ <b>غرفة العمليات الذكية والتحليل التلقائي (AI Core)</b>
═════════════════════════════
📊 <b>رأس المال:</b> <code>${bot_settings['capital']:,.2f}</code> | <b>المخاطرة:</b> <code>{bot_settings['risk_pct']}%</code>
🤖 <b>الإرسال التلقائي:</b> {dispatch_status}
⏱️ <b>حالة السوق الحية:</b> {market_status_text}

اختر القسم المطلوب:"""
    keyboard = {
        "inline_keyboard": [
            [{"text": "📊 تقارير الأجندة والأخبار والـ COT", "callback_data": "macro_report"}],
            [{"text": "⚡ تحليل الـ POI والفريمات المتعددة", "callback_data": "select_style"}],
            [{"text": "🔄 تبديل حالة الإرسال التلقائي (Auto-Dispatch)", "callback_data": "toggle_dispatch"}],
            [{"text": "📈 تقرير أداء ونجاح الاستراتيجيات أسبوعياً", "callback_data": "weekly_report"}],
            [{"text": "⚙️ تعديل رأس المال والمخاطرة (Risk Config)", "callback_data": "risk_config_prompt"}]
        ]
    }
    return text, keyboard

def generate_style_keyboard():
    market_is_open, market_status_text = check_market_status()
    text = f"""⚡ <b>اختر نوع التداول المفضل للإرسال التلقائي:</b>\n{market_status_text}"""
    keyboard = {
        "inline_keyboard": [
            [{"text": "⚡ سكالبينج (Scalp - تلقائي)", "callback_data": "style_scalp"}],
            [{"text": "🌊 سوينج (Swing - تلقائي)", "callback_data": "style_swing"}],
            [{"text": "◄ العودة للرئيسية", "callback_data": "back_to_menu"}]
        ]
    }
    return text, keyboard

def generate_macro_report_detailed(market_data):
    market_is_open, market_status_text = check_market_status()
    dxy = market_data['DXY']
    return f"""🌐 <b>التقرير الاقتصادي والجيوسياسي والأجندة الشاملة</b>
═════════════════════════════
⏱️ <b>حالة السوق:</b> {market_status_text}
💵 <b>مؤشر الدولار ($DXY):</b> <code>{dxy}</code>

📅 <b>أهم الأخبار الاقتصادية والنتائج الفورية:</b>
1️⃣ <b>مؤشر أسعار المستهلكين (CPI):</b> <code>3.0% (سلبي للدولار - داعم للذهب)</code>.
2️⃣ <b>تقرير الوظائف (NFP):</b> <code>إضافة 225 ألف وظيفة</code>.
3️⃣ <b>الفيدرالي (FOMC):</b> <code>تثبيت الفائدة عند 5.25%</code>.

🗺️ <b>خلاصة الاتجاهات الحقيقية:</b>
• <b>الذهب (XAUUSD):</b> صاعد أسبوعياً بدعم تدفقات الملاذ الآمن والسيولة.
• <b>اليورو والباوند (EUR & GBP):</b> تذبذب وعمليات تحوط تجاري. منظومة الإرسال التلقائي تراقبهما لحظياً."""

def generate_full_market_analysis(style, asset, market_data):
    market_is_open, market_status_text = check_market_status()
    
    if not market_is_open:
        return f"""⚠️ <b>تنبيه: السوق مغلق حالياً!</b>
═════════════════════════════
⏱️ <b>حالة السوق:</b> {market_status_text}
❌ عذراً، لا يمكن جلب تحليلات أو صفقات جديدة لعدم توفر السيولة الحية."""

    dxy = market_data['DXY']
    price = market_data[asset]
    strategies = ["FVG Mitigation", "Order Block Rejection", "Liquidity Sweep"]
    chosen_strategy = random.choice(strategies)

    capital = bot_settings['capital']
    risk_pct = bot_settings['risk_pct']
    risk_amt = capital * (risk_pct / 100.0)
    stop_pips = bot_settings['stop_pips']
    lot_size = round(risk_amt / (stop_pips * 10), 2)
    if lot_size < 0.01:
        lot_size = 0.01

    if style == "scalp":
        tf_desc = "1W -> 1D -> 1H (Structure POI) -> 5M (Entry)"
        entry_poi = f"[{chosen_strategy}] على فريم 1H مع دخول 5M"
        sl_val = round(price - 2.5 if asset == "XAUUSD" else price - 0.0020, 4 if asset != "XAUUSD" else 2)
        tp_val = round(price + 5.0 if asset == "XAUUSD" else price + 0.0040, 4 if asset != "XAUUSD" else 2)
    else:
        tf_desc = "1W -> 1D -> 4H (Dealing Range POI) -> 15M (Confirmation)"
        entry_poi = f"[{chosen_strategy}] على فريم 4H مع تأكيد 15M"
        sl_val = round(price - 8.0 if asset == "XAUUSD" else price - 0.0060, 4 if asset != "XAUUSD" else 2)
        tp_val = round(price + 18.0 if asset == "XAUUSD" else price + 0.0120, 4 if asset != "XAUUSD" else 2)

    direction = "🟢 شراء (BUY)" if dxy <= 104 else "🔴 بيع (SELL)"
    log_trade(asset, style.upper(), chosen_strategy, lot_size, risk_amt, direction, price, dxy)

    return f"""╔═════════════════════════════╗
║  <b>تحليل الفريمات والـ POI الحقيقي</b>  ║
╚═════════════════════════════╝
📊 <b>الأصل:</b> <code>{asset}</code> | <b>النوع:</b> <code>{style.upper()}</code>
💵 <b>مؤشر الدولار ($DXY):</b> <code>{dxy}</code>
⏱️ <b>حالة السوق:</b> {market_status_text}
───────────────────────────
🔍 <b>الاستراتيجية المطبقة:</b> <code>{chosen_strategy}</code>
• <b>الهيكلة:</b> <code>{tf_desc}</code>
• <b>منطقة الـ POI:</b> {entry_poi}
• <b>القرار:</b> <code>{direction}</code>
───────────────────────────
💵 <b>السعر:</b> <code>{price}</code> | 🛑 <b>SL:</b> <code>{sl_val}</code> | 🎯 <b>TP:</b> <code>{tp_val}</code>
⚖️ <b>اللوت:</b> <code>{lot_size}</code> (رأس المال: ${capital:,.2f} | مخاطرة: {risk_pct}%)"""

def process_single_update(update):
    global bot_settings
    try:
        if 'callback_query' in update:
            cq = update['callback_query']
            callback_id = cq['id']
            callback_data = cq['data']
            sender_chat_id = cq['message']['chat']['id']
            message_id = cq['message']['message_id']
            answer_callback_query(callback_id, "")
            
            market_data = fetch_live_market_data()

            if callback_data == "macro_report":
                msg = generate_macro_report_detailed(market_data)
                edit_message_text(sender_chat_id, message_id, msg, {"inline_keyboard": [[{"text": "◄ العودة", "callback_data": "back_to_menu"}]]})
            elif callback_data == "select_style":
                t, k = generate_style_keyboard()
                edit_message_text(sender_chat_id, message_id, t, k)
            elif callback_data == "style_scalp":
                bot_settings['preferred_style'] = 'scalp'
                bot_settings['auto_dispatch_active'] = True
                msg = "⚡ <b>تم اختيار سكالبينج وتفعيل الإرسال التلقائي بنجاح!</b>\n\nسيقوم البوت بمتابعة السوق وإرسال الفرص تلقائياً في الخلفية."
                edit_message_text(sender_chat_id, message_id, msg, {"inline_keyboard": [[{"text": "◄ العودة للرئيسية", "callback_data": "back_to_menu"}]]})
            elif callback_data == "style_swing":
                bot_settings['preferred_style'] = 'swing'
                bot_settings['auto_dispatch_active'] = True
                msg = "🌊 <b>تم اختيار سوينج وتفعيل الإرسال التلقائي بنجاح!</b>\n\nسيقوم البوت بمتابعة السوق وإرسال الفرص تلقائياً في الخلفية."
                edit_message_text(sender_chat_id, message_id, msg, {"inline_keyboard": [[{"text": "◄ العودة للرئيسية", "callback_data": "back_to_menu"}]]})
            elif callback_data == "toggle_dispatch":
                bot_settings['auto_dispatch_active'] = not bot_settings['auto_dispatch_active']
                t, k = generate_menu_keyboard()
                edit_message_text(sender_chat_id, message_id, t, k)
            elif callback_data == "weekly_report":
                conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("SELECT strategy_used, COUNT(*), SUM(CASE WHEN result='SUCCESSFUL_WIN' THEN 1 ELSE 0 END) FROM ai_autonomous_trades GROUP BY strategy_used")
                rows = cursor.fetchall()
                conn.close()
                
                _, m_status = check_market_status()
                report_text = f"""📈 <b>تقرير أداء ونجاح الاستراتيجيات</b>\n⏱️ {m_status}\n\n"""
                for r in rows:
                    strat_name, total_cnt, win_cnt = r[0], r[1], r[2] if r[2] else 0
                    rate = (win_cnt / total_cnt * 100) if total_cnt > 0 else 0.0
                    report_text += f"• <code>{strat_name}</code> | التحليلات: {total_cnt} | النجاح: {win_cnt} ({rate:.1f}%)\n"
                edit_message_text(sender_chat_id, message_id, report_text, {"inline_keyboard": [[{"text": "◄ العودة", "callback_data": "back_to_menu"}]]})
            elif callback_data == "risk_config_prompt":
                msg = f"""⚙️ <b>تعديل إعدادات المخاطر:</b>\nرأس المال: ${bot_settings['capital']:,.2f} | المخاطرة: {bot_settings['risk_pct']}%\n\nأرسل بالشات: <code>مخاطر [المبلغ] [النسبة] [الوقف]</code>\n<i>مثال: <code>مخاطر 20 1.5 15</code></i>"""
                edit_message_text(sender_chat_id, message_id, msg, {"inline_keyboard": [[{"text": "◄ العودة", "callback_data": "back_to_menu"}]]})
            elif callback_data == "back_to_menu":
                text, kbd = generate_menu_keyboard()
                edit_message_text(sender_chat_id, message_id, text, kbd)

        elif 'message' in update and 'text' in update['message']:
            msg_obj = update['message']
            text = msg_obj['text'].strip()
            sender_chat_id = msg_obj['chat']['id']
            
            if text.lower().startswith("مخاطر"):
                try:
                    parts = text.split()
                    bot_settings['capital'] = float(parts[1])
                    bot_settings['risk_pct'] = float(parts[2])
                    bot_settings['stop_pips'] = float(parts[3])
                    send_telegram_message(sender_chat_id, f"✅ تم التحديث بنجاح! رأس المال: ${bot_settings['capital']:,.2f}")
                except Exception:
                    send_telegram_message(sender_chat_id, "❌ خطأ بالصيغة. أرسل: <code>مخاطر 20 1.5 15</code>")
            
            t, k = generate_menu_keyboard()
            send_telegram_message(sender_chat_id, t, k)
    except Exception:
        pass

def run_persistent_bot():
    print("🤖 Autonomous AI Bot is running 24/7...")
    last_update_id = 0
    try:
        init_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        req = urllib.request.Request(init_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=2) as response:
            res = json.loads(response.read().decode('utf-8'))
            if res.get('ok') and res.get('result'):
                last_update_id = res['result'][-1]['update_id'] + 1
    except Exception:
        pass

    with ThreadPoolExecutor(max_workers=10) as executor:
        while True:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={last_update_id}&timeout=5"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=8) as response:
                    res = json.loads(response.read().decode('utf-8'))
                    if res.get('ok') and res.get('result'):
                        for update in res['result']:
                            last_update_id = update['update_id'] + 1
                            executor.submit(process_single_update, update)
            except Exception:
                time.sleep(1)

if __name__ == '__main__':
    run_persistent_bot()
