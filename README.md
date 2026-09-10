# ⚡ Forex Trading Assistant & Alert System (ระบบผู้ช่วยเทรด Forex & แจ้งเตือนอัจฉริยะ)

ระบบผู้ช่วยเทรด Forex ครบวงจร พัฒนาด้วยภาษา **Python** ตามหลักการ **Object-Oriented Programming (OOP)** และ **Clean Architecture** พร้อมหน้าเว็บ Dashboard ธีม Dark Mode สวยงาม และระบบแจ้งเตือนเข้าสู่ LINE อัตโนมัติ

> 📖 **ต้องการคู่มือละเอียดทีละขั้นตอน?** เปิดได้ที่ [`SETUP_GUIDE.md`](SETUP_GUIDE.md) — อธิบายการทำงานของ Dashboard, บอท LINE, และวิธีตั้งค่า Secrets ทั้งใน GitHub และ Streamlit

---

## 🌟 จุดเด่นและฟังก์ชันการทำงานหลัก

### 1. สถาปัตยกรรมระบบ (OOP & Architecture)
- **Modular & Separation of Concerns**: แยกคลาสความรับผิดชอบอย่างชัดเจน (`PriceService`, `IndicatorService`, `ForexFactoryNewsService`, `NotificationService`, `AlertScheduler`, `TradingAssistant`)
- **Centralized Configuration**: โหลดค่า Configuration และ Secrets ผ่าน `config.py` จากไฟล์ `.env` อย่างปลอดภัย
- **Logging System**: บันทึกการทำงานทั้งบน Console และไฟล์ `bot.log` ด้วย `RotatingFileHandler` เพื่อความทนทานและตรวจสอบย้อนหลังได้ง่าย

### 2. ระบบรวบรวมข่าวแดงจาก ForexFactory (High-Impact News)
- ดึงข้อมูลปฏิทินเศรษฐกิจจาก ForexFactory API แบบเรียลไทม์
- **กรองเฉพาะข่าวสีแดง (High-Impact)** ที่ส่งผลกระทบต่อตลาดรุนแรง
- **เงื่อนไขการส่งแจ้งเตือน LINE**: ส่งสรุปภาพรวมข่าว **สัปดาห์ละ 1 ครั้ง ในทุกๆ เช้าวันจันทร์** (ก่อนตลาดเปิด)
- รายละเอียดในข้อความประกอบด้วย:
  * จำนวนข่าวสีแดงทั้งหมดในสัปดาห์นั้น
  * ข่าวแดงในแต่ละวัน (ชื่อข่าว, สกุลเงิน, เวลาที่ข่าวออกเป็นเวลาไทย)
  * **หากวันไหนไม่มีข่าวแดง**: ระบุข้อความอย่างชัดเจนว่า `"🟢 วันนี้ไม่มีข่าวสีแดง สามารถเทรดได้ตลอดวัน"`

### 3. ดึงราคาจาก Yahoo Finance (Free Cloud API) & ตรวจจับ EMA Cross
- ดึงข้อมูลราคาผ่าน **Yahoo Finance (yfinance)** แทน MetaTrader 5 ทำให้ใช้งานบน **Streamlit Community Cloud ได้ฟรี**
- รองรับสัญลักษณ์หลายชนิด: XAUUSD (Gold), EURUSD, GBPUSD, USDJPY, BTCUSD ฯลฯ
- คำนวณ **EMA 50** (Fast) และ **EMA 150** (Slow) บน Timeframe ที่กำหนด (M5, M15, H1, H4, D1)
- **Live Signal Alert แจ้งเตือนเข้า LINE ทันทีเมื่อเกิดการตัดกัน**:
  * **EMA 50 ตัดขึ้นเหนือ EMA 150** -> ส่งแจ้งเตือนระบุว่าเป็น **"🚀 Uptrend / เทรนขาขึ้น"**
  * **EMA 50 ตัดลงใต้ EMA 150** -> ส่งแจ้งเตือนระบุว่าเป็น **"🔻 Downtrend / เทรนขาลง"**
- **Deduplication System**: มีระบบป้องกันการแจ้งเตือนซ้ำ โดยจะส่งเพียงครั้งเดียวต่อแท่งเทียนนั้นๆ

> **หมายเหตุ**: ราคาที่ดึงจาก Yahoo Finance อาจไม่ตรงกับราคาจากโบรกเกอร์ (เช่น Exness) 100% เนื่องจากแหล่งข้อมูลต่างกัน และข้อมูลมี delay เล็กน้อย (ไม่ใช่ tick เรียลไทม์)

### 4. หน้าเว็บ Dashboard (Streamlit & Plotly)
- ดีไซน์สวยงามระดับ **Dark Mode Luxury Glassmorphism** ทันสมัย อ่านง่าย และรองรับการแสดงผลบนมือถือ (**Responsive**)
- **Indicator & Trend Status**:
  * แบนเนอร์เน้นสีเขียวสดใส **`CURRENT TREND: BULLISH`** หรือสีแดง **`CURRENT TREND: BEARISH`**
  * เกจวัด (Plotly Gauge) แสดงระยะห่างของเส้น EMA และโมเมนตัมของตลาด
  * กราฟ Candlestick แบบ Interactive ซูม/เลื่อนดูจุดตัดของ EMA 50 และ EMA 150 ได้ละเอียด
- **ForexFactory News Section**:
  * **Weekly Summary**: ตารางสรุปภาพรวมข่าวแดงทั้งหมดของสัปดาห์
  * **Day Selector**: เลือกคลิกดูข่าวแดงรายวัน พร้อมแบนเนอร์แสดงวันที่ไม่มีข่าวแดง
  * **Monthly Calendar View**: ปฏิทินเลือกดูข่าวแดงย้อนหลังหรือล่วงหน้าของทั้งเดือน พร้อมระบบกรองสกุลเงิน (USD, EUR, GBP, JPY ฯลฯ)
- ปุ่มสั่งงานด่วน: กดทดสอบส่ง LINE หรือกดส่งสรุปข่าวแดงเข้า LINE ได้ทันทีผ่านหน้าเว็บ

---

## 📁 โครงสร้างโปรเจกต์ (Project Structure)

```text
d:/BotAlert/
├── .env                      # เก็บ Credentials (LINE Tokens, Settings)
├── requirements.txt          # รายการ Library สำหรับติดตั้ง
├── config.py                 # จัดการ Config จาก .env (AppConfig, SymbolConfig, LineConfig)
├── logger.py                 # ระบบ Logging (AppLogger, RotatingFileHandler)
├── main.py                   # ตัวควบคุมหลัก (Core TradingAssistant Orchestrator)
├── dashboard.py              # หน้าเว็บ Streamlit Dashboard Dark Mode
├── services/                 # Business Logic แยกตามความรับผิดชอบ
│   ├── __init__.py
│   ├── price_service.py      # PriceService: ดึงราคาจาก Yahoo Finance (yfinance)
│   ├── indicator_service.py  # IndicatorService: คำนวณ EMA 50/150, ตรวจจับ Cross, ป้องกันแจ้งเตือนซ้ำ
│   ├── news_service.py       # ForexFactoryNewsService: ดึงข่าวแดง, จัดกลุ่มรายวัน, ฟอร์แมตข้อความสรุป
│   ├── notifier.py           # NotificationService: ส่งเข้า LINE (รองรับทั้ง Messaging API & Notify)
│   └── scheduler_service.py  # AlertScheduler: ควบคุมเวลาส่งข่าววันจันทร์ และรอบตรวจ EMA
└── bot.log                   # ไฟล์บันทึกประวัติการทำงาน (สร้างขึ้นอัตโนมัติ)
```

---

## 🛠️ วิธีการติดตั้งและเตรียมความพร้อม (Installation & Setup)

### ขั้นตอนที่ 1: ติดตั้ง Libraries ที่จำเป็น
เปิด PowerShell หรือ Command Prompt ในโฟลเดอร์โปรเจกต์ แล้วรันคำสั่ง:

```bash
py -m pip install -r requirements.txt
```

*(หรือ `pip install -r requirements.txt`)*

### ขั้นตอนที่ 2: ตั้งค่าไฟล์ `.env`
เปิดไฟล์ `.env` แล้วตรวจสอบการตั้งค่าดังนี้:

```env
# สัญลักษณ์และ Timeframe เริ่มต้น
# รองรับ: XAUUSDm (ทอง), EURUSD, GBPUSD, USDJPY, BTCUSD ฯลฯ
SYMBOL=XAUUSDm
TIMEFRAME=M5

# ค่าความยาวเส้น EMA
EMA_FAST=50
EMA_SLOW=150

# การตั้งค่าแจ้งเตือน LINE
# รองรับทั้ง LINE Messaging API (แนะนำ) และ LINE Notify
LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token
LINE_USER_ID=your_user_id
LINE_NOTIFY_TOKEN=your_line_notify_token_if_any

# การตั้งค่าสรุปข่าว ForexFactory
TIMEZONE=Asia/Bangkok
WEEKLY_ALERT_DAY=monday
WEEKLY_ALERT_TIME=06:30
POLL_INTERVAL_SECONDS=30
```

---

## 🚀 วิธีการเปิดใช้งานระบบ (How to Run)

### 1. รันระบบผู้ช่วยเทรดในโหมด Background Bot (Main Bot)
คำสั่งนี้จะรันระบบตรวจจับ Live EMA Cross ตลอดเวลา และตั้งเวลาส่งสรุปข่าวแดงทุกเช้าวันจันทร์อัตโนมัติ:

```bash
py main.py
```

### 2. รันหน้าเว็บ Dashboard สวยงาม (Web UI)
เปิดหน้าเว็บแดชบอร์ด Dark Mode ดูสถานะ EMA, เกจวัด, กราฟราคา และปฏิทินข่าวแดง:

```bash
py -m streamlit run dashboard.py
```
*ระบบจะเปิดเบราว์เซอร์ให้อัตโนมัติที่ `http://localhost:8501`*

---

## 🧪 คำสั่งทดสอบฟังก์ชันเฉพาะจุด (Testing & Diagnostics)

สามารถทดสอบการทำงานของแต่ละระบบได้ทันทีโดยไม่ต้องรอรอบเวลา:

- **ทดสอบส่งข้อความเข้า LINE ทันที:**
  ```bash
  py main.py --test-line
  ```

- **ทดสอบดึงข่าวและส่งสรุปข่าวแดงสัปดาห์นี้เข้า LINE ทันที:**
  ```bash
  py main.py --send-news-now
  ```

- **ทดสอบตรวจค่าราคาและ EMA 50 / 150 จาก Yahoo Finance ทันที:**
  ```bash
  py main.py --check-ema-now
  ```
