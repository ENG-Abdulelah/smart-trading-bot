#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Config module — all static constants, seed data, and shared immutable definitions.
"""

import os
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", os.path.join("data", "trading_engine.db"))
PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HTTP_TIMEOUT = 6.0

SYMBOLS = {
    "XAU/USD": {"yahoo": "GC=F", "spot_code": "XAU", "metals_spot": True,
                "base": 2350.0, "decimals": 2, "mult": 100, "pip": 0.01,
                "spread": 0.30, "label_en": "Gold", "label_ar": "الذهب"},
    "XAG/USD": {"yahoo": "SI=F", "spot_code": "XAG", "metals_spot": True,
                "base": 27.50, "decimals": 3, "mult": 1000, "pip": 0.01,
                "spread": 0.020, "label_en": "Silver", "label_ar": "الفضة"},
    "EUR/USD": {"yahoo": "EURUSD=X", "spot_code": None, "metals_spot": False,
                "base": 1.0850, "decimals": 5, "mult": 100000, "pip": 0.0001,
                "spread": 0.00008, "label_en": "Euro", "label_ar": "اليورو"},
    "GBP/USD": {"yahoo": "GBPUSD=X", "spot_code": None, "metals_spot": False,
                "base": 1.2700, "decimals": 5, "mult": 100000, "pip": 0.0001,
                "spread": 0.00010, "label_en": "Sterling", "label_ar": "الإسترليني"},
    "USD/JPY": {"yahoo": "USDJPY=X", "spot_code": None, "metals_spot": False,
                "base": 155.00, "decimals": 3, "mult": 1000, "pip": 0.01,
                "spread": 0.015, "label_en": "Yen", "label_ar": "الين"},
    "DXY":     {"yahoo": "DX-Y.NYB", "spot_code": None, "metals_spot": False,
                "base": 105.00, "decimals": 3, "mult": 1000, "pip": 0.01,
                "spread": 0.020, "label_en": "Dollar Index", "label_ar": "مؤشر الدولار"},
}

TRADEABLE_SYMBOLS = frozenset({"XAU/USD", "XAG/USD", "EUR/USD", "GBP/USD", "USD/JPY"})

PRICE_BOUNDS = {
    "XAU/USD": (1000.0, 6000.0), "XAG/USD": (5.0, 200.0),
    "EUR/USD": (0.50, 2.00), "GBP/USD": (0.70, 2.50),
    "USD/JPY": (70.0, 300.0), "DXY": (70.0, 140.0),
}

TRADE_MODES = {
    "SCALPING_A": {"label_en": "Scalping Mode A", "label_ar": "سكالبينج النمط أ",
                   "htf": ["1W", "1D", "1H"], "entry_tfs": ["M5"]},
    "SCALPING_B": {"label_en": "Scalping Mode B", "label_ar": "سكالبينج النمط ب",
                   "htf": ["1W", "1D", "4H"], "entry_tfs": ["M15", "M1"]},
    "SWING":      {"label_en": "Swing", "label_ar": "سوينج",
                   "htf": ["1W", "1D"], "entry_tfs": ["H1", "H4"]},
}

ICT_STRATEGIES = [
    "Liquidity Sweep & Stop Hunt",
    "Fair Value Gap (FVG)",
    "Order Block (OB)",
    "Change of Character (CHoCH)",
    "Market Structure Shift (MSS)",
    "Break of Structure (BOS)",
    "Breaker Block",
    "Mitigation Block",
    "Balanced Price Range (BPR)",
    "Volume Gap",
    "Inducement (IDM)",
    "Judas Swing / ORL",
    "Kill Zones & Power of 3",
    "Silver Bullet Strategy",
    "Optimal Trade Entry (OTE)",
    "Premium & Discount Zones",
    "Inversion FVG (IFVG)",
    "Institutional Order Flow (IOF)",
    "Quarterly Theory / IPDA",
    "Daily Bias Framework",
]

STRATEGY_AR = {
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
}

ANTI_USD_SYMBOLS = ("XAU/USD", "XAG/USD", "EUR/USD", "GBP/USD")
PRO_USD_SYMBOLS = ("USD/JPY", "DXY")

NEWS_BLACKOUT_BEFORE_MIN = 5
NEWS_BLACKOUT_AFTER_MIN = 10

BIAS_GUARDRAIL_THRESHOLD = 60.0

CB_STATE_SEED = {
    "FED": {"name_en": "Federal Reserve", "name_ar": "الاحتياطي الفيدرالي",
            "currency": "USD", "rate": 4.375, "next_days": 17,
            "cut": 55.0, "hold": 40.0, "hike": 5.0},
    "ECB": {"name_en": "European Central Bank", "name_ar": "البنك المركزي الأوروبي",
            "currency": "EUR", "rate": 3.250, "next_days": 11,
            "cut": 70.0, "hold": 28.0, "hike": 2.0},
    "BOE": {"name_en": "Bank of England", "name_ar": "بنك إنجلترا",
            "currency": "GBP", "rate": 4.750, "next_days": 22,
            "cut": 60.0, "hold": 36.0, "hike": 4.0},
    "BOJ": {"name_en": "Bank of Japan", "name_ar": "بنك اليابان",
            "currency": "JPY", "rate": 0.500, "next_days": 27,
            "cut": 5.0, "hold": 65.0, "hike": 30.0},
}

COT_STATE_SEED = {
    "Gold":   {"long": 224850, "short": 78200, "prev_long": 221000, "prev_short": 81500,
               "label_ar": "الذهب", "source": "seed"},
    "Silver": {"long": 68500, "short": 31200, "prev_long": 67200, "prev_short": 32400,
               "label_ar": "الفضة", "source": "seed"},
    "EUR":    {"long": 165300, "short": 112400, "prev_long": 168100, "prev_short": 108700,
               "label_ar": "اليورو", "source": "seed"},
    "GBP":    {"long": 72400, "short": 58100, "prev_long": 70200, "prev_short": 61300,
               "label_ar": "الإسترليني", "source": "seed"},
    "JPY":    {"long": 48600, "short": 118900, "prev_long": 52100, "prev_short": 115400,
               "label_ar": "الين", "source": "seed"},
}

CALENDAR_SEED = [
    {"month": 1, "day": 28, "event_en": "FOMC Rate Decision", "event_ar": "قرار الفائدة الفيدرالي", "currency": "USD", "impact": "HIGH", "forecast": "3.75%", "previous": "4.00%"},
    {"month": 3, "day": 18, "event_en": "FOMC Rate Decision", "event_ar": "قرار الفائدة الفيدرالي", "currency": "USD", "impact": "HIGH", "forecast": "3.75%", "previous": "3.75%"},
    {"month": 4, "day": 29, "event_en": "FOMC Rate Decision", "event_ar": "قرار الفائدة الفيدرالي", "currency": "USD", "impact": "HIGH", "forecast": "3.50%", "previous": "3.75%"},
    {"month": 6, "day": 17, "event_en": "FOMC Rate Decision", "event_ar": "قرار الفائدة الفيدرالي", "currency": "USD", "impact": "HIGH", "forecast": "3.50%", "previous": "3.50%"},
    {"month": 9, "day": 16, "event_en": "FOMC Rate Decision", "event_ar": "قرار الفائدة الفيدرالي", "currency": "USD", "impact": "HIGH", "forecast": "3.25%", "previous": "3.50%"},
    {"month": 12, "day": 16, "event_en": "FOMC Rate Decision", "event_ar": "قرار الفائدة الفيدرالي", "currency": "USD", "impact": "HIGH", "forecast": "3.25%", "previous": "3.25%"},
    {"month": 1, "day": 2, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "175K", "previous": "160K"},
    {"month": 2, "day": 6, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "180K", "previous": "175K"},
    {"month": 3, "day": 6, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "185K", "previous": "180K"},
    {"month": 4, "day": 3, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "190K", "previous": "185K"},
    {"month": 5, "day": 1, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "185K", "previous": "190K"},
    {"month": 6, "day": 5, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "180K", "previous": "185K"},
    {"month": 7, "day": 3, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "175K", "previous": "180K"},
    {"month": 8, "day": 7, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "180K", "previous": "175K"},
    {"month": 9, "day": 4, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "185K", "previous": "180K"},
    {"month": 10, "day": 2, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "190K", "previous": "185K"},
    {"month": 11, "day": 6, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "185K", "previous": "190K"},
    {"month": 12, "day": 4, "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "180K", "previous": "185K"},
    {"month": 1, "day": 13, "event_en": "US CPI YoY", "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "3.1%", "previous": "3.3%"},
    {"month": 2, "day": 11, "event_en": "US CPI YoY", "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "3.0%", "previous": "3.1%"},
    {"month": 3, "day": 11, "event_en": "US CPI YoY", "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.9%", "previous": "3.0%"},
    {"month": 4, "day": 14, "event_en": "US CPI YoY", "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.8%", "previous": "2.9%"},
    {"month": 5, "day": 12, "event_en": "US CPI YoY", "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.7%", "previous": "2.8%"},
    {"month": 6, "day": 10, "event_en": "US CPI YoY", "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.6%", "previous": "2.7%"},
    {"month": 7, "day": 14, "event_en": "US CPI YoY", "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.5%", "previous": "2.6%"},
    {"month": 8, "day": 12, "event_en": "US CPI YoY", "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.4%", "previous": "2.5%"},
    {"month": 9, "day": 10, "event_en": "US CPI YoY", "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.4%", "previous": "2.4%"},
    {"month": 10, "day": 13, "event_en": "US CPI YoY", "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.3%", "previous": "2.4%"},
    {"month": 1, "day": 30, "event_en": "ECB Press Conference", "event_ar": "المؤتمر الصحفي للبنك المركزي الأوروبي", "currency": "EUR", "impact": "MEDIUM", "forecast": "Hold", "previous": "Hold"},
    {"month": 3, "day": 12, "event_en": "ECB Press Conference", "event_ar": "المؤتمر الصحفي للبنك المركزي الأوروبي", "currency": "EUR", "impact": "MEDIUM", "forecast": "Cut", "previous": "Hold"},
    {"month": 2, "day": 5, "event_en": "BoE Bank Rate", "event_ar": "قرار الفائدة لبنك إنجلترا", "currency": "GBP", "impact": "MEDIUM", "forecast": "4.50%", "previous": "4.75%"},
    {"month": 5, "day": 7, "event_en": "BoE Bank Rate", "event_ar": "قرار الفائدة لبنك إنجلترا", "currency": "GBP", "impact": "MEDIUM", "forecast": "4.25%", "previous": "4.50%"},
    {"month": 1, "day": 23, "event_en": "BoJ Policy Statement", "event_ar": "بيان سياسة بنك اليابان", "currency": "JPY", "impact": "HIGH", "forecast": "Hold", "previous": "Hold"},
    {"month": 4, "day": 30, "event_en": "BoJ Policy Statement", "event_ar": "بيان سياسة بنك اليابان", "currency": "JPY", "impact": "HIGH", "forecast": "Hike", "previous": "Hold"},
    {"month": 7, "day": 30, "event_en": "BoJ Policy Statement", "event_ar": "بيان سياسة بنك اليابان", "currency": "JPY", "impact": "HIGH", "forecast": "Hold", "previous": "Hike"},
    {"month": 1, "day": 15, "event_en": "US Retail Sales MoM", "event_ar": "مبيعات التجزئة الأمريكية", "currency": "USD", "impact": "MEDIUM", "forecast": "0.4%", "previous": "0.3%"},
    {"month": 4, "day": 15, "event_en": "US Retail Sales MoM", "event_ar": "مبيعات التجزئة الأمريكية", "currency": "USD", "impact": "MEDIUM", "forecast": "0.3%", "previous": "0.4%"},
    {"month": 2, "day": 18, "event_en": "German ZEW Sentiment", "event_ar": "مؤشر ZEW الألماني", "currency": "EUR", "impact": "LOW", "forecast": "13.0", "previous": "12.0"},
    {"month": 5, "day": 19, "event_en": "German ZEW Sentiment", "event_ar": "مؤشر ZEW الألماني", "currency": "EUR", "impact": "LOW", "forecast": "14.0", "previous": "13.0"},
]

EVENT_TIME_MAP = {
    "FOMC Rate Decision":     (18, 0),
    "US Non-Farm Payrolls":   (12, 30),
    "US CPI YoY":             (12, 30),
    "ECB Press Conference":   (12, 45),
    "BoE Bank Rate":          (11, 0),
    "BoJ Policy Statement":   (3, 0),
    "US Retail Sales MoM":    (12, 30),
    "German ZEW Sentiment":   (9, 0),
}

STRATEGY_LESSONS = {
    "Liquidity Sweep & Stop Hunt": "Require full entry-TF candle CLOSE beyond sweep wick. Never front-run a sweep.",
    "Fair Value Gap (FVG)": "Only valid if displacement closed with >1.5× avg range AND unmitigated FVG.",
    "Order Block (OB)": "OB must be last opposite-colour candle before impulse with confirmed BOS.",
    "Change of Character (CHoCH)": "Verify CHoCH AFTER HTF liquidity sweep. Standalone is <45% reliable.",
    "Market Structure Shift (MSS)": "MSS on LTF must confirm opposite direction from HTF. Wait for LTF close beyond swing.",
    "Break of Structure (BOS)": "Require body close (not wick) beyond swing with HTF alignment.",
    "Breaker Block": "Only valid if original OB was cleanly consumed by impulse with displacement.",
    "Mitigation Block": "Only trade mitigation if price rejects block with strong reaction candle. No mitigation = no trade.",
    "Balanced Price Range (BPR)": "BPR only valid when both candles have equal wicks and clear displacement on both sides.",
    "Volume Gap": "Volume gap only tradeable if filled within 3 candles. Otherwise invalidate.",
    "Inducement (IDM)": "IDM must be confirmed by lack of follow-through. Never trade inducement itself — trade the reaction.",
    "Judas Swing / ORL": "Only trade Judas AFTER ORL sweep + confirmation candle. First 60 min of session.",
    "Kill Zones & Power of 3": "Restrict entries to London 07-10 UTC or NY 12-15 UTC Kill Zones.",
    "Silver Bullet Strategy": "Only trade 10-11 AM NY (14-15 UTC) or 3-4 AM NY (07-08 UTC). Wait for FVG fill in window.",
    "Optimal Trade Entry (OTE)": "Enter ONLY within 62%-79% retracement. Never buy above 50% premium.",
    "Premium & Discount Zones": "Buy only in discount (below 50%), sell only in premium (above 50%).",
    "Inversion FVG (IFVG)": "IFVG only valid after full-body close through FVG with strong displacement.",
    "Institutional Order Flow (IOF)": "IOF only valid when DXY + macro regime align. Counter-flow trades have <40% WR.",
    "Quarterly Theory / IPDA": "Only enter on quarterly reset (Q1-Q4) or 20-40-60 day IPDA range boundaries.",
    "Daily Bias Framework": "Daily bias determined by prior day liquidity: bullish if prev close > prev open.",
}

MODE_LESSONS = {
    "SCALPING_A": "Mode A: HTF (1W/1D/1H) must align before M5 entry.",
    "SCALPING_B": "Mode B: HTF (1W/1D/4H) bias drives M15/M1 entry.",
    "SWING": "Swing: H1/H4 entry must be inside verified HTF discount/premium.",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
