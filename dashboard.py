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
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import config
from logger import get_logger
from services.price_service import PriceService
from services.indicator_service import IndicatorService, TrendState, CrossSignal
from services.news_service import ForexFactoryNewsService, ForexNewsItem
from services.notifier import NotificationService

logger = get_logger("Dashboard")

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
    price_srv = PriceService()
    ind_srv = IndicatorService()
    news_srv = ForexFactoryNewsService()
    notif_srv = NotificationService()
    return price_srv, ind_srv, news_srv, notif_srv


price_service, indicator_service, news_service, notification_service = get_services()


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


def style_actual_column(df, colors, col_name):
    """
    ใช้ pandas Styler เพื่อระบายสีข้อความของคอลัมน์ Actual
    - สีเขียว (#00aa00) = ตัวเลขจริงดีกว่าคาดการณ์
    - สีแดง (#cc0000) = ตัวเลขจริงแย่กว่าคาดการณ์
    :param df: DataFrame ที่มีคอลัมน์ col_name
    :param colors: list สีตามแถว (เรียงเดียวกับ df)
    :param col_name: ชื่อคอลัมน์ Actual
    """
    def _style_row(row):
        styles = [""] * len(row)
        idx = int(row.name)
        if 0 <= idx < len(colors) and colors[idx]:
            col_pos = list(row.index).index(col_name)
            styles[col_pos] = f"color: {colors[idx]}; font-weight: 700;"
        return styles

    return df.style.apply(_style_row, axis=1)

# ==========================================
# 3. Sidebar Controls & System Status
# ==========================================
with st.sidebar:
    st.markdown("## ⚡ Forex Trading Assistant")
    st.caption("ระบบวิเคราะห์ EMA Cross & แจ้งเตือนข่าวแดง ForexFactory")
    st.markdown("---")

    # ดึงค่าเริ่มต้นคู่เงิน ไทม์เฟรม และ EMA จาก Streamlit Secrets
    default_symbol = st.secrets.get("SYMBOL", "XAUUSDm")
    default_tf = st.secrets.get("TIMEFRAME", "M5")
    default_ema_fast = int(st.secrets.get("EMA_FAST", 50))
    default_ema_slow = int(st.secrets.get("EMA_SLOW", 150))

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
    try:
        channel_access_token = st.secrets["LINE_CHANNEL_ACCESS_TOKEN"]
        user_id = st.secrets["LINE_USER_ID"]
        has_token = bool(channel_access_token and user_id)
    except Exception:
        has_token = False
        channel_access_token = None
        user_id = None

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
    auto_refresh = st.checkbox("🔄 รีเฟรชหน้าจออัตโนมัติ (ทุก 30 วินาที)", value=False)
    if auto_refresh:
        # Streamlit rerun ทุก 30 วินาที
        st.info("โหมด Auto-refresh เปิดใช้งาน")
        st.markdown(
            """
            <meta http-equiv="refresh" content="30">
            """,
            unsafe_allow_html=True,
        )

# ==========================================
# 4. Main Header & Top Status
# ==========================================
st.markdown("# 🚀 Forex Trading Assistant & Live Alert System")
st.caption(f"เวลาปัจจุบัน (Local): {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | สกุลเงินหลัก: {selected_symbol}")

# ดึงข้อมูลราคาจาก Yahoo Finance
with st.spinner("กำลังดึงข้อมูลแท่งเทียนและคำนวณอินดิเคเตอร์..."):
    df_rates = price_service.get_rates(symbol=selected_symbol, timeframe_str=selected_tf, count=250)

signal_result = None
if df_rates is not None and len(df_rates) > 0:
    signal_result = indicator_service.analyze(df_rates, symbol=selected_symbol, timeframe=selected_tf)

# ==========================================
# 5. Section 1: สถานะอินดิเคเตอร์ & เกจวัด EMA
# ==========================================
st.markdown("## 📊 1. สถานะอินดิเคเตอร์ & การตัดกันของ EMA (EMA Cross)")

col_status, col_gauge = st.columns([1.2, 1.0])

with col_status:
    if signal_result:
        # แสดง Banner สถานะใหญ่สะดุดตาตามข้อกำหนด
        if signal_result.is_bullish:
            st.markdown(
                """
                <div class="trend-bullish">
                    <h2 style="color: #10b981; margin:0; font-size: 1.8rem;">🟢 CURRENT TREND: BULLISH</h2>
                    <p style="margin: 5px 0 0 0; color: #a7f3d0; font-size: 1.1rem; font-weight: 500;">
                        EMA 50 อยู่เหนือ EMA 150 (โมเมนตัมขาขึ้น)
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif signal_result.is_bearish:
            st.markdown(
                """
                <div class="trend-bearish">
                    <h2 style="color: #ef4444; margin:0; font-size: 1.8rem;">🔴 CURRENT TREND: BEARISH</h2>
                    <p style="margin: 5px 0 0 0; color: #fecaca; font-size: 1.1rem; font-weight: 500;">
                        EMA 50 อยู่ใต้ EMA 150 (โมเมนตัมขาลง)
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div class="trend-neutral">
                    <h2 style="color: #94a3b8; margin:0; font-size: 1.8rem;">⚪ CURRENT TREND: NEUTRAL</h2>
                    <p style="margin: 5px 0 0 0;">เส้น EMA กำลังเกาะกลุ่มกัน</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

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
            if signal_result.cross_signal == CrossSignal.CROSS_UP:
                cross_text = "🚀 ตัดขึ้น (Uptrend)"
            elif signal_result.cross_signal == CrossSignal.CROSS_DOWN:
                cross_text = "🔻 ตัดลง (Downtrend)"
            st.metric(
                label="สัญญาณล่าสุด (Cross)",
                value=cross_text,
            )

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### 🧭 สรุปเทรน Multi-Timeframe (MTF)")
        mtf_tfs = ["M5", "M15", "H1", "H4", "D1"]
        mtf_cols = st.columns(len(mtf_tfs))
        
        for idx, tf in enumerate(mtf_tfs):
            tf_df = price_service.get_rates(symbol=selected_symbol, timeframe_str=tf, count=160)
            tf_trend = "NEUTRAL"
            tf_color = "#94a3b8"
            
            if tf_df is not None and len(tf_df) > 0:
                tf_res = indicator_service.analyze(tf_df, symbol=selected_symbol, timeframe=tf)
                if tf_res:
                    if tf_res.is_bullish:
                        tf_trend = "BULLISH 🟢"
                        tf_color = "#10b981"
                    elif tf_res.is_bearish:
                        tf_trend = "BEARISH 🔴"
                        tf_color = "#ef4444"
            
            with mtf_cols[idx]:
                st.markdown(
                    f"""
                    <div style="text-align: center; background: rgba(30, 41, 59, 0.5); padding: 8px; border-radius: 6px; border-bottom: 2px solid {tf_color};">
                        <div style="font-size: 0.95rem; font-weight: bold; color: #f8fafc;">{tf}</div>
                        <div style="font-size: 0.75rem; color: {tf_color}; font-weight: 600; margin-top: 2px;">{tf_trend}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
    else:
        st.warning(
            "⚠️ ไม่สามารถดึงข้อมูลราคาได้ในขณะนี้ กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ตหรือลองใหม่ภายหลัง"
        )

with col_gauge:
    # เกจวัดสวยๆ ด้วย Plotly Gauge Indicator
    if signal_result:
        spread_ema = signal_result.ema_fast - signal_result.ema_slow
        max_range = max(abs(spread_ema) * 2, 10.0)

        gauge_color = "#10b981" if signal_result.is_bullish else "#ef4444"
        fig_gauge = go.Figure(
            go.Indicator(
                mode="gauge+number+delta",
                value=spread_ema,
                domain={"x": [0, 1], "y": [0, 1]},
                title={"text": "EMA Distance (EMA50 - EMA150)", "font": {"size": 16, "color": "#cbd5e1"}},
                delta={"reference": 0, "increasing": {"color": "#10b981"}, "decreasing": {"color": "#ef4444"}},
                gauge={
                    "axis": {"range": [-max_range, max_range], "tickcolor": "#64748b"},
                    "bar": {"color": gauge_color},
                    "bgcolor": "rgba(15, 23, 42, 0.6)",
                    "borderwidth": 1,
                    "bordercolor": "#334155",
                    "steps": [
                        {"range": [-max_range, 0], "color": "rgba(239, 68, 68, 0.15)"},
                        {"range": [0, max_range], "color": "rgba(16, 185, 129, 0.15)"},
                    ],
                    "threshold": {
                        "line": {"color": "#f59e0b", "width": 3},
                        "thickness": 0.75,
                        "value": 0,
                    },
                },
            )
        )
        fig_gauge.update_layout(
            height=240,
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor="rgba(0,0,0,0)",
            font={"color": "#e2e8f0"},
        )
        st.plotly_chart(fig_gauge, use_container_width=True)
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


# ==========================================
# 6. Interactive Candlestick + EMA Chart
# ==========================================
if df_rates is not None and len(df_rates) > 0:
    with st.expander("📈 ดูกราฟแท่งเทียน Candlestick พร้อมเส้น EMA 50 / 150 แบบละเอียด", expanded=True):
        df_plot = indicator_service.calculate_ema(df_rates).tail(120)

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

# ดึงข่าวสัปดาห์นี้
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
        df_weekly = pd.DataFrame(table_data)
        st.dataframe(
            style_actual_column(df_weekly, actual_colors, "ตัวเลขจริง (Actual)"),
            use_container_width=True,
            hide_index=True,
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
        st.dataframe(
            style_actual_column(pd.DataFrame(day_table), day_colors, "Actual"),
            use_container_width=True,
            hide_index=True,
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
        st.dataframe(
            style_actual_column(pd.DataFrame(cal_table), cal_colors, "Actual"),
            use_container_width=True,
            hide_index=True,
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
