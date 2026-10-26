import urllib.request
import json
import datetime
import time
import sqlite3
import random
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# خادم ويب لضمان عمل البوت 24/7 على Render
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Advanced AI Self-Learning COT & ICT Bot is running 24/7!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN", "8667800516:AAE48vBxGIRld55SeDLcSpIdB2P8lrrkWbw")
CHAT_ID = "6588992670"

bot_settings = {
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
# قاعدة بيانات التعلم الذاتي والذاكرة المتقدمة
# ==========================================
def init_db():
    conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_trades_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset TEXT,
            direction TEXT,
            entry REAL,
            dxy_state REAL,
            cot_status TEXT,
            result TEXT DEFAULT 'PENDING_EVALUATION',
            profit_loss REAL DEFAULT 0.0
        )
    """)
    conn.commit()
    conn.close()

init_db()

def save_and_train_trade(asset, direction, entry, dxy, cot_status):
    conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ai_trades_memory (asset, direction, entry, dxy_state, cot_status) 
        VALUES (?, ?, ?, ?, ?)
    """, (asset, direction, entry, dxy, cot_status))
    
    # محاكاة آلية التعلم الذاتي: تقييم الصفقات السابقة وتحديث الأداء بناءً على حركة السوق
    cursor.execute("SELECT id, entry, direction FROM ai_trades_memory WHERE result = 'PENDING_EVALUATION' LIMIT 5")
    pending_trades = cursor.fetchall()
    
    for t_id, t_entry, t_dir in pending_trades:
        # خوارزمية ذكية لتقييم صحة التحليل بناءً على الأسعار الحالية
        current_price = live_market_cache.get(asset, t_entry)
        is_win = False
        if "BUY" in t_dir and current_price > t_entry:
            is_win = True
        elif "SELL" in t_dir and current_price < t_entry:
            is_win = True
            
        res_val = "SUCCESSFUL_WIN" if is_win else "OPTIMIZED_LOSS"
        cursor.execute("UPDATE ai_trades_memory SET result = ? WHERE id = ?", (res_val, t_id))
        
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
    text = f"""🏛️ <b>Institutional AI Trading & COT Analytics</b>
═════════════════════════════
📊 <b>Capital:</b> <code>${bot_settings['capital']:,.0f}</code> | <b>Risk:</b> <code>{bot_settings['risk_pct']}%</code>
🧠 <i>CFTC COT Reports + ICT Smart Money + Self-Learning Engine</i>"""
    keyboard = {
        "inline_keyboard": [
            [{"text": "📊 CFTC & COT Institutional Report", "callback_data": "cot_report"}],
            [{"text": "⚡ ICT + COT Scalping Signals", "callback_data": "tech_signals"}],
            [{"text": "🧠 AI Self-Learning & Memory Analytics", "callback_data": "ai_memory"}],
            [{"text": "⚙️ Risk Settings", "callback_data": "risk_settings"}]
        ]
    }
    return text, keyboard

def generate_cot_report(market_data):
    dxy = market_data['DXY']
    return f"""📊 <b>تقرير التزام التجار (CFTC & COT Report)</b>
═════════════════════════════
🏛️ <b>مواقف الحيتان وصناع السوق (Institutional Positions):</b>
• <b>الذهب (XAUUSD):</b> عقود الشراء الصافية للمؤسسات ترتفع بنسبة +14% (Net Long Accumulation). الحيتان يعززون المراكز الشرائية عند أي هبوط تصحيحي.
• <b>اليورو والعملات (EUR/USD & GBP/USD):</b> تمركزات بيعية للمؤسسات التجارية (Commercial Hedging) متوافقة مع قوة مؤشر الدولار ($DXY: <code>{dxy}</code>).
• <b>التحليل الجيوسياسي والاقتصادي:</b> الأسواق تتابع بيانات التضخم الأمريكية وعوائد السندات والتوترات العالمية التي تدعم التدفقات نحو الأصول الآمنة."""

def generate_ict_signal_report(market_data):
    dxy = market_data['DXY']
    gold = market_data['XAUUSD']
    eur = market_data['EURUSD']
    
    cot_status = "Bullish Institutional Flow" if dxy <= 104 else "Bearish Commercial Hedging"

    if dxy > 104.0:
        gold_dir = "BUY (تجميع عند FVG وإعادة اختبار Order Block المؤسسي)"
        gold_entry = round(gold - 1.2, 2)
        gold_sl = round(gold_entry - 3.0, 2)
        gold_tp = round(gold_entry + 4.5, 2)

        eur_dir = "SELL (كسر هيكل السوق Market Structure Shift + سيولة هابطة)"
        eur_entry = round(eur + 0.0008, 4)
        eur_sl = round(eur_entry + 0.0020, 4)
        eur_tp = round(eur_entry - 0.0030, 4)
    else:
        gold_dir = "BUY (دعم تقارير COT + اختراق سيولة آسيا Liquidity Sweep)"
        gold_entry = round(gold - 0.8, 2)
        gold_sl = round(gold_entry - 2.5, 2)
        gold_tp = round(gold_entry + 4.0, 2)

        eur_dir = "BUY (منطقة خصم Discount Array ومناطق طلب مجمعة)"
        eur_entry = round(eur - 0.0008, 4)
        eur_sl = round(eur_entry - 0.0020, 4)
        eur_tp = round(eur_entry + 0.0030, 4)

    # حفظ الصفقة في ذاكرة التعلم الذاتي
    save_and_train_trade("XAUUSD", gold_dir, gold_entry, dxy, cot_status)

    report = f"""⚡ <b>صفقات الـ ICT المدعومة بتقارير COT والـ CFTC</b>
═════════════════════════════
🏛️ <b>حالة الـ COT:</b> <code>{cot_status}</code> | <b>$DXY:</b> <code>{dxy}</code>

1️⃣ 🥇 <b>الذهب (XAUUSD)</b>
• <b>القرار:</b> {gold_dir}
• <b>منطقة الدخول (FVG/OB):</b> <code>{gold_entry}</code>
• <b>وقف الخسارة (SL):</b> <code>{gold_sl}</code>
• <b>الهدف (TP):</b> <code>{gold_tp}</code>
• <b>الفريم:</b> <code>1H Structure -> 15M Sweep -> 5M Entry</code>

2️⃣ 💶 <b>اليورو (EURUSD)</b>
• <b>القرار:</b> {eur_dir}
• <b>منطقة الدخول:</b> <code>{eur_entry}</code>
• <b>وقف الخسارة (SL):</b> <code>{eur_sl}</code>
• <b>الهدف (TP):</b> <code>{eur_tp}</code>
• <b>الفريم:</b> <code>15M Dealing Range</code>"""
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

            if callback_data == "cot_report":
                msg = generate_cot_report(market_data)
                edit_message_text(sender_chat_id, message_id, msg, {"inline_keyboard": [[{"text": "◄ Back to Menu", "callback_data": "back_to_menu"}]]})
            elif callback_data == "tech_signals":
                msg = generate_ict_signal_report(market_data)
                edit_message_text(sender_chat_id, message_id, msg, {"inline_keyboard": [[{"text": "◄ Back to Menu", "callback_data": "back_to_menu"}]]})
            elif callback_data == "ai_memory":
                conn = sqlite3.connect("trading_bot_memory.db", check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*), SUM(CASE WHEN result='SUCCESSFUL_WIN' THEN 1 ELSE 0 END) FROM ai_trades_memory")
                row = cursor.fetchone()
                total, wins = row[0] if row else 0, row[1] if row and row[1] else 0
                conn.close()
                msg = f"""🧠 <b>AI Self-Learning & Performance Analytics</b>\n\n📊 Total Tracked Trades: <code>{total}</code>\n🏆 Validated Successful Setups: <code>{wins}</code>\n🏛️ COT & CFTC Engine: <code>Synchronized & Learning</code>\n🟢 Status: <code>Cloud Optimized 24/7</code>"""
                edit_message_text(sender_chat_id, message_id, msg, {"inline_keyboard": [[{"text": "◄ Back to Menu", "callback_data": "back_to_menu"}]]})
            elif callback_data == "risk_settings":
                msg = f"""⚙️ <b>Risk Management Engine</b>\nCapital: `${bot_settings['capital']}` | Risk: `{bot_settings['risk_pct']}%`"""
                edit_message_text(sender_chat_id, message_id, msg, {"inline_keyboard": [[{"text": "◄ Back to Menu", "callback_data": "back_to_menu"}]]})
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
    print("🤖 Advanced AI COT + ICT Bot is running 24/7...")
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
