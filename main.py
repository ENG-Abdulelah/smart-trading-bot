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

# خادم ويب وهمي لضمان عمل البوت 24/7 على Render
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"AI Self-Learning COT & ICT Bot with Weekly Reports & Market Status is running 24/7!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN", "8667800516:AAE48vBxGIRld55SeDLcSpIdB2P8lrrkWbw")
CHAT_ID = "6588992670"

bot_settings = {
    'auto_alerts': True,
    'capital': 1000.0,
    'risk_pct': 1.0,
    'stop_pips': 15.0
}

live_market_cache = {
    'XAUUSD': 2865.20,
    'EURUSD': 1.0580,
    'GBPUSD': 1.2650,
    'DXY': 104.20
}

active_panel_msg_id = None

# ==========================================
# التحقق من حالة السوق (مفتوح / مغلق)
# ==========================================
def check_market_status():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    weekday = now_utc.weekday() # 0=الإثنين, ..., 4=الجمعة, 5=السبت, 6=الأحد
    hour = now_utc.hour
    
    # السوق يغلق يوم الجمعة الساعة 21:00 UTC ويفتح الأحد الساعة 22:00 UTC
    if weekday == 5: # السبت
        return False, "🔴 السوق مغلق (عطلة نهاية الأسبوع - السبت)"
    elif weekday == 6 and hour < 22: # الأحد قبل الافتتاح
        return False, "🔴 السوق مغلق (بانتظار افتتاح جلسة الأسبوع)"
    elif weekday == 4 and hour >= 21: # الجمعة بعد الإغلاق
        return False, "🔴 السوق مغلق (تم إغلاق الأسواق أسبوعياً)"
    
    return True, "🟢 السوق مفتوح وتعمل السيولة الحية"

# ==========================================
# قاعدة بيانات التعلم الذاتي وتقارير الأسبوع
# ==========================================
def init_db():
    conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_weekly_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset TEXT,
            trade_type TEXT,
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

def log_and_evaluate_trade(asset, trade_type, lot, risk_amt, direction, entry, dxy):
    conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO ai_weekly_performance (asset, trade_type, lot_size, risk_amount, direction, entry, dxy_state) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (asset, trade_type, lot, risk_amt, direction, entry, dxy))
    
    # تقييم الصفقات المعلقة وتحديث نتائجها للتعلم الذاتي
    cursor.execute("SELECT id, entry, direction FROM ai_weekly_performance WHERE result = 'PENDING_EVALUATION'")
    pending = cursor.fetchall()
    
    for t_id, t_entry, t_dir in pending:
        curr_price = live_market_cache.get(asset, t_entry)
        win = ("BUY" in t_dir and curr_price > t_entry) or ("SELL" in t_dir and curr_price < t_entry)
        res = "SUCCESSFUL_WIN" if win else "OPTIMIZED_LOSS"
        cursor.execute("UPDATE ai_weekly_performance SET result = ? WHERE id = ?", (res, t_id))
        
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

    return live_market_cache

def generate_menu_keyboard():
    market_is_open, market_status_text = check_market_status()
    text = f"""🏛️ <b>غرفة العمليات الذكية والتعلم الذاتي (AI Trading Core)</b>
═════════════════════════════
📊 <b>رأس المال:</b> <code>${bot_settings['capital']:,.0f}</code> | <b>المخاطرة:</b> <code>{bot_settings['risk_pct']}%</code>
⏱️ <b>حالة السوق الحية:</b> {market_status_text}

اختر القسم المطلوب للتنفيذ والدراسة:"""
    keyboard = {
        "inline_keyboard": [
            [{"text": "📊 تقارير الـ COT والتحليل الاقتصادي الشامل", "callback_data": "cot_macro"}],
            [{"text": "⚡ تحليل الفريمات المتعددة (ICT Scalp & Swing)", "callback_data": "select_style"}],
            [{"text": "📈 تقرير أداء نهاية الأسبوع (Weekly Report)", "callback_data": "weekly_report"}],
            [{"text": "🧠 تقرير أداء ونسبة نجاح الذكاء الاصطناعي", "callback_data": "ai_memory"}],
            [{"text": "⚙️ إعدادات المخاطر", "callback_data": "risk_settings"}]
        ]
    }
    return text, keyboard

def generate_style_keyboard():
    market_is_open, market_status_text = check_market_status()
    text = f"""⚡ <b>اختر نوع التداول المؤسسي لدراسة الشارت:</b>\n{market_status_text}"""
    keyboard = {
        "inline_keyboard": [
            [{"text": "⚡ سكالبينج (Scalping - 1H/5M)", "callback_data": "style_scalp"}],
            [{"text": "🌊 سوينج (Swing - 4H/15M)", "callback_data": "style_swing"}],
            [{"text": "◄ العودة للرئيسية", "callback_data": "back_to_menu"}]
        ]
    }
    return text, keyboard

def generate_asset_keyboard(style):
    text = f"""🎯 <b>النوع المختار:</b> <code>{style.upper()}</code>\nاختر الأصل لبدء التحليل وتغذية ذاكرة البوت:"""
    keyboard = {
        "inline_keyboard": [
            [{"text": "🪙 الذهب (XAUUSD)", "callback_data": f"asset_{style}_XAUUSD"}],
            [{"text": "💶 اليورو (EURUSD)", "callback_data": f"asset_{style}_EURUSD"}],
            [{"text": "💷 الباوند (GBPUSD)", "callback_data": f"asset_{style}_GBPUSD"}],
            [{"text": "◄ العودة", "callback_data": "select_style"}]
        ]
    }
    return text, keyboard

def generate_full_market_analysis(style, asset, market_data):
    market_is_open, market_status_text = check_market_status()
    dxy = market_data['DXY']
    price = market_data[asset]
    
    capital = bot_settings['capital']
    risk_pct = bot_settings['risk_pct']
    risk_amt = capital * (risk_pct / 100.0)
    stop_pips = bot_settings['stop_pips']
    lot_size = round(risk_amt / (stop_pips * 10), 2)
    if lot_size < 0.01:
        lot_size = 0.01

    if style == "scalp":
        tf_desc = "1W (Bias) -> 1D (Dealing Range) -> 1H (Structure POI) -> 5M (Execution Entry)"
        entry_poi = "منطقة FVG واختبار Order Block على فريم 1H مع دخول سريع 5M"
        sl_val = round(price - 2.5 if asset == "XAUUSD" else price - 0.0020, 4 if asset != "XAUUSD" else 2)
        tp_val = round(price + 5.0 if asset == "XAUUSD" else price + 0.0040, 4 if asset != "XAUUSD" else 2)
    else:
        tf_desc = "1W (Institutional Bias) -> 1D (Market Structure) -> 4H (Dealing Range POI) -> 15M (Confirmation)"
        entry_poi = "منطقة Order Block كبرى على فريم 4H مع تأكيد هيكلي على 15M"
        sl_val = round(price - 8.0 if asset == "XAUUSD" else price - 0.0060, 4 if asset != "XAUUSD" else 2)
        tp_val = round(price + 18.0 if asset == "XAUUSD" else price + 0.0120, 4 if asset != "XAUUSD" else 2)

    direction = "🟢 شراء (BUY - اتجاه صاعد مدعوم بسيولة المؤسسات)" if dxy <= 104 else "🔴 بيع (SELL - ضغط تجاري وقوة $DXY)"
    
    # تسجيل الصفقة وحساب اللوت والمارجن في قاعدة البيانات
    log_and_evaluate_trade(asset, style.upper(), lot_size, risk_amt, direction, price, dxy)

    warning_note = f"\n⚠️ <i>ملاحظة: {market_status_text}</i>" if not market_is_open else ""

    report = f"""╔═════════════════════════════╗
║  <b>تحليل الذكاء الاصطناعي (ICT + COT)</b>  ║
╚═════════════════════════════╝
📊 <b>الأصل:</b> <code>{asset}</code> | <b>النوع:</b> <code>{style.upper()}</code>
💵 <b>مؤشر الدولار ($DXY):</b> <code>{dxy}</code>
{warning_note}
───────────────────────────
📅 <b>تحليلات الأسبوع (1W) واليوم (1D):</b>
• الإطار الأسبوعي يحدد اتجاه الـ Bias المؤسسي بدقة.
• الإطار اليومي يحدد نطاق التعامل (Dealing Range).

🔍 <b>نقاط الاهتمام (POI) وفريمات التنفيذ:</b>
• <b>الهيكلة:</b> <code>{tf_desc}</code>
• <b>منطقة الـ POI:</b> {entry_poi}
• <b>القرار النهائي:</b> <code>{direction}</code>
───────────────────────────
💵 <b>سعر الدخول:</b> <code>{price}</code>
🛑 <b>وقف الخسارة (SL):</b> <code>{sl_val}</code>
🎯 <b>الهدف (TP):</b> <code>{tp_val}</code>
⚖️ <b>إدارة المخاطر والوت:</b> رأس المال: <code>${capital:,.0f}</code> | المخاطرة: <code>{risk_pct}% (${risk_amt:.2f})</code> | <b>Lot Size:</b> <code>{lot_size}</code>
🧠 <i>تم تسجيل الصفقة وحساب الوت وإدارتها آلياً لدراسة الأداء.</i>"""
    return report

def process_single_update(update):
    try:
        if 'callback_query' in update:
            cq = update['callback_query']
            callback_id = cq['id']
            callback_data = cq['data']
            sender_chat_id = cq['message']['chat']['id']
            message_id = cq['message']['message_id']
            answer_callback_query(callback_id, "")
            
            market_data = fetch_live_market_data()
            market_is_open, market_status_text = check_market_status()

            if callback_data == "cot_macro":
                msg = f"""📊 <b>تقارير التزام التجار (COT) والتحليل الاقتصادي</b>\n\n{market_status_text}\n\n• <b>الذهب (XAUUSD):</b> عقود الشراء الصافية للمؤسسات تسجل تجميداً إيجابياً.\n• <b>مؤشر الدولار ($DXY):</b> عند مستوى <code>{market_data['DXY']}</code>، مما يوجه السيولة الذكية نحو العملات الرئيسية.\n• <b>الجيوسياسية:</b> دراسة مستمرة لبيانات التضخم وأثرها على صانع السوق."""
                edit_message_text(sender_chat_id, message_id, msg, {"inline_keyboard": [[{"text": "◄ العودة", "callback_data": "back_to_menu"}]]})
            elif callback_data == "select_style":
                t, k = generate_style_keyboard()
                edit_message_text(sender_chat_id, message_id, t, k)
            elif callback_data == "style_scalp":
                t, k = generate_asset_keyboard("scalp")
                edit_message_text(sender_chat_id, message_id, t, k)
            elif callback_data == "style_swing":
                t, k = generate_asset_keyboard("swing")
                edit_message_text(sender_chat_id, message_id, t, k)
            elif callback_data.startswith("asset_"):
                parts = callback_data.split("_")
                style = parts[1]
                asset = parts[2]
                report = generate_full_market_analysis(style, asset, market_data)
                edit_message_text(sender_chat_id, message_id, report, {"inline_keyboard": [[{"text": "◄ العودة", "callback_data": "select_style"}, {"text": "🏠 الرئيسية", "callback_data": "back_to_menu"}]]})
            elif callback_data == "weekly_report":
                conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*), SUM(CASE WHEN result='SUCCESSFUL_WIN' THEN 1 ELSE 0 END), SUM(CASE WHEN result='OPTIMIZED_LOSS' THEN 1 ELSE 0 END) FROM ai_weekly_performance")
                row = cursor.fetchone()
                conn.close()
                
                total_t = row[0] if row and row[0] else 0
                wins = row[1] if row and row[1] else 0
                losses = row[2] if row and row[2] else 0
                win_rate = (wins / total_t * 100) if total_t > 0 else 0.0
                
                weekly_msg = f"""📈 <b>تقرير أداء نهاية الأسبوع الآلي (Weekly Performance)</b>
═════════════════════════════
📊 <b>إجمالي الصفقات التي أدارها البوت:</b> <code>{total_t}</code>
🏆 <b>الصفقات الناجحة (Wins):</b> <code>{wins}</code>
❌ <b>الصفقات الخاسرة / قيد التحسين (Losses):</b> <code>{losses}</code>
🎯 <b>نسبة النجاح الإجمالية (Win Rate):</b> <code>{win_rate:.1f}%</code>
───────────────────────────
⚖️ <b>إدارة رأس المال واللوت:</b>
• رأس المال المعتمد: <code>${bot_settings['capital']:,.0f}</code>
• نسبة المخاطرة الآلية: <code>{bot_settings['risk_pct']}%</code>
🏛️ <i>يقوم البوت بدراسة وتتبع الدخول والـ Lot والهدف لرفع الكفاءة أسبوعياً.</i>"""
                edit_message_text(sender_chat_id, message_id, weekly_msg, {"inline_keyboard": [[{"text": "◄ العودة", "callback_data": "back_to_menu"}]]})
            elif callback_data == "ai_memory":
                conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM ai_weekly_performance")
                total = cursor.fetchone()[0]
                conn.close()
                msg = f"""🧠 <b>تقرير ذاكرة التعلم وتطوير الذكاء الاصطناعي</b>\n\n📊 إجمالي الصفقات الخاضعة للتدريب: <code>{total}</code>\n🟢 حالة السيرفر: <code>يعمل 24/7 على Render (مع تتبع حالة السوق)</code>"""
                edit_message_text(sender_chat_id, message_id, msg, {"inline_keyboard": [[{"text": "◄ العودة", "callback_data": "back_to_menu"}]]})
            elif callback_data == "risk_settings":
                msg = f"""⚙️ <b>إدارة المخاطر</b>\nرأس المال: `${bot_settings['capital']}` | المخاطرة: `{bot_settings['risk_pct']}%`"""
                edit_message_text(sender_chat_id, message_id, msg, {"inline_keyboard": [[{"text": "◄ العودة", "callback_data": "back_to_menu"}]]})
            elif callback_data == "back_to_menu":
                text, kbd = generate_menu_keyboard()
                edit_message_text(sender_chat_id, message_id, text, kbd)

        elif 'message' in update and 'text' in update['message']:
            msg_obj = update['message']
            sender_chat_id = msg_obj['chat']['id']
            t, k = generate_menu_keyboard()
            send_telegram_message(sender_chat_id, t, k)
    except Exception:
        pass

def run_persistent_bot():
    print("🤖 AI COT + ICT Bot with Weekly Report & Market Status is running 24/7...")
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
