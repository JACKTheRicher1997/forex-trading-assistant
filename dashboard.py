"""
Trading Assistant & Alert System - Web Dashboard
สร้างด้วย Streamlit และ Plotly ในธีม Dark Mode ที่ทันสมัย สวยงาม อ่านง่าย และ Responsive
ประกอบด้วย:
1. การแสดงสถานะอินดิเคเตอร์ EMA 50 & EMA 150 พร้อม Gauge และ Trend Banner สวยงาม
2. กราฟราคา Candlestick แบบ Interactive พร้อมเส้น EMA ทั้งสองเส้น
3. ระบบรวบรวมข่าวแดงจาก ForexFactory: สรุปรายสัปดาห์, Day Selector, และ Monthly Calendar View
4. แผงควบคุมระบบแจ้งเตือน LINE แบบเรียลไทม์
"""

import datetime
import calendar
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import config
from logger import get_logger
try:
    from services.price_service import create_price_service
except ImportError:
    # Fallback ถ้า snapshot ยังไม่ทัน (โค้ดเก่าไม่มี factory) -> ใช้ PriceService เก่า
    from services.price_service import PriceService as create_price_service
    get_logger("Dashboard").warning("ไม่พบ create_price_service (โค้ดเก่า?) -> ใช้ PriceService แทน")
from services.indicator_service import IndicatorService, TrendState, CrossSignal
from services.news_service import ForexFactoryNewsService, ForexNewsItem
from services.notifier import NotificationService

logger = get_logger("Dashboard")


def _st_secret(key: str, default: str = ""):
    """
    อ่านค่า Streamlit Secrets อย่างปลอดภัยทุกเวอร์ชัน (ไม่โยน exception)
    รองรับทั้ง st.secrets ที่เป็น dict (.get / []) และเวอร์ชันที่ยังไม่มี runtime
    """
    try:
        import streamlit as st

        secs = getattr(st, "secrets", None)
        if secs is not None:
            try:
                value = secs.get(key, default)
            except Exception:
                value = None
            if value is None:
                try:
                    value = secs[key]
                except Exception:
                    return default
            if value is not None and str(value).strip():
                return value
    except Exception:
        pass
    return default


def _switch_timeframe(tf: str) -> None:
    """Callback เมื่อกดปุ่ม MTF: ตั้งค่า selectbox 'กรอบเวลา (Timeframe)' ก่อน rerun"""
    st.session_state["select_tf"] = tf

# ==========================================
# 1. Page Configuration & Custom Dark CSS
# ==========================================
st.set_page_config(
    page_title="Forex Trading Assistant | EMA & Red News Alert",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS เพื่อสร้าง UI สไตล์ Dark Luxury Glassmorphism & High-tech Financial Terminal
st.markdown(
    """
    <style>
    /* Dark Theme Core */
    .stApp {
        background-color: #0b0e14;
        color: #e2e8f0;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Card Container */
    .metric-card {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.8));
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
        backdrop-filter: blur(10px);
        margin-bottom: 15px;
    }

    /* Status Banners */
    .trend-bullish {
        background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(5, 150, 105, 0.35));
        border: 2px solid #10b981;
        border-radius: 12px;
        padding: 16px 20px;
        text-align: center;
        box-shadow: 0 0 20px rgba(16, 185, 129, 0.3);
        animation: pulse-green 2s infinite;
    }
    .trend-bearish {
        background: linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(220, 38, 38, 0.35));
        border: 2px solid #ef4444;
        border-radius: 12px;
        padding: 16px 20px;
        text-align: center;
        box-shadow: 0 0 20px rgba(239, 68, 68, 0.3);
        animation: pulse-red 2s infinite;
    }
    .trend-neutral {
        background: linear-gradient(135deg, rgba(148, 163, 184, 0.15), rgba(71, 85, 105, 0.25));
        border: 2px solid #94a3b8;
        border-radius: 12px;
        padding: 16px 20px;
        text-align: center;
    }

    /* Safe Day Banner (เมื่อไม่มีข่าวแดง) */
    .safe-trading-banner {
        background: linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(6, 95, 70, 0.25));
        border-left: 5px solid #10b981;
        border-radius: 8px;
        padding: 16px;
        margin: 15px 0;
        color: #6ee7b7;
        font-size: 1.05rem;
        font-weight: 600;
    }

    /* News Table (อ่านง่าย ตัวเลขใหญ่ พอดีคอลัมน์) */
    .news-table-wrap {
        overflow-x: auto;
        margin: 12px 0 20px 0;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
        background: rgba(15, 23, 42, 0.6);
    }
    .news-table {
        width: 100%;
        border-collapse: collapse;
        color: #e2e8f0;
        font-size: 1.05rem;
        line-height: 1.4;
    }
    .news-table th {
        background: rgba(30, 41, 59, 0.8);
        color: #94a3b8;
        font-weight: 700;
        font-size: 0.9rem;
        text-align: center;
        padding: 10px 12px;
        white-space: nowrap;
        border-bottom: 2px solid rgba(255, 255, 255, 0.1);
        position: sticky;
        top: 0;
    }
    .news-table td {
        padding: 9px 12px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        vertical-align: middle;
    }
    .news-table tbody tr:hover {
        background: rgba(255, 255, 255, 0.04);
    }
    .news-table tbody tr:last-child td {
        border-bottom: none;
    }
    .news-detail { text-align: left; }
    .news-detail summary {
        cursor: pointer;
        color: #fbbf24;
        font-weight: 600;
        font-size: 1rem;
        list-style-position: inside;
        text-decoration: underline dotted;
        text-underline-offset: 3px;
        transition: color 0.15s ease;
    }
    .news-detail summary:hover { color: #fcd34d; }
    .news-detail__body {
        display: block;
        color: #cbd5e1;
        font-size: 0.9rem;
        line-height: 1.5;
        padding: 6px 2px 2px 18px;
    }

    /* Header styling */
    h1, h2, h3 {
        color: #f8fafc !important;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    
    /* Pulse animations */
    @keyframes pulse-green {
        0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4); }
        70% { box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
        100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
        70% { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
        100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
    }

    /* Responsive adjustments */
    @media (max-width: 768px) {
        .metric-card {
            padding: 12px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ==========================================
# 2. Service Caching & Singletons
# ==========================================
@st.cache_resource
def get_services():
    """สร้าง Service Instances แบบ Cached ป้องกันการสร้างซ้ำใน Streamlit Rerun"""
    price_srv = create_price_service()
    ind_srv = IndicatorService()
    news_srv = ForexFactoryNewsService()
    notif_srv = NotificationService()
    return price_srv, ind_srv, news_srv, notif_srv


price_service, indicator_service, news_service, notification_service = get_services()


@st.cache_data(ttl=90, show_spinner=False)
def cached_rates(symbol: str, timeframe_str: str, count: int) -> object:
    """
    ดึงข้อมูลแท่งเทียนจาก Yahoo Finance พร้อม Cache (90 วินาที)
    ทำให้เปิดเว็บ/ย้อนกลับมาดู หรือสลับแท็บ ไม่ต้องโหลดข้อมูลราคาซ้ำสด ๆ ทุกครั้ง
    """
    return price_service.get_rates(symbol=symbol, timeframe_str=timeframe_str, count=count)


def drop_last_open_candle(df) -> object:
    """
    ตัดแท่งเทียนที่ยังไม่ปิด (กำลังก่อตัว) ออกหนึ่งแท่งสุดท้ายก่อนนำมาวิเคราะห์
    เพื่อให้เลข EMA Distance / ราคาที่แสดงคงที่ ณ ระหว่างที่แท่งยังไม่ปิด
    (กดรีเฟรช หรือกดปุ่มในหน้าเว็บหลายครั้ง เลขจะไม่สั่น/เพี้ยนตามราคาระหว่างแท่ง)
    """
    if df is not None and len(df) > 2:
        return df.iloc[:-1].reset_index(drop=True)
    return df


def seconds_to_next_candle(tf: str) -> int:
    """
    คำนวณจำนวนวินาทีที่เหลือจนถึงแท่งเทียนแท่งถัดไปจะปิด
    เพื่อให้เว็บรีเฟรซพอดีตอนแท่งปิด -> ค่า EMA Distance ตรงกับข้อมูลจริงล่าสุดเสมอ
    เผื่อเวลา +5 วินาทีให้ Yahoo Finance อัปเดตแท่งใหม่แล้วค่อย rerun
    """
    now = datetime.datetime.now()
    tf_sec = {"M5": 300, "M15": 900, "H1": 3600}.get(tf)
    if tf == "D1":
        nxt = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(15, int((nxt - now).total_seconds()) + 5)
    if tf == "H4":
        elapsed = (now.hour % 4) * 3600 + now.minute * 60 + now.second
        tf_sec = 14400
    elif tf_sec is not None:
        elapsed = (now.minute % (tf_sec // 60)) * 60 + now.second
    else:
        tf_sec = 300
        elapsed = (now.minute % 5) * 60 + now.second
    return max(15, tf_sec - elapsed + 5)


def countdown_to_news(news_date_local) -> str:
    """
    คำนวณเวลานับถอยหลังก่อนข่าวออก (เฉพาะข่าวที่ยังไม่ถึงเวลา):
    - เหลือ <= 10 นาที: '🔴 กำลังออกใน X นาที Y วิ'
    - ยังอีกนาน: แสดงเวลาเหลือแบบ 'HH:MM:SS'
    - ผ่านไปแล้ว: '-' (ไม่นับถอยหลัง)
    """
    try:
        now = datetime.datetime.now(news_date_local.tzinfo)
        delta = news_date_local - now
        if delta.total_seconds() <= 0:
            return "-"
        total_sec = int(delta.total_seconds())
        days = total_sec // 86400
        hours = (total_sec % 86400) // 3600
        minutes = (total_sec % 3600) // 60
        seconds = total_sec % 60

        if total_sec <= 600:  # เหลือไม่เกิน 10 นาที -> โชว์นับถอยหลังวิ
            return f"🔴 {minutes}m {seconds:02d}s"
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except Exception:
        return "-"


def countdown_tag(news_date_local) -> str:
    """สร้าง HTML badge สำหรับช่วง 10 นาทีก่อนข่าวออก"""
    try:
        now = datetime.datetime.now(news_date_local.tzinfo)
        delta = news_date_local - now
        if 0 < delta.total_seconds() <= 600:
            return '<span style="background:#ef4444;color:#fff;padding:2px 8px;border-radius:10px;font-size:0.8rem;font-weight:bold;">🔴 ใกล้ถึงเวลาออกข่าว</span>'
    except Exception:
        pass


def _candle_as_naive_utc(ts):
    """แปลง timestamp แท่งเทียนให้เป็น naive UTC (เพื่อคิดระยะเวลาเทียบกับตอนนี้)"""
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _fmt_ts_bangkok(ts) -> str:
    """แปลง timestamp เป็นเวลาไทย (ICT UTC+7) สำหรับแสดงผล"""
    return (_candle_as_naive_utc(ts) + datetime.timedelta(hours=7)).strftime("%Y-%m-%d %H:%M น.")


def _fmt_duration(delta) -> str:
    """จัดรูปแบบระยะเวลาต่อเนื่องให้อ่านง่าย (เดือน/สัปดาห์/วัน/ชั่วโมง)"""
    total = max(0, int(delta.total_seconds()))
    minutes, _ = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    weeks, days = divmod(days, 7)
    months, weeks = divmod(weeks, 4)
    parts = []
    for label, val in (("เดือน", months), ("สัปดาห์", weeks), ("วัน", days), ("ชั่วโมง", hours)):
        if val:
            parts.append(f"{val} {label}")
    if not parts:
        if minutes:
            return f"{minutes} นาที"
        return "ผ่านมาไม่ถึง 1 นาที"
    return " ".join(parts)


def _resolve_app_tz():
    """คืน (tzinfo, tz_name) ของเวลาที่ระบบตั้งไว้ (TIMEZONE) โดยมี fallback เป็น UTC+7"""
    tz_name = getattr(config.news, "timezone", None) or "Asia/Bangkok"
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name), tz_name
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=7)), "Asia/Bangkok"


def _load_cross_state_cache() -> dict:
    """โหลดฐานข้อมูลสัญญาณ EMA Cross (state/ema_cross_state.json) ที่ bot สะสมไว้ข้าม run"""
    try:
        _p = Path(__file__).resolve().parent / "state" / "ema_cross_state.json"
        if _p.exists():
            with open(_p, "r", encoding="utf-8") as _f:
                _data = json.load(_f)
            _entries = _data.get("entries")
            if isinstance(_entries, dict):
                return _entries
    except Exception:
        pass
    return {}


def _last_cross_from_state(symbol: str, timeframe: str):
    """
    ค้นหา EMA Cross "ครั้งล่าสุด" ของ symbol::timeframe จากฐานข้อมูลสัญญาณ
    (มีประโยชน์เมื่อไม่มี Cross อยู่ในช่วงข้อมูลที่โหลดมาเพราะเก่าเกินขอบข้อมูล)
    """
    entries = _load_cross_state_cache()
    if not entries:
        return None
    record = entries.get(f"{symbol}::{timeframe}")
    if record is None:
        sym_up = symbol.upper()
        for k, v in entries.items():
            parts = str(k).split("::", 1)
            if len(parts) == 2 and parts[1] == timeframe and parts[0].upper() == sym_up:
                record = v
                break
    if not isinstance(record, dict):
        return None
    # ลำดับการอ่าน: last_cross (เข็มถาวรที่ bot สะสมไว้ทุกไทม์เฟรม) -> alerted[-1] (24 ชม. ล่าสุด)
    last_cross = record.get("last_cross")
    if isinstance(last_cross, dict) and last_cross.get("candle_time"):
        return last_cross
    alerted = record.get("alerted")
    if isinstance(alerted, list) and alerted:
        last = alerted[-1]
        if isinstance(last, dict) and last.get("candle_time"):
            return last
    if record.get("candle_time"):
        return {"candle_time": record["candle_time"], "signal": record.get("signal", "")}
    return None


def _state_candle_to_naive_utc(ts):
    """แปลง timestamp จากไฟล์ state (ISO string) เป็น naive UTC สำหรับคำนวณระยะเวลา"""
    if isinstance(ts, datetime.datetime):
        return _candle_as_naive_utc(ts)
    try:
        dt = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None
    return _candle_as_naive_utc(dt)


def render_live_clock(symbol: str) -> None:
    """
    แสดงเวลาปัจจุบันตาม TIMEZONE ของระบบ (ค่าเริ่มต้นเวลาไทย ICT UTC+7) แบบเรียลไทม์
    ให้ตัวเลขวินาทีเดินทุกวินาทีโดยไม่ต้องรีเฟรชหน้า
    ใช้ st.html + JavaScript ฝังลงในหน้าเว็บตรง ๆ (ไม่ถูก iframe) จึงอัปเดตเองได้
    ฝั่ง JS ต้องระบุ timeZone ด้วย ไม่งั้นจะกลายเป็นเวลาเครื่องผู้ใช้แทน
    """
    tz, tz_name = _resolve_app_tz()
    initial = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    st.html(
        f"""
        <div class="live-clock" id="liveClockBox" data-symbol="{symbol}" data-tz="{tz_name}">
            <span class="live-clock__dot"></span>
            เวลาปัจจุบัน ({tz_name}): <span class="live-clock__time" id="liveClockTime">{initial}</span>
            <span class="live-clock__sep">|</span>
            สกุลเงินหลัก: <span class="live-clock__symbol" id="liveClockSymbol">{symbol}</span>
        </div>
        <style>
            .live-clock {{
                display: flex;
                align-items: center;
                flex-wrap: wrap;
                gap: 6px;
                color: #8b9bb4;
                font-size: 0.875rem;
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                margin: -4px 0 8px 0;
            }}
            .live-clock__dot {{
                width: 7px;
                height: 7px;
                border-radius: 50%;
                background: #22c55e;
                box-shadow: 0 0 8px rgba(34, 197, 94, 0.9);
                animation: liveClockBlink 2s ease-in-out infinite;
            }}
            .live-clock__time {{
                color: #e2e8f0;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                letter-spacing: 0.3px;
            }}
            .live-clock__sep {{ opacity: 0.45; }}
            .live-clock__symbol {{ color: #fbbf24; font-weight: 600; }}
            @keyframes liveClockBlink {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.25; }}
            }}
        </style>
        <script>
            (function () {{
                const box = document.getElementById('liveClockBox');
                const timeEl = document.getElementById('liveClockTime');
                const symEl = document.getElementById('liveClockSymbol');
                if (!box || !timeEl) return;
                if (box.dataset.liveClockBound === '1') return;
                box.dataset.liveClockBound = '1';

                const tzName = box.dataset.tz || 'Asia/Bangkok';
                const render = () => {{
                    const parts = new Intl.DateTimeFormat('sv-SE', {{
                        timeZone: tzName,
                        year: 'numeric', month: '2-digit', day: '2-digit',
                        hour: '2-digit', minute: '2-digit', second: '2-digit',
                        hour12: false,
                    }}).formatToParts(new Date());
                    const get = (t) => (parts.find((p) => p.type === t) || {{}}).value || '00';
                    timeEl.textContent =
                        get('year') + '-' + get('month') + '-' + get('day') +
                        ' ' + get('hour') + ':' + get('minute') + ':' + get('second');
                    timeEl.title = new Date().toLocaleString();
                }};
                if (symEl && box.dataset.symbol) symEl.textContent = box.dataset.symbol;

                render();
                // เช็คทุก 200ms แล้วเขียนเฉพาะตอนวินาทีเปลี่ยน กัน drift และกันเขียนซ้ำ
                setInterval(render, 200);
            }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def format_actual_with_color(item: ForexNewsItem) -> str:
    """
    จัดรูปแบบตัวเลขจริง (Actual) พร้อมสีตาม ForexFactory
    - better (สีเขียว): ตัวเลขจริงดีกว่าคาดการณ์
    - worse (สีแดง): ตัวเลขจริงแย่กว่าคาดการณ์
    - ปกติ: ไม่มีสีพิเศษ
    """
    actual = getattr(item, "actual", "") or "รอดูผล"
    actual_color = getattr(item, "actual_color", "")
    if not actual:
        return actual
    if actual_color == "better":
        return f'<span style="color:#00aa00;font-weight:700;">{actual} ▲</span>'
    elif actual_color == "worse":
        return f'<span style="color:#cc0000;font-weight:700;">{actual} ▼</span>'
    return actual


def format_actual_text(item: ForexNewsItem) -> str:
    """จัดรูปแบบตัวเลขจริงสำหรับ st.dataframe (สีถูกใช้ผ่าน pandas Styler)"""
    actual = getattr(item, "actual", "") or "รอดูผล"
    actual_color = getattr(item, "actual_color", "")
    if not actual:
        return actual
    if actual_color == "better":
        return f"{actual} ▲"
    elif actual_color == "worse":
        return f"{actual} ▼"
    return actual


def actual_color_code(item: ForexNewsItem) -> str:
    """คืนค่า CSS สีของตัวเลขจริง: สีเขียว/แดง/ว่าง (ตามสไตล์ ForexFactory จริง)"""
    c = getattr(item, "actual_color", "")
    if c == "better":
        return "#00aa00"
    elif c == "worse":
        return "#cc0000"
    return ""


# คู่มือความหมายข่าวเศรษฐกิจเป็นภาษาไทยสั้น ๆ (สำหรับชื่อข่าวแดงที่เจอบ่อย)
_NEWS_MEANING_TH = {
    "Non-Farm Employment Change": "ตัวเลขการจ้างงานนอกภาคเกษตร (NFP) — ตัวชี้วัดสุขภาพตลาดแรงงานสหรัฐฯ ที่สำคัญที่สุด หากมากกว่าคาด หมายถึงเศรษฐกิจแข็งแรง ดอลลาร์มีแนวโน้มแข็งค่า และอาจกดดันให้เฟดขึ้นดอกเบี้ย",
    "Non-Farm Payrolls": "ตัวเลขการจ้างงานนอกภาคเกษตร (NFP) — ตัวชี้วัดสุขภาพตลาดแรงงานสหรัฐฯ ที่สำคัญที่สุด หากมากกว่าคาด หมายถึงเศรษฐกิจแข็งแรง ดอลลาร์มีแนวโน้มแข็งค่า และอาจกดดันให้เฟดขึ้นดอกเบี้ย",
    "Unemployment Rate": "อัตราการว่างงานของสหรัฐฯ — ถ้าลดลงต่ำกว่าคาด ตลาดแรงงานร้อนแรง เฟดอาจไม่รีบลดดอกเบี้ย ดอลลาร์มักแข็งค่า ส่วนถ้าสูงกว่าคาด ดอลลาร์มักอ่อนค่า",
    "Average Hourly Earnings m/m": "ค่าจ้างเฉลี่ยรายชั่วโมง — วัดแรงกดดันเงินเฟ้อจากฝั่งค่าแรง ถ้าสูงกว่าคาด หมายถึงค่าแรงแพงขึ้น เงินเฟ้ออาจเร่ง เฟดมีเหตุผลให้คง/ขึ้นดอกเบี้ย ดอลลาร์แข็งค่าขึ้น",
    "Core PCE Price Index m/m": "ดัชนีราคาค่าใช้จ่ายเพื่อการบริโภคส่วนบุคคล (ไม่รวมอาหาร/พลังงาน) — ตัววัดเงินเฟ้อที่เฟดนิยมใช้ตัดสินนโยบาย ถ้าสูงกว่าคาด เงินเฟ้อร้อน เฟดอาจไม่ลดดอกเบี้ย ดอลลาร์แข็งค่า",
    "Core CPI m/m": "ดัชนีราคาผู้บริโภค (ไม่รวมอาหาร/พลังงาน) — เงินเฟ้อหลัก ถ้าสูงกว่าคาด หมายถึงราคาสินค้าสูงขึ้น เฟดอาจขึ้นดอกเบี้ย ดอลลาร์แข็งค่า",
    "CPI m/m": "ดัชนีราคาผู้บริโภค — ตัววัดเงินเฟ้อที่ทุกคนจับตา ถ้าสูงกว่าคาด เงินเฟ้อเร่ง เฟดมีแนวโน้มขึ้นดอกเบี้ย ดอลลาร์แข็งค่า",
    "CPI y/y": "ดัชนีราคาผู้บริโภครายปี — ตัววัดเงินเฟ้อ ถ้าสูงกว่าคาด เฟดอาจขึ้นดอกเบี้ย ดอลลาร์แข็งค่า",
    "Final GDP q/q": "อัตราการเติบโตทางเศรษฐกิจ (GDP) ประจำไตรมาส — ถ้าสูงกว่าคาด เศรษฐกิจโตแรง เฟดไม่ต้องรีบลดดอกเบี้ย ดอลลาร์แข็งค่า ถ้าต่ำกว่าคาด เศรษฐกิจซบเซา ดอลลาร์อ่อนค่า",
    "GDP q/q": "อัตราการเติบโตทางเศรษฐกิจ (GDP) ประจำไตรมาส — ถ้าสูงกว่าคาด เศรษฐกิจโตแรง ดอลลาร์แข็งค่า ถ้าต่ำกว่าคาด เศรษฐกิจซบเซา ดอลลาร์อ่อนค่า",
    "Retail Sales m/m": "ยอดขายปลีก — วัดกำลังซื้อของผู้บริโภค ถ้าสูงกว่าคาด ผู้คนใช้จ่ายคล่อง เศรษฐกิจดี ดอลลาร์แข็งค่า ถ้าต่ำกว่าคาด ดอลลาร์อ่อนค่า",
    "ISM Manufacturing PMI": "ดัชนีผู้จัดการฝ่ายจัดซื้อภาคการผลิต — ถ้าเกิน 50 หมายถึงภาคการผลิตขยายตัว ถ้าสูงกว่าคาด เศรษฐกิจแข็งแรง ดอลลาร์แข็งค่า",
    "ISM Services PMI": "ดัชนีผู้จัดการฝ่ายจัดซื้อภาคบริการ — ถ้าเกิน 50 ภาคบริการขยายตัว ถ้าสูงกว่าคาด ดอลลาร์แข็งค่า",
    "ADP Non-Farm Employment Change": "ตัวเลขการจ้างงานภาคเอกชน (ADP) — มักออกก่อน NFP 2 วัน ใช้คาดการณ์ตลาดแรงงาน ถ้าสูงกว่าคาด ดอลลาร์แข็งค่า",
    "Initial Jobless Claims": "จำนวนผู้ยื่นขอรับสวัสดิการว่างงานรายสัปดาห์ — ถ้าต่ำกว่าคาด ตลาดแรงงานแข็งแรง ดอลลาร์แข็งค่า ถ้าสูงกว่าคาด ตลาดแรงงานอ่อนแอ ดอลลาร์อ่อนค่า",
    "Jobless Claims": "จำนวนผู้ยื่นขอรับสวัสดิการว่างงานรายสัปดาห์ — ถ้าต่ำกว่าคาด ตลาดแรงงานแข็งแรง ดอลลาร์แข็งค่า ถ้าสูงกว่าคาด ดอลลาร์อ่อนค่า",
    "Trade Balance": "ดุลการค้า — ผลต่างระหว่างส่งออกกับนำเข้า ถ้าเกินคาด (เกินดุล) ค่าเงินมีแนวโน้มแข็งค่า ถ้าต่ำกว่าคาด (ขาดดุล) ค่าเงินอ่อนค่า",
    "Consumer Confidence": "ดัชนีความเชื่อมั่นผู้บริโภค — ถ้าสูงกว่าคาด ผู้คนมั่นใจในเศรษฐกิจ ใช้จ่ายมากขึ้น ค่าเงินแข็งค่า",
    "Michigan Consumer Sentiment": "ดัชนีความเชื่อมั่นผู้บริโภคมหาวิทยาลัยมิชิแกน — ถ้าสูงกว่าคาด ผู้บริโภคมองเศรษฐกิจดี ค่าเงินแข็งค่า",
    "FOMC Statement": "แถลงการณ์หลังประชุมเฟด — ส่งสัญญาณทิศทางดอกเบี้ย หากท่าที 'ฮอว์ก' (ขึ้นดอกเบี้ย) ดอลลาร์แข็งค่า หาก 'โดฟ' (ลดดอกเบี้ย) ดอลลาร์อ่อนค่า",
    "Federal Funds Rate": "การประกาศอัตราดอกเบี้ยของเฟด — ดอกเบี้ยขึ้น = ดอลลาร์แข็ง ดอกเบี้ยลง = ดอลลาร์อ่อน คล้องกับ FOMC Statement",
    "Federal Funds Rate Decision": "การประกาศอัตราดอกเบี้ยของเฟด — ดอกเบี้ยขึ้น = ดอลลาร์แข็ง ดอกเบี้ยลง = ดอลลาร์อ่อน",
    "ECB Press Conference": "งานแถลงข่าวประธาน ECB หลังประชุมกำหนดดอกเบี้ยยูโร — สัญญาณทิศทางดอกเบี้ยส่งผลโดยตรงต่อยูโร",
    "ECB Interest Rate Decision": "การประกาศอัตราดอกเบี้ยของ ECB — ดอกเบี้ยขึ้น = ยูโรแข็ง ลง = ยูโรอ่อน",
    "BoE Interest Rate Decision": "การประกาศอัตราดอกเบี้ยของธนาคารกลางอังกฤษ — ดอกเบี้ยขึ้น = ปอนด์แข็ง ลง = ปอนด์อ่อน",
    "BoJ Interest Rate Decision": "การประกาศอัตราดอกเบี้ยของธนาคารกลางญี่ปุ่น — ดอกเบี้ยขึ้น = เยนแข็ง ลง = เยนอ่อน",
    "RBA Interest Rate Decision": "การประกาศอัตราดอกเบี้ยของ RBA (ออสเตรเลีย) — ดอกเบี้ยขึ้น = ดอลลาร์ออสเตรเลียแข็ง ลง = อ่อน",
    "RBNZ Interest Rate Decision": "การประกาศอัตราดอกเบี้ยของ RBNZ (นิวซีแลนด์) — ดอกเบี้ยขึ้น = ดอลลาร์นิวซีแลนด์แข็ง ลง = อ่อน",
    "BOC Rate Statement": "แถลงการณ์หลังประชุมกำหนดดอกเบี้ยของธนาคารกลางแคนาดา — สัญญาณดอกเบี้ยส่งผลโดยตรงต่อดอลลาร์แคนาดา",
    "Retail Sales (MoM)": "ยอดขายปลีก — วัดกำลังซื้อของผู้บริโภค ถ้าสูงกว่าคาด เศรษฐกิจดี ค่าเงินแข็งค่า",
    "German CPI m/m": "ดัชนีราคาผู้บริโภคเยอรมนี — เงินเฟ้อของประเทศเศรษฐกิจใหญ่สุดในยูโรโซน ถ้าสูงกว่าคาด ยูโรแข็งค่า",
    "German Ifo Business Climate": "ดัชนีความเชื่อมั่นภาคธุรกิจเยอรมนี — ถ้าสูงกว่าคาด เศรษฐกิจเยอรมนี/ยูโรโซนดี ยูโรแข็งค่า",
    "Eurozone CPI Flash Estimate y/y": "ประมาณการเงินเฟ้อเบื้องต้นของยูโรโซน — ถ้าสูงกว่าคาด ECB อาจขึ้นดอกเบี้ย ยูโรแข็งค่า",
    "Eurozone GDP q/q": "อัตราการเติบโตทางเศรษฐกิจยูโรโซน — ถ้าสูงกว่าคาด เศรษฐกิจโตแรง ยูโรแข็งค่า ถ้าต่ำกว่าคาด ยูโรอ่อนค่า",
    "UK Jobless Claims Change": "ผู้ขอรับสวัสดิการว่างงานอังกฤษ — ถ้าเพิ่มขึ้นมากกว่าคาด ตลาดแรงงานอ่อนแอ ปอนด์อ่อนค่า",
    "Swiss CPI m/m": "ดัชนีราคาผู้บริโภคสวิส — เงินเฟ้อสวิตเซอร์แลนด์ ถ้าสูงกว่าคาด ฟรังก์แข็งค่า",
    "Foreign Exchange Reserves": "ทุนสำรองเงินตราต่างประเทศ — ใช้ดูแลเสถียรภาพค่าเงิน ตัวเลขเปลี่ยนแปลงผิดคาดอาจกระทบความเชื่อมั่น",
}

_TITLE_COLUMN_KEYS = ("ชื่อข่าว", "ชื่อข่าวเศรษฐกิจ", "ชื่อข่าว (ไทย)")


def compute_trade_verdict(
    mtf_results: dict,
    selected_tf: str,
    red_news_this_week: list,
) -> dict:
    """
    คำนวณสรุปทิศทางเทรดรวม (Trade Verdict) จาก:
    - MTF Trend: ถ่วงน้ำหนักตามกรอบเวลายิ่งใหญ่ยิ่งสำคัญ (M5=1 ... D1=5)
    - ข่าวแดงที่กำลังจะออก (< 30 นาที) -> บังคับ NO TRADE
    :return: dict สำหรับ render แผง verdict
    """
    weights = {"M5": 1, "M15": 2, "H1": 3, "H4": 4, "D1": 5}
    score, total_w = 0, 0
    bull_frames, bear_frames, neutral_frames = [], [], []
    per_tf = {}
    for tf in ("M5", "M15", "H1", "H4", "D1"):
        trend_str, _color = mtf_results.get(tf, ("NEUTRAL", "#94a3b8"))
        w = weights.get(tf, 1)
        if trend_str.startswith("BULLISH"):
            per_tf[tf] = ("▲", "#10b981")
            score += w
            total_w += w
            bull_frames.append(tf)
        elif trend_str.startswith("BEARISH"):
            per_tf[tf] = ("▼", "#ef4444")
            score -= w
            total_w += w
            bear_frames.append(tf)
        else:
            per_tf[tf] = ("—", "#94a3b8")
            neutral_frames.append(tf)

    ratio = (score / total_w) if total_w else 0.0
    confidence = int(abs(ratio) * 100)

    # ข่าวแดงบนพื้น (ข้อมูลนี้)
    upcoming = []
    for n in red_news_this_week:
        try:
            now_bkk = datetime.datetime.now(n.date_local.tzinfo)
        except Exception:
            now_bkk = datetime.datetime.now()
        secs = (n.date_local - now_bkk).total_seconds()
        if 0 < secs <= 30 * 60:
            upcoming.append(n)
    upcoming = sorted(upcoming, key=lambda x: x.date_local)[:5]

    if upcoming:
        verdict = "NO TRADE"
        icon = "⛔"
        color = "#f59e0b"
        note = (
            "มีข่าวแดงกำลังจะออกในไม่ถึง 30 นาที — ราคามักวิ่งแรง/แกว่งทิศทางไม่แน่นอน "
            "ควรหลีกเลี่ยงการเข้าตำแหน่งใหม่ รอผลประกาศและตลาดนิ่งลงก่อน"
        )
    elif ratio >= 0.25:
        verdict = "BUY"
        icon = "🟢"
        color = "#10b981"
        note = f"แนวโน้มน้ำหนักขาขึ้น ({len(bull_frames)} เฟรมเห็นพ้องขาขึ้น) — มองหาโอกาส Buy เมื่อราคาย่อตัว"
    elif ratio <= -0.25:
        verdict = "SELL"
        icon = "🔴"
        color = "#ef4444"
        note = f"แนวโน้มน้ำหนักขาลง ({len(bear_frames)} เฟรมเห็นพ้องขาลง) — มองหาโอกาส Sell เมื่อราคาดีดตัวขึ้น"
    else:
        verdict = "NEUTRAL"
        icon = "⚪"
        color = "#94a3b8"
        note = "สัญญาณหลายกรอบเวลาไม่ลงทางเดียวกัน — รอทิศทางชัดเจนก่อนเข้าออเดอร์"

    return {
        "verdict": verdict,
        "icon": icon,
        "color": color,
        "confidence": confidence,
        "note": note,
        "per_tf": per_tf,
        "bull_frames": bull_frames,
        "bear_frames": bear_frames,
        "neutral_frames": neutral_frames,
        "upcoming": upcoming,
        "selected_tf": selected_tf,
    }


def _verdict_panel_html(v: dict, countdown_fn) -> str:
    """สร้าง HTML แผงสรุปทิศทางเทรดแบบเต็มความกว้าง"""
    dots = " ".join(
        f'<span style="margin:0 6px;"><b>{tf}</b> <span style="color:{color};font-weight:800;">{sym}</span></span>'
        for tf, (sym, color) in v["per_tf"].items()
    )
    conf_color = v["color"] if v["confidence"] >= 50 else "#f59e0b"
    news_block = ""
    if v["upcoming"]:
        lines = "".join(
            f"• 🔴 {countdown_fn(n.date_local)} | [{n.country}] {n.title}<br/>"
            for n in v["upcoming"]
        )
        news_block = (
            f'<div style="margin-top:12px;padding:10px 14px;border-left:3px solid #ef4444;'
            f'background:rgba(239,68,68,0.12);border-radius:6px;color:#fecaca;font-size:0.95rem;">'
            f"<b>⏰ ข่าวแดงใกล้ถึงเวลา:</b><br/>{lines}</div>"
        )
    return f"""
    <div style="background:rgba(15,23,42,0.9);border:1px solid {v['color']};border-radius:14px;
                padding:18px 22px;margin:16px 0 6px 0;">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
            <span style="font-size:1.3rem;font-weight:800;color:#f8fafc;">🎯 สรุปทิศทางเทรด (Trade Verdict)</span>
            <span style="font-size:1.5rem;font-weight:800;color:{v['color']};">{v['icon']} {v['verdict']}</span>
        </div>
        <div style="margin-top:10px;">
            <div style="font-size:0.85rem;color:#94a3b8;margin-bottom:3px;">ความสอดคล้องของกรอบเวลา (Confidence): {v['confidence']}%</div>
            <div style="height:10px;background:rgba(255,255,255,0.08);border-radius:5px;overflow:hidden;">
                <div style="height:100%;width:{v['confidence']}%;background:{conf_color};border-radius:5px;"></div>
            </div>
        </div>
        <div style="margin-top:12px;font-size:1.05rem;color:#cbd5e1;">{dots}</div>
        <div style="margin-top:10px;color:#e2e8f0;font-size:1rem;line-height:1.5;">💡 {v['note']}</div>
        {news_block}
    </div>
    """


def _news_title_html(title: str) -> str:
    """ทำให้ชื่อข่าวกดเปิดดูคำอธิบายภาษาไทยสั้น ๆ ได้ (Details/Summary)"""
    meaning = _NEWS_MEANING_TH.get(title)
    if not meaning:
        meaning = "ข่าวแดงผลกระทบสูงของสกุลเงินนี้ — ควรหลีกเลี่ยงการเปิดออเดอร์ช่วงประกาศ และเฝ้าดูการเคลื่อนไหวของราคาก่อน"
    return (
        f'<details class="news-detail"><summary>{title}</summary>'
        f'<span class="news-detail__body">{meaning}</span></details>'
    )


def compute_support_resistance(df, swing_window: int = 40) -> dict:
    """
    คำนวณแนวรับ/แนวต้านอัตโนมัติจาก:
    - Pivot Point แบบ Classic (แท่งปิดล่าสุด) -> R3..S3 + Pivot
    - Swing High/Low ในช่วง swing_window แท่งล่าสุด
    - ระดับเลขกลม (Round Numbers) ใกล้ราคาปัจจุบัน
    รวมระดับที่อยู่ใกล้กัน (ภายใน ~0.15%) แล้วจัดหมวดเป็นด้าน R / S เทียบราคาปัจจุบัน
    :return: dict {current_close, levels, nearest_support, nearest_resistance}
    """
    out = {"current_close": None, "levels": [], "nearest_support": None, "nearest_resistance": None}
    if df is None or len(df) < 3:
        return out
    df2 = df.dropna(subset=["high", "low", "close"])
    if len(df2) < 3:
        return out

    last = df2.iloc[-1]
    H = float(last["high"])
    L = float(last["low"])
    C = float(last["close"])
    P = (H + L + C) / 3

    # 1) Pivot Point แบบ Classic
    candidates = [
        (H + 2 * (P - L), "R3", "Pivot"),
        (P + (H - L), "R2", "Pivot"),
        (2 * P - L, "R1", "Pivot"),
        (P, "Pivot", "Pivot"),
        (2 * P - H, "S1", "Pivot"),
        (P - (H - L), "S2", "Pivot"),
        (L - 2 * (H - P), "S3", "Pivot"),
    ]

    # 2) Swing High/Low
    look = df2.tail(swing_window)
    if len(look) >= 5:
        highs = look["high"].astype(float).tolist()
        lows = look["low"].astype(float).tolist()
        for i in range(2, len(look) - 2):
            if highs[i] == max(highs[i - 2:i + 3]):
                candidates.append((highs[i], "Swing", "Swing"))
            if lows[i] == min(lows[i - 2:i + 3]):
                candidates.append((lows[i], "Swing", "Swing"))

    # 3) ระดับเลขกลม (Round Numbers)
    step = 100 if C >= 1000 else 10 if C >= 100 else 1 if C >= 10 else 0.5 if C >= 1 else 0.1
    dec = 0 if step >= 1 else 1
    base = int(C // step) * step
    for k in range(-3, 4):
        v = round(base + k * step, dec)
        if v > 0 and v != C:
            candidates.append((v, "Round", "Round"))

    # รวมระดับที่อยู่ใกล้กัน (ความสำคัญ: Pivot > Swing > Round)
    rank = {"Pivot": 0, "Swing": 1, "Round": 2}
    groups = []
    for price, label, kind in sorted(candidates, key=lambda x: x[0]):
        placed = False
        for g in groups:
            if abs(g["avg"] - price) / max(price, 1e-9) * 100 <= 0.15:
                g["items"].append((price, label, kind))
                g["avg"] = sum(i[0] for i in g["items"]) / len(g["items"])
                placed = True
                break
        if not placed:
            groups.append({"avg": price, "items": [(price, label, kind)]})

    levels = []
    for g in groups:
        best = min(g["items"], key=lambda i: rank[i[2]])
        price, label, kind = best
        side = "R" if price > C else "S"
        levels.append(
            {
                "price": round(g["avg"], 2),
                "label": label,
                "kind": kind,
                "side": side,
                "pct": abs(price - C) / C * 100 if C else 0.0,
            }
        )
    levels.sort(key=lambda x: x["price"], reverse=True)

    resistances = [l for l in levels if l["side"] == "R"]
    supports = [l for l in levels if l["side"] == "S"]

    out["current_close"] = C
    out["levels"] = levels
    out["nearest_resistance"] = min(resistances, key=lambda l: l["price"]) if resistances else None
    out["nearest_support"] = max(supports, key=lambda l: l["price"]) if supports else None
    return out


def _sr_box_html(l: dict, is_support: bool, is_nearest: bool, is_price: bool = False) -> str:
    """กล่องเล็กแสดงระดับ S/R หรือราคาปัจจุบัน"""
    border = "#f87171" if is_support else "#34d399"
    text = "#fecaca" if is_support else "#a7f3d0"
    if is_price:
        border, text = "#fbbf24", "#fde68a"
    ring = "box-shadow:0 0 0 2px rgba(251,191,36,0.55);" if is_nearest else ""
    if is_price:
        inner = (
            f'<div style="font-size:0.7rem;color:#94a3b8;">ราคาปัจจุบัน</div>'
            f'<div style="font-size:1.15rem;font-weight:800;color:#f8fafc;">${l["price"]:,.2f}</div>'
        )
    else:
        arrow = "↑" if not is_support else "↓"
        inner = (
            f'<div style="font-size:0.7rem;color:#94a3b8;">{arrow} {l["label"]} · {l["pct"]:.2f}%</div>'
            f'<div style="font-size:1.15rem;font-weight:800;color:{text};">${l["price"]:,.2f}</div>'
        )
    return (
        f'<div style="flex:1 1 120px;min-width:120px;background:rgba(15,23,42,0.85);'
        f'border:1px solid {border};border-radius:10px;padding:8px 10px;text-align:center;{ring}">{inner}</div>'
    )


def _sr_panel_html(sr: dict) -> str:
    """สร้าง HTML แผงแนวรับ/แนวต้านอัตโนมัติแบบบันได (R3...S3)"""
    C = sr["current_close"]
    resistances = sorted([l for l in sr["levels"] if l["side"] == "R"], key=lambda l: l["price"])[:3][::-1]
    supports = sorted([l for l in sr["levels"] if l["side"] == "S"], key=lambda l: l["price"], reverse=True)[:3]
    nr = sr["nearest_resistance"]
    ns = sr["nearest_support"]

    cells = "".join(
        _sr_box_html(l, False, bool(nr and l["price"] == nr["price"])) for l in resistances
    )
    cells += _sr_box_html({"price": C}, False, False, is_price=True)
    cells += "".join(
        _sr_box_html(l, True, bool(ns and l["price"] == ns["price"])) for l in supports
    )

    tip = ""
    if nr and ns:
        tip = (
            f'<div style="margin-top:8px;color:#cbd5e1;font-size:0.9rem;">'
            f'• ใกล้แนวต้าน <b style="color:#f87171;">{nr["label"]} ${nr["price"]:,.2f}</b> อยู่ห่าง {nr["pct"]:.2f}%<br/>'
            f'• ใกล้แนวรับ <b style="color:#34d399;">{ns["label"]} ${ns["price"]:,.2f}</b> อยู่ห่าง {ns["pct"]:.2f}%'
            f'</div>'
        )
    return (
        f'<div style="background:rgba(15,23,42,0.9);border:1px solid rgba(255,255,255,0.08);'
        f'border-radius:14px;padding:16px 20px;margin:12px 0 6px 0;">'
        f'<div style="font-size:1.15rem;font-weight:800;color:#f8fafc;margin-bottom:10px;">'
        f'📏 แนวรับ / แนวต้านอัตโนมัติ (Support & Resistance)</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:stretch;">{cells}</div>'
        f'{tip}'
        f'<div style="margin-top:8px;color:#64748b;font-size:0.8rem;">อ้างอิง: Pivot Point Classic + Swing High/Low 40 แท่งล่าสุด + ระดับเลขกลม</div>'
        f'</div>'
    )


def compute_atr(df, period: int = 14) -> Optional[float]:
    """
    คำนวณ Average True Range (ATR) แบบ Wilder Smoothing
    ใช้เป็นตัววัดความผันผวนของราคาเพื่อกำหนด SL/TP ที่สมเหตุสมผล
    """
    if df is None or len(df) < period + 2:
        return None
    rows = df.dropna(subset=["high", "low", "close"])
    if len(rows) < period + 2:
        return None
    highs = rows["high"].astype(float).tolist()
    lows = rows["low"].astype(float).tolist()
    closes = rows["close"].astype(float).tolist()

    trs = []
    for i in range(1, len(rows)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


def _plan_sl_tp_html(direction: str, price: float, atr: float, sr: dict) -> str:
    """
    สร้างแผน SL/TP อัตโนมัติจาก ATR (และแนวรับ/ต้านใกล้สุดเป็นตัวช่วย)
    ค่าเริ่มต้น: SL = 1.5xATR, TP1 = 1.5xATR (R:R 1:1), TP2 = 3xATR (R:R 1:2)
    ถ้าแนวต้าน/รับใกล้สุดอยู่ใกล้กว่า TP -> ใช้แนวนั้นเป็นเป้าแรก (สมจริงกว่า)
    """
    is_buy = direction == "BUY"
    vm = 1 if is_buy else -1

    sl_price = price - vm * 1.5 * atr
    tp1_price = price + vm * 1.5 * atr
    tp2_price = price + vm * 3.0 * atr

    # รวมแนวรับ/ต้านใกล้สุดเข้ากับเป้าแรก
    ref_note = ""
    if is_buy and sr.get("nearest_resistance"):
        nr = sr["nearest_resistance"]
        if nr["price"] < tp1_price:
            tp1_price = nr["price"]
            ref_note = f"TP1 ปรับให้ตรงแนวต้านใกล้สุด {nr['label']} ${nr['price']:,.2f}"
    if not is_buy and sr.get("nearest_support"):
        ns = sr["nearest_support"]
        if ns["price"] > tp1_price:
            tp1_price = ns["price"]
            ref_note = f"TP1 ปรับให้ตรงแนวรับใกล้สุด {ns['label']} ${ns['price']:,.2f}"

    sl_dist = abs(price - sl_price)
    tp1_dist = abs(tp1_price - price)
    tp2_dist = abs(tp2_price - price)
    rr1 = tp1_dist / sl_dist if sl_dist else 0
    rr2 = tp2_dist / sl_dist if sl_dist else 0

    def box(label, val, color, sub=""):
        return (
            f'<div style="flex:1 1 130px;min-width:130px;background:rgba(15,23,42,0.85);'
            f'border:1px solid {color};border-radius:10px;padding:8px 10px;text-align:center;">'
            f'<div style="font-size:0.7rem;color:#94a3b8;">{label}</div>'
            f'<div style="font-size:1.15rem;font-weight:800;color:{color};">${val:,.2f}</div>'
            f'{("<div style=font-size:0.72rem;color:#94a3b8;>" + sub + "</div>") if sub else ""}'
            f'</div>'
        )

    arrow = "⇈ Buy" if is_buy else "⇊ Sell"
    dir_color = "#10b981" if is_buy else "#ef4444"

    cells = (
        box("เข้าซื้อ/ขาย (Entry)", price, "#fbbf24", "ราคาปัจจุบัน")
        + box("Stop Loss", sl_price, "#ef4444", f"{abs(sl_dist):,.2f} จากราคา")
        + box("Take Profit 1", tp1_price, "#34d399", f"R:R 1:{rr1:.1f}")
        + box("Take Profit 2", tp2_price, "#34d399", f"R:R 1:{rr2:.1f}")
    )

    return (
        f'<div style="background:rgba(15,23,42,0.9);border:1px solid {dir_color};'
        f'border-radius:14px;padding:16px 20px;margin:12px 0 6px 0;">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">'
        f'<span style="font-size:1.15rem;font-weight:800;color:#f8fafc;">🎯 แผนการเทรด (SL/TP อัตโนมัติ)</span>'
        f'<span style="font-size:1.3rem;font-weight:800;color:{dir_color};">{arrow}</span>'
        f'</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;align-items:stretch;">{cells}</div>'
        f'<div style="margin-top:10px;color:#cbd5e1;font-size:0.9rem;">'
        f'📊 ความผันผวน ATR({14}) = ${atr:,.2f} · ใช้ SL/TP ที่ {abs(1.5 * atr):,.2f} / {abs(3.0 * atr):,.2f} จุดจากราคา<br/>'
        f'{"🎯 " + ref_note + "<br/>" if ref_note else ""}'
        f'⚠️ แนะนำความเสี่ยงต่อออเดอร์ไม่เกิน <b>1-2%</b> ของเงินทุน และตรวจสอบข่าวแดง/โครงสร้างราคาก่อนเสมอ'
        f'</div></div>'
    )


def compute_volatility(atr_now: float, atr_base: Optional[float]) -> dict:
    """
    เทียบ ATR ปัจจุบันกับค่าเฉลี่ยระยะยาว (baseline) เพื่อบอกระดับความผันผวน
    - ratio < 1.0  -> ปกติ (สีเขียว)
    - 1.0-1.5      -> สูง (สีเหลือง)
    - >= 1.5       -> ร้อนมาก (สีแดง)
    """
    base = atr_base or atr_now
    ratio = (atr_now / base) if base else 0.0
    if ratio >= 1.5:
        status, color = "ร้อนมาก (Very Hot)", "#ef4444"
        msg = "สเปรดกว้าง + หยุดถูกลากง่าย — ลดขนาด lot อย่าฝืนเทรด หรือรอตลาดนิ่งลงก่อน"
    elif ratio >= 1.0:
        status, color = "สูง (High)", "#f59e0b"
        msg = "ความผันผวนสูงกว่าปกติ ควรตั้ง SL กว้างขึ้นและลดขนาด lot ลง"
    else:
        status, color = "ปกติ (Normal)", "#10b981"
        msg = "ความผันผวนอยู่ในเกณฑ์ปกติ เหมาะกับการเทรดตามแผน"
    return {"ratio": ratio, "ratio_pct": ratio * 100, "status": status, "color": color, "msg": msg}


def _volatility_html(atr_now: float, atr_base: Optional[float], v: dict) -> str:
    """สร้าง HTML เกจวัดความผันผวน (ATR ปัจจุบัน vs เฉลี่ยระยะยาว)"""
    pos = min(max(v["ratio"], 0.0), 2.0) / 2.0 * 100.0
    base_txt = f"${atr_base:,.2f}" if atr_base else "—"
    return (
        f'<div style="background:rgba(15,23,42,0.9);border:1px solid {v["color"]};'
        f'border-radius:14px;padding:16px 20px;margin:12px 0 6px 0;">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">'
        f'<span style="font-size:1.15rem;font-weight:800;color:#f8fafc;">🌡️ ระดับความผันผวน (Volatility)</span>'
        f'<span style="font-size:1.1rem;font-weight:800;color:{v["color"]};">{v["status"]} · {v["ratio"]:.2f}x</span>'
        f'</div>'
        f'<div style="display:flex;gap:16px;margin-top:10px;flex-wrap:wrap;">'
        f'<span style="color:#cbd5e1;font-size:0.92rem;">ATR ปัจจุบัน: <b>${atr_now:,.2f}</b></span>'
        f'<span style="color:#cbd5e1;font-size:0.92rem;">ค่าเฉลี่ยระยะยาว: <b>{base_txt}</b></span>'
        f'</div>'
        f'<div style="position:relative;height:14px;border-radius:7px;margin:14px 0 4px 0;'
        f'background:linear-gradient(90deg,#10b981 0%,#10b981 50%,#f59e0b 50%,#f59e0b 75%,#ef4444 75%,#ef4444 100%);">'
        f'<div style="position:absolute;left:{pos}%;top:-3px;width:4px;height:20px;'
        f'background:#f8fafc;border-radius:2px;transform:translateX(-2px);box-shadow:0 0 6px rgba(248,250,252,0.8);"></div>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;color:#64748b;font-size:0.75rem;">'
        f'<span>0.5x</span><span>1x (ปกติ)</span><span>1.5x</span><span>2x</span></div>'
        f'<div style="margin-top:10px;color:#e2e8f0;font-size:0.95rem;">💡 {v["msg"]}</div>'
        f'</div>'
    )


_TRADING_SESSIONS = [
    {"name": "🌏 เอเชีย (Tokyo)", "short": "เอเชีย", "start": 7 * 60, "end": 16 * 60, "color": "#38bdf8"},
    {"name": "🇬🇧 ลอนดอน (London)", "short": "ลอนดอน", "start": 14 * 60, "end": 23 * 60, "color": "#a78bfa"},
    {"name": "🗽 นิวยอร์ก (New York)", "short": "นิวยอร์ก", "start": 19 * 60 + 30, "end": 4 * 60, "color": "#fbbf24"},
]


def _session_intervals(start: int, end: int) -> list:
    """แปลงช่วงเวลาเซสชันเป็นช่วง [ต้น, ปลาย) ในกรอบ 0–1440 นาที (เซสชันข้ามคืนแยกเป็น 2 ช่วง)"""
    if end <= start:
        return [(start, 1440), (0, end)]
    return [(start, end)]


def compute_session_overlaps(sessions: list) -> list:
    """หาช่วงเวลาที่ตลาด 2 เซสชันเปิดทับกัน (Overlap) = ช่วงที่ปริมาณหนาแน่นสูงสุด"""
    intervals = {s["name"]: _session_intervals(s["start"], s["end"]) for s in sessions}
    overlaps = []
    for i in range(len(sessions)):
        for j in range(i + 1, len(sessions)):
            a, b = sessions[i], sessions[j]
            for a1, a2 in intervals[a["name"]]:
                for b1, b2 in intervals[b["name"]]:
                    lo, hi = max(a1, b1), min(a2, b2)
                    if hi > lo:
                        overlaps.append({
                            "label": f"{a['short']} × {b['short']}",
                            "start": lo,
                            "end": hi,
                            "minutes": hi - lo,
                            "color": b["color"],
                        })
    overlaps.sort(key=lambda x: x["start"])
    return overlaps


def compute_trading_sessions(now=None) -> dict:
    """
    คำนวณสถานะช่วงเวลาเทรด (Trading Sessions) เทียบกับเวลาปัจจุบัน (ICT)
    - เช็คว่าแต่ละเซสชันเปิดอยู่หรือไม่ + เหลือเวลานับถอยหลัง / กว่าจะเปิด
    - เช็ควันหยุดสุดสัปดาห์ (ตลาด Forex ปิด เสาร์-อาทิตย์)
    """
    tz, _ = _resolve_app_tz()
    now = now or datetime.datetime.now(tz)
    now_m = now.hour * 60 + now.minute
    is_weekend = now.weekday() >= 5

    sessions = []
    for s in _TRADING_SESSIONS:
        start, end = s["start"], s["end"]
        wrap = end <= start
        if wrap:
            active = now_m >= start or now_m < end
            if active:
                end_w = end + 1440 if now_m >= start else end
                secs_end = (end_w - now_m) * 60
            else:
                secs_end = None
            next_open = start if now_m < start else start + 1440
            secs_to_open = (next_open - now_m) * 60
            end_disp = end + 1440
        else:
            active = start <= now_m < end
            secs_end = (end - now_m) * 60 if active else None
            secs_to_open = ((start - now_m) % 1440) * 60
            end_disp = end
        left = None
        width = None
        end_disp = end
        segments = []
        if wrap:
            # เซสชันข้ามเที่ยงคืน (เช่น NY 19:30–04:00) แบ่งวาดเป็น 2 ท่อนให้อยู่ภายในเส้น 24 ชม.
            seg1 = {"left": start / 1440 * 100, "width": max(0.0, (1440 - start) / 1440 * 100)}
            seg2 = {"left": 0.0, "width": max(0.0, end / 1440 * 100)}
            segments = [seg1, seg2]
            end_disp = 0
        else:
            segments = [{"left": start / 1440 * 100, "width": max(0.0, (end - start) / 1440 * 100)}]
        sessions.append(
            {
                **s,
                "active": active,
                "segments": segments,
                "secs_end": secs_end,
                "secs_to_open": secs_to_open,
            }
        )
    return {"sessions": sessions, "now": now, "is_weekend": is_weekend, "overlaps": compute_session_overlaps(sessions)}


def _fmt_hhmm_countdown(seconds: float) -> str:
    """จัดรูปแบบเวลานับถอยหลังของเซสชันให้ครบทั้งชั่วโมง+นาที (เช่น 3 ชม. 49 นาที)"""
    total = max(0, int(seconds))
    minutes, _ = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days} วัน")
    if hours:
        parts.append(f"{hours} ชม.")
    if minutes:
        parts.append(f"{minutes} นาที")
    if not parts:
        return "อีกไม่กี่อึดใจ"
    return " ".join(parts)


def _hhmm(mins: int) -> str:
    mins = int(mins)
    return f"{mins // 60 % 24:02d}:{mins % 60:02d}"


def _sessions_html(info: dict) -> str:
    """สร้าง HTML แผงช่วงเวลาเทรด (Timeline 24 ชม. + สถานะเซสชัน)"""
    now_m = info["now"].hour * 60 + info["now"].minute
    pos = now_m / 1440 * 100

    rows = ""
    for s in info["sessions"]:
        time_range = f"{_hhmm(s['start'])}–{_hhmm(s['end'])} น."
        if s["active"]:
            st_txt = (
                f'<span style="color:{s["color"]};font-weight:700;">● เปิดอยู่ · '
                f'เหลือ {_fmt_hhmm_countdown(s["secs_end"])}</span>'
            )
        else:
            st_txt = (
                f'<span style="color:#64748b;">○ เปิดใน '
                f'{_fmt_hhmm_countdown(s["secs_to_open"])}</span>'
            )
        seg_html = ""
        _opacity = "0.95" if s["active"] else "0.25"
        for seg in s["segments"]:
            seg_html += (
                f'<div style="position:absolute;left:{seg["left"]:.2f}%;'
                f'width:{seg["width"]:.2f}%;height:100%;background:{s["color"]};'
                f'opacity:{_opacity};border-radius:5px;"></div>'
            )
        rows += (
            f'<div style="margin:8px 0;">'
            f'<div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;'
            f'font-size:0.9rem;color:#cbd5e1;margin-bottom:4px;">'
            f'<span>{s["name"]} · {time_range}</span>{st_txt}</div>'
            f'<div style="position:relative;height:10px;background:rgba(255,255,255,0.08);border-radius:5px;'
            f'overflow:hidden;">'
            f'{seg_html}'
            f'<div style="position:absolute;left:{pos:.2f}%;top:-4px;width:2px;height:18px;'
            f'background:#f8fafc;box-shadow:0 0 5px rgba(248,250,252,0.8);"></div>'
            f'</div>'
            f'</div>'
        )

    banner = ""
    if info["is_weekend"]:
        banner = (
            f'<div style="margin-bottom:10px;color:#f87171;font-weight:700;">'
            f'🚫 วันหยุดสุดสัปดาห์ — ตลาดปิด จะกลับมาเปิดวันจันทร์ช่วงเช้า</div>'
        )

    overlap_rows = ""
    overlaps = info.get("overlaps") or []
    if overlaps:
        seg_html = ""
        for o in overlaps:
            seg_html += (
                f'<div style="position:absolute;left:{o["start"] / 1440 * 100:.2f}%;'
                f'width:{o["minutes"] / 1440 * 100:.2f}%;height:100%;'
                f'background:linear-gradient(90deg,#a78bfa,#fbbf24);border-radius:5px;"></div>'
            )
        seg_html += (
            f'<div style="position:absolute;left:{pos:.2f}%;top:-4px;width:2px;height:18px;'
            f'background:#f8fafc;box-shadow:0 0 5px rgba(248,250,252,0.8);"></div>'
        )
        detail = []
        active_ov = None
        next_ov = None
        for o in overlaps:
            if o["start"] <= now_m < o["end"]:
                active_ov = o
                detail.append(
                    f'<span style="color:#fcd34d;font-weight:700;">● {o["label"]} '
                    f'{_hhmm(o["start"])}–{_hhmm(o["end"])} กำลังอยู่ · '
                    f'เหลือ {_fmt_hhmm_countdown((o["end"] - now_m) * 60)}</span>'
                )
            else:
                secs_to = ((o["start"] - now_m) % 1440) * 60
                if next_ov is None or secs_to < next_ov[0]:
                    next_ov = (secs_to, o)
                detail.append(
                    f'<span style="color:#94a3b8;">○ {o["label"]} '
                    f'{_hhmm(o["start"])}–{_hhmm(o["end"])} เริ่มใน {_fmt_hhmm_countdown(secs_to)}</span>'
                )
        if not active_ov and next_ov is not None:
            detail.append(
                f'<span style="color:#fcd34d;font-weight:700;">🔜 '
                f'Overlap ถัดไป {next_ov[1]["label"]} เริ่มใน {_fmt_hhmm_countdown(next_ov[0])}</span>'
            )
        overlap_rows = (
            f'<div style="margin:12px 0 4px 0;">'
            f'<div style="font-size:0.9rem;color:#cbd5e1;margin-bottom:4px;">'
            f'🔥 <b>Overlap</b> (ตลาดเปิดทับกัน 2 แห่ง — ปริมาณหนาแน่นสูงสุด)</div>'
            f'<div style="position:relative;height:10px;background:rgba(255,255,255,0.08);'
            f'border-radius:5px;overflow:hidden;">{seg_html}</div>'
            f'<div style="display:flex;flex-direction:column;gap:2px;margin-top:6px;'
            f'font-size:0.85rem;">{"".join(detail)}</div>'
            f'</div>'
        )

    return (
        f'<div style="background:rgba(15,23,42,0.9);border:1px solid rgba(255,255,255,0.08);'
        f'border-radius:14px;padding:16px 20px;margin:12px 0 6px 0;">'
        f'<div style="font-size:1.15rem;font-weight:800;color:#f8fafc;margin-bottom:4px;">'
        f'🕐 ช่วงเวลาเทรดที่ดีที่สุด (Trading Sessions) · '
        f'<span style="color:#fbbf24;">{info["now"].strftime("%H:%M น.")}</span></div>'
        f'{banner}{rows}{overlap_rows}'
        f'<div style="margin-top:12px;padding:10px 14px;border-left:3px solid #fbbf24;'
        f'background:rgba(251,191,36,0.1);border-radius:6px;color:#fde68a;font-size:0.93rem;">'
        f'🥇 <b>ช่วงทองคำ (XAUUSD) เคลื่อนไหวแรงที่สุด:</b> 19:00–23:30 น. (เวลาไทย) '
        f'— ช่วงลอนดอนเปิดทับนิวยอร์ก ปริมาณหนาแน่น สเปรดแคบ เหมาะวางแผนเทรดรอบใหญ่</div>'
        f'<div style="margin-top:8px;color:#64748b;font-size:0.78rem;">'
        f'*เวลาโดยประมาณ (ICT UTC+7) ช่วง DST ต่างประเทศอาจเลื่อน ±1 ชม. อ้างอิงตามประกาศโบรกเกอร์</div>'
        f'</div>'
    )


def render_html_table(rows: list, colors: list, actual_col: str, band_keys: list = None) -> str:
    """
    สร้าง HTML Table ที่อ่านง่าย ตัวเลขใหญ่ พอดีกับคอลัมน์
    :param rows: list ของ dict (แต่ละ dict คือ 1 แถว)
    :param colors: list สีของคอลัมน์ Actual ตามแถว (ว่าง = สีปกติ)
    :param actual_col: ชื่อคอลัมน์ Actual ที่จะระบายสี
    :param band_keys: ลิสต์คีย์กลุ่มแถบสี (เช่น วันที่) เพื่อแบ่งแถว/วันในตารางให้ดูแยกง่าย
                      แถวที่คีย์ต่างจากแถวบน จะได้เส้นคั่นสีเหลือง + สลับสีพื้นหลังรายวัน
    :return: HTML string
    """
    if not rows:
        return ""
    columns = list(rows[0].keys())

    # คำนวณแถบสีพื้นหลังสลับตามกลุ่มวัน + เส้นคั่นสีเหลืองตอนเปลี่ยนวัน
    row_style = [""] * len(rows)
    if band_keys:
        band_id = 0
        prev_key = None
        for i, key in enumerate(band_keys[: len(rows)]):
            if i > 0 and prev_key is not None and key != prev_key:
                band_id += 1
            prev_key = key
            bg = "rgba(59,130,246,0.07)" if band_id % 2 == 0 else "rgba(255,255,255,0.02)"
            sep = (
                "border-top:2px solid #fbbf24;"
                if i > 0 and band_keys[i] != band_keys[i - 1]
                else ""
            )
            row_style[i] = f"background:{bg};{sep}"

    thead = "".join(f"<th>{c}</th>" for c in columns)
    tbody = ""
    for i, row in enumerate(rows):
        cells = ""
        for c in columns:
            val = row[c]
            if c == actual_col and colors and i < len(colors) and colors[i]:
                cells += (
                    f'<td style="color:{colors[i]};font-weight:700;text-align:center;'
                    f'white-space:nowrap;">{val}</td>'
                )
            elif c in _TITLE_COLUMN_KEYS:
                cells += f'<td style="text-align:left;">{_news_title_html(str(val))}</td>'
            else:
                cells += '<td style="text-align:center;">' + str(val) + "</td>"
        tbody += f"<tr style='{row_style[i]}'>{cells}</tr>"
    return (
        '<div class="news-table-wrap">'
        f'<table class="news-table"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>'
        "</div>"
    )

# ==========================================
# 3. Sidebar Controls & System Status
# ==========================================
with st.sidebar:
    st.markdown("## ⚡ Forex Trading Assistant")
    st.caption("ระบบวิเคราะห์ EMA Cross & แจ้งเตือนข่าวแดง ForexFactory")
    st.markdown("---")

    # ดึงค่าเริ่มต้นคู่เงิน ไทม์เฟรม และ EMA จาก Streamlit Secrets (ปลอดภัยทุกเวอร์ชัน)
    default_symbol = str(_st_secret("SYMBOL", "XAUUSDm"))
    default_tf = str(_st_secret("TIMEFRAME", "M5"))
    default_ema_fast = int(_st_secret("EMA_FAST", 50))
    default_ema_slow = int(_st_secret("EMA_SLOW", 150))

    # ตัวเลือกตั้งค่า Symbol & Timeframe (กำหนดให้ดึงค่าเริ่มต้นจาก Secrets)
    selected_symbol = st.selectbox(
        "สัญลักษณ์คู่เงิน (Symbol)",
        options=[default_symbol, "EURUSD", "GBPUSD", "USDJPY", "BTCUSD"],
        index=0,
    )

    # แปลงชื่อเล่นไทม์เฟรมให้ตรงกับตัวเลือกในแอปของคุณ
    tf_options = ["M5", "M15", "H1", "H4", "D1"]
    try:
        tf_index = tf_options.index(default_tf)
    except ValueError:
        tf_index = 0  # ถ้าหาไม่เจอให้เลือกตัวแรก (M5) เป็นค่าเริ่มต้น

    selected_tf = st.selectbox(
        "กรอบเวลา (Timeframe)",
        options=tf_options,
        index=tf_index,
        key="select_tf",
    )

    st.markdown("---")
    st.markdown("### ⚙️ การตั้งค่า EMA")
    col_ema1, col_ema2 = st.columns(2)
    with col_ema1:
        fast_ema = st.number_input("EMA Fast", min_value=5, max_value=200, value=default_ema_fast)
    with col_ema2:
        slow_ema = st.number_input("EMA Slow", min_value=20, max_value=500, value=default_ema_slow)

    indicator_service.fast_period = fast_ema
    indicator_service.slow_period = slow_ema

    st.markdown("---")
    st.markdown("### 📲 ทดสอบการแจ้งเตือน LINE")

    # ดึงค่าจากหน้า Streamlit Secrets มาใช้งานโดยตรงแทนระบบ config เดิม
    channel_access_token = str(_st_secret("LINE_CHANNEL_ACCESS_TOKEN", ""))
    user_id = str(_st_secret("LINE_USER_ID", ""))
    has_token = bool(channel_access_token and user_id)

    st.caption(
        f"สถานะ LINE Config: "
        f"{'✅ Token & User ID พร้อมใช้งาน' if has_token else '❌ Token/User ID ว่าง'}"
    )
    if not has_token:
        st.warning("ไปตั้งค่า LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID ใน Streamlit Secrets ก่อนนะครับ")

    if st.button("🔔 ส่งข้อความทดสอบ LINE", use_container_width=True):
        with st.spinner("กำลังส่งข้อความทดสอบ..."):
            notifier = notification_service.notifier

            # บังคับป้อนรหัสจาก Streamlit Secrets เข้าไปในระบบแจ้งเตือนโดยตรง
            if has_token:
                notifier.channel_access_token = channel_access_token
                notifier.user_id = user_id

            last_error = None
            if has_token:
                _status_ok = False
                try:
                    _status_ok = notifier.send_via_messaging_api(
                        "🔔 [Test Alert] ทดสอบการเชื่อมต่อระบบแจ้งเตือน\n"
                        "ระบบผู้ช่วยเทรด Forex (Trading Assistant & Alert System)\n"
                        "สถานะ: ระบบทำงานปกติ พร้อมส่งสัญญาณ Live Cross และข่าวเศรษฐกิจครับ 🚀"
                    )
                except Exception as e:
                    last_error = repr(e)
                if _status_ok:
                    st.success("ส่งข้อความทดสอบผ่าน LINE Messaging API สำเร็จ!")
                else:
                    st.error(f"LINE Messaging API ส่งไม่สำเร็จ {last_error or ''}")
                    st.caption(
                        "ตรวจสอบว่า: 1) Token ถูกต้อง 2) User ID ถูกต้อง "
                        "3) user ต้องมากด 'Add friend' / follow LINE Official Account แล้ว"
                    )
            else:
                st.error("ไม่พบ Token ใดเลย กรุณาตั้งค่า Secrets ก่อน")

    if st.button("📢 ส่งสรุปข่าวแดงสัปดาห์นี้เข้า LINE ทันที", use_container_width=True):
        with st.spinner("กำลังดึงข่าวและส่งเข้า LINE..."):
            news_items = news_service.fetch_this_week_news(only_high_impact=True)
            msg = news_service.format_weekly_line_message(news_items)
            res = notification_service.send_weekly_news_alert(msg)
            if res:
                st.success("ส่งสรุปข่าวประจำสัปดาห์เข้า LINE สำเร็จ!")
            else:
                st.error("ส่งไม่สำเร็จ")

    st.markdown("---")
    auto_refresh = st.checkbox("🔄 รีเฟรชเองอัตโนมัติ (ตรงเมื่อแท่งเทียนปิด)", value=False)
    if auto_refresh:
        wait_sec = seconds_to_next_candle(selected_tf)
        st.info(
            f"โหมด Auto-refresh เปิดใช้งาน — จะรีเฟรชหน้าอัตโนมัติทุก ~{wait_sec} วินาที "
            f"(พอดีกับแท่ง {selected_tf} ปิด) ค่า EMA Distance จะตรงกับข้อมูลจริงเสมอ"
        )
        st.markdown(
            f'<meta http-equiv="refresh" content="{wait_sec}">',
            unsafe_allow_html=True,
        )

# ==========================================
# 4. Main Header & Top Status
# ==========================================
st.markdown("# 🚀 Forex Trading Assistant & Live Alert System")
render_live_clock(selected_symbol)

# ดึงข้อมูลราคาจาก Yahoo Finance (ใช้ Cache เพื่อให้โหลดเร็วขึ้นเมื่อกลับมาดูซ้ำ)
with st.spinner("กำลังดึงข้อมูลแท่งเทียนและคำนวณอินดิเคเตอร์..."):
    df_rates = drop_last_open_candle(cached_rates(selected_symbol, selected_tf, 800))

# คำนวณ EMA บนข้อมูลชุดเดียวกับที่ใช้วิเคราะห์ เพื่อให้ตัวเลขทุกจุด
# (เกจ EMA Distance / metrics / กราฟแท่งเทียน) ตรงกันเสมอ ไม่เพี้ยน
df_ema_full = indicator_service.calculate_ema(df_rates) if df_rates is not None and len(df_rates) > 0 else None

signal_result = None
if df_rates is not None and len(df_rates) > 0:
    signal_result = indicator_service.analyze(df_rates, symbol=selected_symbol, timeframe=selected_tf)

# ==========================================
# 5. Section 1: สถานะอินดิเคเตอร์ & เกจวัด EMA (Responsive Layout)
# ==========================================
st.markdown("## 📊 1. สถานะอินดิเคเตอร์ & การตัดกันของ EMA (EMA Cross)")

if signal_result:
    # สรุปเวลาแท่งเทียนปิด (ICT) ที่เกิดการตัดกันล่าสุด + ระยะเวลาที่ต่อเนื่องมาแล้ว
    # แสดงใต้แบนเนอร์เทรนเสมอ (ถ้าไม่พบ Cross จะแจ้งช่วงข้อมูลแทน ไม่ปล่อยว่าง)
    cross_occur = ""
    if signal_result.cross_signal == CrossSignal.CROSS_UP:
        _dur = _fmt_duration(datetime.datetime.utcnow() - _candle_as_naive_utc(signal_result.candle_time))
        if signal_result.is_bullish:
            _extra = f" — ต่อเนื่องมาแล้ว {_dur}"
        else:
            _extra = " — แต่เทรนปัจจุบันหันกลับแล้ว (รอ Cross ใหม่บนแท่งที่ปิด)"
        cross_occur = (
            f"🚀 เกิดการตัดขึ้น (CROSS UP) ในแท่งเทียนที่ปิด เวลา "
            f"<b>{signal_result._format_candle_time_thai()}</b>{_extra}"
        )
    elif signal_result.cross_signal == CrossSignal.CROSS_DOWN:
        _dur = _fmt_duration(datetime.datetime.utcnow() - _candle_as_naive_utc(signal_result.candle_time))
        if signal_result.is_bearish:
            _extra = f" — ต่อเนื่องมาแล้ว {_dur}"
        else:
            _extra = " — แต่เทรนปัจจุบันหันกลับแล้ว (รอ Cross ใหม่บนแท่งที่ปิด)"
        cross_occur = (
            f"🔻 เกิดการตัดลง (CROSS DOWN) ในแท่งเทียนที่ปิด เวลา "
            f"<b>{signal_result._format_candle_time_thai()}</b>{_extra}"
        )
    else:
        # ไม่พบ Cross ในช่วงข้อมูลที่โหลดมา -> ไม่ปล่อยว่าง ให้แจ้งช่วงข้อมูลแทน
        # (มักเกิดเพราะ Cross เก่าเกินขอบข้อมูล หรือเพิ่งตัดบนแท่งที่ยังไม่ปิด)
        _n_bars = len(df_rates) if df_rates is not None else 0
        _start_str = _fmt_ts_bangkok(df_rates["time"].iloc[0]) if (df_rates is not None and len(df_rates) > 0) else "-"
        _last_cross = _last_cross_from_state(selected_symbol, selected_tf)
        if _last_cross:
            _lc_naive = _state_candle_to_naive_utc(_last_cross["candle_time"])
            _lc_sig = str(_last_cross.get("signal", "")).upper()
            if _lc_sig == "CROSS_UP":
                _lc_mark = "🚀 CROSS UP (ตัดขึ้น)"
            elif _lc_sig == "CROSS_DOWN":
                _lc_mark = "🔻 CROSS DOWN (ตัดลง)"
            else:
                _lc_mark = "EMA Cross"
            if _lc_naive is not None:
                _lc_dur = _fmt_duration(datetime.datetime.utcnow() - _lc_naive)
                cross_occur = (
                    f"ℹ️ ในข้อมูล {_n_bars} แท่งล่าสุด (เริ่ม {_start_str}) ไม่พบการตัดกัน (CROSS) — "
                    f"แต่ Cross ครั้งล่าสุดเป็นดังนี้<br>"
                    f"📌 <b>EMA Cross ครั้งล่าสุด:</b> {_lc_mark} เวลา "
                    f"<b>{_fmt_ts_bangkok(_lc_naive)}</b> (ผ่านมาแล้ว {_lc_dur})"
                )
            else:
                cross_occur = (
                    f"ℹ️ ยังไม่พบการตัดกัน (CROSS) ในข้อมูล {_n_bars} แท่งล่าสุด "
                    f"(ช่วงข้อมูลเริ่ม {_start_str}) — แนวโน้มนี้ต่อเนื่องมาก่อนหน้าข้อมูลที่แสดง หรือกำลังตัดกันบนแท่งที่ยังไม่ปิด"
                )
        else:
            cross_occur = (
                f"ℹ️ ยังไม่พบการตัดกัน (CROSS) ในข้อมูล {_n_bars} แท่งล่าสุด "
                f"(ช่วงข้อมูลเริ่ม {_start_str}) — แนวโน้มนี้ต่อเนื่องมาก่อนหน้าข้อมูลที่แสดง หรือกำลังตัดกันบนแท่งที่ยังไม่ปิด"
            )

    # Banner แสดงเทรนแบบเต็มความกว้างหน้าจอ
    if signal_result.is_bullish:
        st.markdown(
            f"""
            <div class="trend-bullish">
                <h2 style="color: #10b981; margin:0; font-size: 1.8rem;">🟢 CURRENT TREND: BULLISH</h2>
                <p style="margin: 5px 0 0 0; color: #a7f3d0; font-size: 1.1rem; font-weight: 500;">
                    ⏱️ Timeframe: {selected_tf} | EMA 50 อยู่เหนือ EMA 150 (โมเมนตัมขาขึ้น)
                </p>
                {('<p style="margin: 8px 0 0 0; color: #6ee7b7; font-size: 1rem;">' + cross_occur + '</p>') if cross_occur else ''}
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif signal_result.is_bearish:
        st.markdown(
            f"""
            <div class="trend-bearish">
                <h2 style="color: #ef4444; margin:0; font-size: 1.8rem;">🔴 CURRENT TREND: BEARISH</h2>
                <p style="margin: 5px 0 0 0; color: #fecaca; font-size: 1.1rem; font-weight: 500;">
                    ⏱️ Timeframe: {selected_tf} | EMA 50 อยู่ใต้ EMA 150 (โมเมนตัมขาลง)
                </p>
                {('<p style="margin: 8px 0 0 0; color: #fca5a5; font-size: 1rem;">' + cross_occur + '</p>') if cross_occur else ''}
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="trend-neutral">
                <h2 style="color: #94a3b8; margin:0; font-size: 1.8rem;">⚪ CURRENT TREND: NEUTRAL</h2>
                <p style="margin: 5px 0 0 0;">⏱️ Timeframe: {selected_tf} | เส้น EMA กำลังเกาะกลุ่มกัน</p>
                {('<p style="margin: 8px 0 0 0; font-size: 1rem;">' + cross_occur + '</p>') if cross_occur else ''}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # แบ่งหน้าจอเป็น 2 ฝั่ง: ซ้าย (ตัวเลข 4 ช่อง + MTF) | ขวา (หน้าปัด Gauge)
    col_metrics, col_gauge = st.columns([6, 4])

    with col_metrics:
        # ข้อมูล Metric ตัวเลขหลัก 4 ช่อง
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric(
                label=f"ราคาปิด ({selected_symbol})",
                value=f"{signal_result.close_price:,.2f}",
            )
        with m2:
            st.metric(
                label=f"EMA {fast_ema}",
                value=f"{signal_result.ema_fast:,.2f}",
                delta=f"{signal_result.ema_fast - signal_result.ema_slow:+.2f}",
            )
        with m3:
            st.metric(
                label=f"EMA {slow_ema}",
                value=f"{signal_result.ema_slow:,.2f}",
            )
        with m4:
            cross_text = "ไม่มีการตัดกัน"
            cross_help = None
            if signal_result.cross_signal == CrossSignal.CROSS_UP:
                cross_text = "🚀 ตัดขึ้น (Uptrend)"
                cross_help = f"ล่าสุด: {signal_result._format_candle_time_thai()}"
            elif signal_result.cross_signal == CrossSignal.CROSS_DOWN:
                cross_text = "🔻 ตัดลง (Downtrend)"
                cross_help = f"ล่าสุด: {signal_result._format_candle_time_thai()}"
            st.metric(
                label="สัญญาณล่าสุด (Cross)",
                value=cross_text,
                help=cross_help,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # สรุปเทรน Multi-Timeframe (MTF) ภายในคอลัมน์ซ้าย
        st.markdown("#### 🧭 สรุปเทรน Multi-Timeframe (MTF)")
        # จัดเป็น 2 แถว (แถวบน 3 ไทม์เฟรม, แถวล่าง 2 ไทม์เฟรม) เพื่อไม่ให้มีพื้นที่ว่างด้านล่าง
        mtf_rows = [["M5", "M15", "H1"], ["H4", "D1"]]

        # โหลดราคา + วิเคราะห์เทรนทุกไทม์เฟรมแบบขนาน (ThreadPool) 
        # แทนการวนลูป fetch ทีละตัว เพื่อลดเวลาหน้าแรกค้าง (5 เฟรม → เหลือ ~เท่าเฟรมเดียว)
        mtf_tfs = [tf for row in mtf_rows for tf in row]

        def _mtf_analyze_one(tf: str):
            tf_df = drop_last_open_candle(cached_rates(selected_symbol, tf, 800))
            trend = "NEUTRAL"
            color = "#94a3b8"
            if tf_df is not None and len(tf_df) > 0:
                res = indicator_service.analyze(tf_df, symbol=selected_symbol, timeframe=tf)
                if res:
                    if res.is_bullish:
                        trend, color = "BULLISH 🟢", "#10b981"
                    elif res.is_bearish:
                        trend, color = "BEARISH 🔴", "#ef4444"
            return tf, trend, color

        mtf_results = {}
        with ThreadPoolExecutor(max_workers=min(len(mtf_tfs), 5)) as _pool:
            for _tf, _trend, _col in _pool.map(_mtf_analyze_one, mtf_tfs):
                mtf_results[_tf] = (_trend, _col)

        for row in mtf_rows:
            row_cols = st.columns(len(row))
            for col, tf in zip(row_cols, row):
                tf_trend, tf_color = mtf_results[tf]

                with col:
                    # กล่องสรุปเทรนแบบกดได้: คลิกเพื่อสลับเลือกกรอบเวลา (Timeframe) ใน sidebar
                    btn_label = f"{tf}\n{tf_trend}"
                    # เน้นไทม์เฟรมที่กำลังเลือกอยู่
                    is_active = (tf == selected_tf)
                    # ใช้ on_click callback (รันก่อน widget instantiate) เพื่อไม่ให้ error
                    # ตอนเขียนค่า selectbox ผ่าน session_state
                    st.button(
                        btn_label,
                        key=f"mtf_{tf}",
                        use_container_width=True,
                        type="primary" if is_active else "secondary",
                        on_click=_switch_timeframe,
                        args=(tf,),
                    )
                    # ระบายสีขอบล่างของปุ่มตามสถานะเทรนของแต่ละไทม์เฟรม
                    st.markdown(
                        f"""
                        <style>
                        .st-key-mtf_{tf} button {{
                            border-bottom: 3px solid {tf_color} !important;
                            text-align: center;
                            font-weight: 600;
                        }}
                        .st-key-mtf_{tf} button:hover {{
                            filter: brightness(1.25);
                            border-color: {tf_color};
                        }}
                        </style>
                        """,
                        unsafe_allow_html=True,
                    )

    with col_gauge:
        # หน้าปัดวัดระยะห่าง EMA แบบยืดหยุ่น (Responsive)
        spread_ema = signal_result.ema_fast - signal_result.ema_slow
        max_range = max(abs(spread_ema) * 2, 10.0)
        gauge_color = "#10b981" if signal_result.is_bullish else "#ef4444"

        fig_gauge = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=spread_ema,
                domain={"x": [0, 1], "y": [0, 1]},
                number={"font": {"color": "#f8fafc", "size": 36}, "valueformat": ".1f"},
                gauge={
                    "axis": {"range": [-max_range, max_range], "tickwidth": 1, "tickcolor": "#94a3b8"},
                    "bar": {"color": gauge_color},
                    "bgcolor": "rgba(30, 41, 59, 0.5)",
                    "borderwidth": 1,
                    "bordercolor": "rgba(255,255,255,0.1)",
                    "steps": [
                        {"range": [-max_range, 0], "color": "rgba(239, 68, 68, 0.15)"},
                        {"range": [0, max_range], "color": "rgba(16, 185, 129, 0.15)"},
                    ],
                    "threshold": {
                        "line": {"color": "#f59e0b", "width": 3},
                        "thickness": 0.75,
                        "value": spread_ema,
                    },
                },
            )
        )
        fig_gauge.update_layout(
            autosize=True,
            height=220,
            margin=dict(l=10, r=10, t=40, b=10),
            title=dict(text="📏 EMA Distance (EMA50 - EMA150)", x=0.5, xanchor="center", font=dict(size=14, color="#cbd5e1")),
            paper_bgcolor="rgba(0,0,0,0)",
            font={"color": "#e2e8f0"},
        )
        st.plotly_chart(fig_gauge, use_container_width=True, config={"displayModeBar": False})

        st.markdown(
            """
            <div style="background-color: rgba(56, 189, 248, 0.1); border-left: 4px solid #38bdf8; padding: 10px 15px; border-radius: 4px; font-size: 0.9rem; color: #cbd5e1; margin-top: -10px;">
                💡 <b>EMA Distance คืออะไร?</b><br>
                คือ <b>"ระยะห่าง"</b> ระหว่างเส้น EMA 50 กับ EMA 150 <br>
                • <b>ค่าเป็นบวก (สีเขียว)</b>: EMA 50 อยู่เหนือ 150 แสดงถึง <b>โมเมนตัมขาขึ้น (Uptrend)</b> ยิ่งตัวเลขมาก ยิ่งขึ้นแรง<br>
                • <b>ค่าติดลบ (สีแดง)</b>: EMA 50 อยู่ใต้ 150 แสดงถึง <b>โมเมนตัมขาลง (Downtrend)</b> ยิ่งติดลบมาก ยิ่งลงแรง<br>
                • <b>ค่าเข้าใกล้ 0</b>: กราฟกำลังพักตัว (Sideway) หรือ <b>เตรียมเกิดการตัดกัน (Cross)</b>
            </div>
            """,
            unsafe_allow_html=True
        )

else:
    st.warning(
        "⚠️ ไม่สามารถดึงข้อมูลราคาได้ในขณะนี้ กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ตหรือลองใหม่ภายหลัง"
    )


# ==========================================
# 6. Interactive Candlestick + EMA Chart
# ==========================================
if df_ema_full is not None and len(df_ema_full) > 0:
    with st.expander("📈 ดูกราฟแท่งเทียน Candlestick พร้อมเส้น EMA 50 / 150 แบบละเอียด", expanded=False):
        df_plot = df_ema_full.tail(120)

        fig_chart = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.04,
            row_heights=[0.8, 0.2],
        )

        # แท่งเทียน Candlestick
        fig_chart.add_trace(
            go.Candlestick(
                x=df_plot["time"],
                open=df_plot["open"],
                high=df_plot["high"],
                low=df_plot["low"],
                close=df_plot["close"],
                name="Price",
                increasing_line_color="#10b981",
                decreasing_line_color="#ef4444",
            ),
            row=1,
            col=1,
        )

        # เส้น EMA 50 (สีฟ้าอ่อน / นีออน)
        fast_col = f"ema_{fast_ema}"
        if fast_col in df_plot:
            fig_chart.add_trace(
                go.Scatter(
                    x=df_plot["time"],
                    y=df_plot[fast_col],
                    line=dict(color="#38bdf8", width=2),
                    name=f"EMA {fast_ema} (Fast)",
                ),
                row=1,
                col=1,
            )

        # เส้น EMA 150 (สีส้มนีออน)
        slow_col = f"ema_{slow_ema}"
        if slow_col in df_plot:
            fig_chart.add_trace(
                go.Scatter(
                    x=df_plot["time"],
                    y=df_plot[slow_col],
                    line=dict(color="#f97316", width=2.5),
                    name=f"EMA {slow_ema} (Slow)",
                ),
                row=1,
                col=1,
            )

        # เส้นแนวรับ/แนวต้านอัตโนมัติ (SR) ซ้อนบนกราฟ
        sr_info = compute_support_resistance(df_ema_full)
        atr_value = compute_atr(df_ema_full)
        atr_base_value = compute_atr(df_ema_full, 100) if len(df_ema_full) > 100 else None
        _lo = float(df_plot["low"].min()) * 0.995
        _hi = float(df_plot["high"].max()) * 1.005
        for lv in sr_info["levels"]:
            if not (_lo <= lv["price"] <= _hi):
                continue
            _c = "#f87171" if lv["side"] == "R" else "#34d399"
            if lv["kind"] == "Pivot":
                _c = "#fbbf24"
            _dash = "dash" if lv["kind"] == "Round" else "dot"
            fig_chart.add_shape(
                type="line",
                x0=df_plot["time"].iloc[0],
                x1=df_plot["time"].iloc[-1],
                y0=lv["price"],
                y1=lv["price"],
                line=dict(color=_c, width=1, dash=_dash),
                row=1,
                col=1,
            )
            fig_chart.add_annotation(
                x=df_plot["time"].iloc[0],
                y=lv["price"],
                text=lv["label"],
                showarrow=False,
                xanchor="left",
                xshift=2,
                font=dict(size=10, color=_c),
                row=1,
                col=1,
            )

        # ปริมาณ Volume ด้านล่าง
        fig_chart.add_trace(
            go.Bar(
                x=df_plot["time"],
                y=df_plot["tick_volume"],
                marker_color="rgba(148, 163, 184, 0.4)",
                name="Tick Volume",
            ),
            row=2,
            col=1,
        )

        fig_chart.update_layout(
            autosize=True,
            template="plotly_dark",
            height=500,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="#0b0e14",
            plot_bgcolor="rgba(15, 23, 42, 0.5)",
            xaxis_rangeslider_visible=False,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_chart, use_container_width=True)

st.markdown("---")

# ==========================================
# 7. Section 2: ระบบรวบรวมข่าวแดงจาก ForexFactory
# ==========================================
st.markdown("## 🔴 2. ตารางข่าวเศรษฐกิจสีแดง (ForexFactory High-Impact News)")
st.caption("ระบบรวบรวมและกรองเฉพาะข่าวความสำคัญสูง (High-Impact / ข่าวแดง) ที่ส่งผลกระทบต่อความผันผวนของราคา")

# ดึงข่าวสัปดาห์นี้ (news_service มีระบบ cache ภายใน 5 นาทีอยู่แล้ว)
all_news_this_week = news_service.fetch_this_week_news(only_high_impact=False)
red_news_this_week = [n for n in all_news_this_week if n.is_high_impact]

# กรองสกุลเงิน (Global Filter) - ค่าเริ่มต้นแสดงเฉพาะ USD
currency_filter = st.multiselect(
    "กรองสกุลเงิน (Currency)",
    options=["ALL", "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD", "CHF"],
    default=["USD"],
)

if "ALL" not in currency_filter and currency_filter:
    red_news_this_week = [n for n in red_news_this_week if n.country in currency_filter]

# การแสดงสถิติเบื้องต้น
kpi1, kpi2, kpi3 = st.columns(3)
with kpi1:
    st.metric("ข่าวแดง (High-Impact) ทั้งหมดในสัปดาห์นี้", f"{len(red_news_this_week)} ข่าว")
with kpi2:
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    today_red_news = [n for n in red_news_this_week if n.date_local.strftime("%Y-%m-%d") == today_str]
    st.metric("ข่าวแดงวันนี้", f"{len(today_red_news)} ข่าว")
with kpi3:
    # สกุลเงินที่มีข่าวแดงมากที่สุด
    if red_news_this_week:
        currencies = [n.country for n in red_news_this_week]
        top_curr = max(set(currencies), key=currencies.count)
        st.metric("สกุลเงินที่ได้รับผลกระทบสูงสุด", f"{top_curr} ({currencies.count(top_curr)} ข่าว)")
    else:
        st.metric("สกุลเงินที่ได้รับผลกระทบสูงสุด", "-")

# 🎯 สรุปทิศทางเทรด (Trade Verdict) — ภาพรวมว่าเทรดไปทางไหน
# (วางหลัง red_news_this_week ซึ่งมีข่าวแดงครบ + กรองสกุลเงินแล้ว)
if "mtf_results" in locals():
    verdict = compute_trade_verdict(mtf_results, selected_tf, red_news_this_week)
    st.markdown(
        _verdict_panel_html(verdict, countdown_to_news),
        unsafe_allow_html=True,
    )

    # 📏 แนวรับ/แนวต้านอัตโนมัติ — แสดงต่อจาก Verdict (ใช้ sr_info จากกราฟ Section 6)
    if "sr_info" in locals() and sr_info and sr_info["levels"]:
        st.markdown(_sr_panel_html(sr_info), unsafe_allow_html=True)

    # 🎯 แผน SL/TP อัตโนมัติจาก ATR — แสดงเฉพาะเมื่อ Verdict แนะนำเทรดได้จริง
    _atrv = locals().get("atr_value") if "atr_value" in locals() else None
    if _atrv and verdict["verdict"] in ("BUY", "SELL") and sr_info and sr_info["current_close"]:
        st.markdown(
            _plan_sl_tp_html(verdict["verdict"], sr_info["current_close"], _atrv, sr_info),
            unsafe_allow_html=True,
        )
    elif _atrv:
        # แม้ยังไม่แนะนำเทรด ก็ให้เห็นความผันผวนเพื่อวางแผนรอ
        st.markdown(
            f'<div style="background:rgba(15,23,42,0.8);border:1px solid #94a3b8;border-radius:12px;'
            f'padding:12px 18px;margin:12px 0 6px 0;color:#cbd5e1;font-size:0.95rem;">'
            f'📊 ความผันผวน ATR(14) = ${_atrv:,.2f} — ยังไม่แนะนำวางแผน SL/TP เพราะ Verdict = '
            f'<b>{verdict["verdict"]}</b> รอสัญญาณชัดเจนก่อนเข้าออเดอร์'
            f'</div>',
            unsafe_allow_html=True,
        )

    # 🌡️ เกจวัดความผันผวน (ATR ปัจจุบัน vs เฉลี่ยระยะยาว) — แสดงเสมอเมื่อมีข้อมูล
    if _atrv:
        _atr_base = locals().get("atr_base_value") if "atr_base_value" in locals() else None
        _vol = compute_volatility(_atrv, _atr_base)
        st.markdown(_volatility_html(_atrv, _atr_base, _vol), unsafe_allow_html=True)

    # 🕐 ช่วงเวลาเทรด (Trading Sessions) — แสดงเสมอ
    _sess_info = compute_trading_sessions()
    st.markdown(_sessions_html(_sess_info), unsafe_allow_html=True)

# แท็บแสดง 3 มุมมองตามโจทย์: สรุปรายสัปดาห์, ดูแยกตามวัน, และ ปฏิทินรายเดือน
tab_weekly, tab_daily, tab_calendar = st.tabs(
    [
        "📅 1. สรุปรายสัปดาห์ (Weekly Summary)",
        "📆 2. ดูแยกตามวัน (Day Selector)",
        "🗓️ 3. ปฏิทินรายเดือน (Monthly Calendar View)",
    ]
)

# ----------------------------------------------------
# Tab 1: มุมมองสรุปรายสัปดาห์ (Weekly Summary Table)
# ----------------------------------------------------
with tab_weekly:
    st.markdown("### 📋 ตารางสรุปข่าวแดงของสัปดาห์ปัจจุบัน")
    st.caption("🟢 ตัวเลขสีเขียว = ดีกว่าคาดการณ์ | 🔴 ตัวเลขสีแดง = แย่กว่าคาดการณ์ | ไม่มีสี = เท่ากับคาดการณ์")
    if red_news_this_week:
        table_data = []
        actual_colors = []
        for n in red_news_this_week:
            table_data.append(
                {
                    "วัน": n.day_name_th,
                    "วันที่": n.date_local.strftime("%d/%m/%Y"),
                    "เวลา (เวลาไทย)": n.time_str,
                    "นับถอยหลัง": countdown_to_news(n.date_local),
                    "สกุลเงิน": n.country,
                    "ชื่อข่าวเศรษฐกิจ": n.title,
                    "ตัวเลขคาดการณ์ (Forecast)": n.forecast or "-",
                    "ตัวเลขจริง (Actual)": format_actual_text(n),
                    "ตัวเลขเดิม (Previous)": n.previous or "-",
                }
            )
            actual_colors.append(actual_color_code(n))
        st.markdown(
            render_html_table(
                table_data,
                actual_colors,
                "ตัวเลขจริง (Actual)",
                band_keys=[n.date_local.strftime("%Y-%m-%d") for n in red_news_this_week],
            ),
            unsafe_allow_html=True,
        )
    else:
        st.success("🟢 ยินดีด้วย! สัปดาห์นี้ไม่มีข่าวสีแดง สามารถวางแผนเทรดได้อย่างราบรื่น")

# ----------------------------------------------------
# Tab 2: ดูแยกตามวัน (Day Selector)
# ----------------------------------------------------
with tab_daily:
    st.markdown("### 🔍 ตรวจสอบข่าวแดงแยกตามรายวัน")

    business_days = news_service.get_week_business_days()
    day_options = {}
    thai_days = {0: "วันจันทร์", 1: "วันอังคาร", 2: "วันพุธ", 3: "วันพฤหัสบดี", 4: "วันศุกร์"}

    for d in business_days:
        label = f"{thai_days.get(d.weekday())} ({d.strftime('%d/%m/%Y')})"
        day_options[label] = d

    # ตัวเลือก Day Selector
    selected_day_label = st.radio(
        "เลือกวันที่ต้องการดูข่าวแดง:",
        options=list(day_options.keys()),
        horizontal=True,
    )

    selected_date = day_options[selected_day_label]
    selected_date_str = selected_date.strftime("%Y-%m-%d")

    grouped_news = news_service.group_by_day(red_news_this_week)
    day_news_items = grouped_news.get(selected_date_str, [])

    # เงื่อนไขสำคัญตามโจทย์: หากวันไหน 'ไม่มีข่าวสีแดง' ให้พิมพ์บอกสถานะอย่างชัดเจน
    if not day_news_items:
        st.markdown(
            f"""
            <div class="safe-trading-banner">
                🟢 <b>{selected_day_label}</b>: วันนี้ไม่มีข่าวสีแดง สามารถเทรดได้ตลอดวัน 🎉
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='margin: 10px 0; color: #f87171; font-weight: bold;'>⚠️ พบข่าวสีแดงทั้งหมด {len(day_news_items)} ข่าว ใน {selected_day_label}:</div>",
            unsafe_allow_html=True,
        )

        # แบนเนอร์แจ้งเตือนข่าวที่กำลังจะออกในอีก 10 นาที
        now_daily = datetime.datetime.now().astimezone()
        urgent_news = [
            item for item in day_news_items
            if 0 < (item.date_local - now_daily).total_seconds() <= 600
        ]
        if urgent_news:
            urgent_list = "".join(
                f"• 🔴 {item.time_str} [{item.country}] {item.title}<br/>"
                for item in urgent_news
            )
            st.markdown(
                f"""
                <div style="background:rgba(239,68,68,0.15);border:1px solid #ef4444;border-radius:10px;
                            padding:12px 16px;margin:10px 0;">
                    <b style="color:#fecaca;">⏰ ข่าวกำลังจะออกในอีกไม่ถึง 10 นาที!</b><br/>
                    <span style="color:#fecaca;font-size:0.95rem;">{urgent_list}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        
        day_table = []
        day_colors = []
        for item in day_news_items:
            day_table.append(
                {
                    "เวลา (เวลาไทย)": item.time_str,
                    "นับถอยหลัง": countdown_to_news(item.date_local),
                    "สกุลเงิน": item.country,
                    "ชื่อข่าว": item.title,
                    "Forecast": item.forecast or "-",
                    "Actual": format_actual_text(item),
                    "Previous": item.previous or "-",
                }
            )
            day_colors.append(actual_color_code(item))
        st.markdown(
            render_html_table(day_table, day_colors, "Actual"),
            unsafe_allow_html=True,
        )

# ----------------------------------------------------
# Tab 3: ปฏิทินรายเดือน (Monthly Calendar View)
# ----------------------------------------------------
with tab_calendar:
    st.markdown("### 🗓️ ปฏิทินข่าวแดงรายเดือน (Monthly Calendar Explorer)")
    st.caption("สามารถเลือกดูข่าวแดงย้อนหลังหรือล่วงหน้าของทั้งเดือนได้ พร้อมกรองตามสกุลเงิน")

    col_cal_m, col_cal_y, col_cal_curr = st.columns(3)
    now_dt = datetime.datetime.now()

    with col_cal_m:
        month_names = list(calendar.month_name)[1:]
        selected_month_idx = st.selectbox("เลือกเดือน (Month)", range(1, 13), index=now_dt.month - 1, format_func=lambda x: month_names[x - 1])
    with col_cal_y:
        selected_year = st.selectbox("เลือกปี (Year)", [now_dt.year - 1, now_dt.year, now_dt.year + 1], index=1)

    # ฟิลเตอร์ตามเดือนและปี
    matched_month_news = [
        n for n in red_news_this_week
        if n.date_local.month == selected_month_idx and n.date_local.year == selected_year
    ]

    st.markdown(f"#### 📅 สรุปรายการข่าวแดงในเดือน {month_names[selected_month_idx - 1]} {selected_year} (พบ {len(matched_month_news)} ข่าว)")

    if matched_month_news:
        cal_table = []
        cal_colors = []
        for n in matched_month_news:
            cal_table.append(
                {
                    "วันที่": n.date_local.strftime("%Y-%m-%d"),
                    "วัน": n.day_name_th,
                    "เวลา (เวลาไทย)": n.time_str,
                    "สกุลเงิน": n.country,
                    "ชื่อข่าว": n.title,
                    "Forecast": n.forecast or "-",
                    "Actual": format_actual_text(n),
                    "Previous": n.previous or "-",
                    "Impact": "🔴 High",
                }
            )
            cal_colors.append(actual_color_code(n))
        st.markdown(
            render_html_table(cal_table, cal_colors, "Actual"),
            unsafe_allow_html=True,
        )
    else:
        st.info(f"ไม่มีข้อมูลข่าวแดงในเดือน {month_names[selected_month_idx - 1]} {selected_year} ตามตัวกรองปัจจุบัน")

# ==========================================
# 8. Footer
# ==========================================
st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: #64748b; font-size: 0.85rem; padding: 10px 0;">
        Forex Trading Assistant & Alert System | ออกแบบตามสถาปัตยกรรม OOP & Clean Code | 
        เชื่อมต่อ Yahoo Finance, ForexFactory News และ LINE แจ้งเตือนอัตโนมัติ
    </div>
    """,
    unsafe_allow_html=True,
)
