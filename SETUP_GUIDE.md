# 📖 คู่มือฉบับสมบูรณ์: ระบบ Forex Trading Assistant & Alert System

คู่มือนี้จะอธิบาย **ทีละขั้นตอน** ว่า:
1. หน้า Dashboard ทำงานอย่างไร
2. บอทแจ้งเตือน LINE ทำงานอย่างไร
3. วิธีเชื่อมต่อ LINE (แบบง่าย และแบบแนะนำ)
4. วิธีตั้งค่า Secrets ใน **GitHub** และ **Streamlit Cloud**

---

## 📌 ส่วนที่ 1: ภาพรวมระบบ

ระบบมี **2 ส่วนหลัก** ที่ทำงานแยกกัน:

| ส่วน | ไฟล์ | หน้าที่ | ทำงานที่ไหน |
|------|------|--------|-------------|
| **Dashboard (Web UI)** | `dashboard.py` | แสดงกราฟ EMA สถานะเทรนด์ และตารางข่าวแดง | Streamlit Cloud (เปิดเมื่อมีคนเข้าชม) |
| **Bot (Background)** | `main.py` | ตรวจสัญญาณ EMA + ส่งข่าวเข้า LINE อัตโนมัติ | GitHub Actions (ทำงานตามตารางเวลา) |

```
                ┌─────────────────────────────┐
                │       LINE (สมาร์ทโฟน)       │
                └──────────────▲──────────────┘
                               │ ส่งแจ้งเตือน
        ┌──────────────────────┴───────────────────────┐
        │              GitHub Actions (ฟรี)             │
        │  • EMA Cross Check ทุก 5 นาที                  │
        │  • Weekly News Alert ทุกวันจันทร์ 06:30 น.      │
        │  • Keep Alive ทุกวันที่ 1 ของเดือน             │
        └──────────────┬──────────────────────┬─────────┘
                       │                      │
              Yahoo Finance            ForexFactory
              (ราคา/EMA)               (ข่าวแดง)
```

---

## 📌 ส่วนที่ 2: หน้า Dashboard ทำงานอย่างไร (ทีละขั้นตอน)

### ขั้นตอนที่ 1 — โหลดค่าระบบ
ไฟล์ `streamlit_app.py` (จุดเริ่มต้น) ทำ `from dashboard import *` แล้ว `dashboard.py` จะ:
- ตั้งค่า theme Dark (CSS แบบ Glassmorphism)
- สร้าง Service ทั้ง 4 ตัวแบบ **Cache** (สร้างครั้งเดียว แชร์ทุกคนที่เปิด) ผ่าน `get_services()`:
  - `PriceService` → ดึงราคาจาก Yahoo Finance (yfinance)
  - `IndicatorService` → คำนวณ EMA 50 / 150 และจับสัญญาณตัดกัน (Cross)
  - `ForexFactoryNewsService` → ดึงตารางข่าวแดงจาก ForexFactory
  - `NotificationService` → ส่งข้อความเข้า LINE

### ขั้นตอนที่ 2 — Sidebar (ตั้งค่าด้านซ้าย)
ผู้ใช้เลือก:
- **Symbol** เช่น XAUUSDm, EURUSD, GBPUSD, BTCUSD
- **Timeframe** เช่น M5, M15, H1, H4, D1
- (ค่า default อ่านจาก Streamlit Secrets ก่อน ถ้าไม่มีใช้ค่า Default)

### ขั้นตอนที่ 3 — ส่วนวิเคราะห์ EMA (Section 1)
1. ดึงข้อมูลราคาย้อนหลัง 300 แท่งเทียนจาก Yahoo Finance
2. คำนวณ EMA 50 (เส้นเร็ว) และ EMA 150 (เส้นช้า)
3. แสดงผล 4 ส่วน:
   - **Trend Banner** → เขียว = Bullish, แดง = Bearish, เทา = Neutral
   - **Gauge** (Plotly) → แสดงระยะห่างระหว่าง EMA ทั้ง 2
   - **Candlestick Chart** → กราฟราคา Interactive พร้อมเส้น EMA
   - สรุปสถานะว่าเกิด Golden Cross / Death Cross หรือยัง

### ขั้นตอนที่ 4 — ตารางข่าวแดง ForexFactory (Section 2)
1. ระบบ scrape จากหน้า `https://www.forexfactory.com/calendar` (แคช 5 นาที)
2. กรองเฉพาะข่าว **High Impact (สีแดง)** และกรองสกุลเงิน (ค่า default = USD)
3. แสดง 3 แท็บ:
   - **สรุปรายสัปดาห์** → ตารางข่าวแดงทั้งสัปดาห์ พร้อมตัวเลขจริงสีเขียว/แดง
   - **ดูแยกตามวัน** → เลือกวัน ดูรายละเอียดข่าวรายวัน + นับถอยหลังก่อนข่าวออก
   - **ปฏิทินรายเดือน** → เลือกเดือน/ปี ดูข่าวย้อนหลังหรือล่วงหน้า
4. **สีตัวเลขจริง (Actual)** ตามกฎ ForexFactory:
   - 🟢 เขียว (`▲`) = ตัวเลขจริงดีกว่าคาดการณ์
   - 🔴 แดง (`▼`) = ตัวเลขจริงแย่กว่าคาดการณ์
   - ไม่มีสี = เท่ากับคาด หรือยังไม่ออก ("รอดูผล")

### ขั้นตอนที่ 5 — ปุ่มส่ง LINE จากหน้าเว็บ
ใน Dashboard มีปุ่มให้กด:
- **ทดสอบส่ง LINE** → เรียก `send_test_message()`
- **ส่งข่าวแดงตอนนี้** → เรียก `broadcast_weekly_news_alert()`

---

## 📌 ส่วนที่ 3: บอทแจ้งเตือน LINE ทำงานอย่างไร

ไฟล์ `main.py` กำหนดตารางงานไว้ใน `scheduler_service.py` (`AlertScheduler`):

| งาน | เวลา | เกิดอะไรขึ้น |
|-----|------|-------------|
| ตรวจ EMA Cross | ทุก `POLL_INTERVAL_SECONDS` (30 วินาที) | ดึงราคา → คำนวณ EMA → ถ้าเกิด **Golden Cross / Death Cross ใหม่** → ส่ง LINE ทันที |
| สรุปข่าวแดงประจำสัปดาห์ | ทุกวันจันทร์ `WEEKLY_ALERT_TIME` (06:30 น.) | ดึงข่าวแดงทั้งสัปดาห์ → รวบรวมข้อความ → ส่งไลน์ 1 ครั้ง |
| (GitHub) Keep Alive | วันที่ 1 ของเดือน | สร้าง commit อัตโนมัติให้ repo ไม่เฉื่อย → cron ไม่ถูกปิด |

**ระบบป้องกันแจ้งเตือนซ้ำ**: จดจำแท่งเทียนล่าสุดที่ส่งสัญญาณไปแล้ว (`_last_alerted_candle_time`) ส่งแจ้งเตือนแค่ครั้งเดียวต่อแท่งเทียนนั้น

**การส่ง LINE** (`services/notifier.py`): พยายามส่ง 2 ช่องทาง เรียงลำดับ:
1. **LINE Messaging API** (Push) → ใช้ `LINE_CHANNEL_ACCESS_TOKEN` + `LINE_USER_ID`
2. **LINE Notify** → ใช้ `LINE_NOTIFY_TOKEN` (1-Token) ถ้ามี
> ส่งผ่านช่องทางใดสำเร็จก็ถือว่าสำเร็จ

---

## 📌 ส่วนที่ 4: วิธีเชื่อมต่อ LINE (เลือก 1 วิธีก็พอ)

### วิธี A — LINE Notify (ง่ายที่สุด เหมาะเริ่มต้น) ✅ แนะนำสำหรับมือใหม่

1. เปิดเว็บ https://notify-bot.line.me แล้ว **Login** ด้วยบัญชี LINE
2. กดเมนูบนขวา → **My page**
3. กดปุ่ม **Generate token**
4. เลือก **"1-on-1 chat with LINE Notify"** (ส่งมาหาตัวเอง)
5. ตั้งชื่อ Token (เช่น `forex-alert`) แล้วกด **Generate**
6. **คัดลอก Token** นั้นไปเก็บไว้**ทันที** (โชว์ครั้งเดียว!)

### วิธี B — LINE Messaging API (แนะนำ: ไม่หมดอายุ ใช้บริหารจัดการได้)

1. เปิด https://developers.line.biz → **Log in ด้วยบัญชี LINE**
2. กด **บริษัท/Provider** → กดปุ่ม `Create` เลือก **Messaging API**
3. กรอกชื่อ Provider และ Channel (เช่น `Forex Alert`) แล้วสร้าง
4. ไปที่แท็บ **Messaging API**:
   - **Channel Access Token** → กดปุ่ม **Issue** ในหัวข้อ *Channel access token (long-lived)* → **คัดลอก token** ไว้
5. **หาค่า User ID** ของตัวเอง:
   - เพิ่มบอทเป็นเพื่อนในแอป LINE (สแกน QR จากหน้า LINE Developers)
   - ในแอป LINE เปิดแชทกับบอท → แตะชื่อบอทบนสุด → เลื่อนล่างสุดจะเจอปุ่ม **"คัดลอก User ID"**
6. เก็บ 2 ค่า: `LINE_CHANNEL_ACCESS_TOKEN` และ `LINE_USER_ID`

### ทดสอบก่อนใช้งาน
ที่เครื่องท้องถิ่น (ในโฟลเดอร์โปรเจกต์) รัน:
```bash
py main.py --test-line
```
ถ้ามีข้อความ "Test Alert" เข้า LINE = เชื่อมต่อสำเร็จ 🎉

---

## 📌 ส่วนที่ 5: วิธีตั้งค่า Secrets (ค่าลับ) ทั้ง 3 ที่

> หลักการ: **ค่า token ต้องไม่ถูกเซฟลงในโค้ด** — เซฟในไฟล์แยก ที่ระบบ 3 จุดนี้

### 5.1 ตำแหน่งที่ 1 — ไฟล์ `.env` (เครื่องคอมของคุณ สำหรับทดสอบท้องถิ่น)

คัดลอก `.env.example` → เปลี่ยนชื่อเป็น `.env` แล้วใส่ค่าจริง:

```env
# สัญลักษณ์และ Timeframe
SYMBOL=XAUUSDm
TIMEFRAME=M5

# ค่า EMA
EMA_FAST=50
EMA_SLOW=150

# LINE (ใส่ตามวิธีที่เลือกในส่วนที่ 4)
LINE_CHANNEL_ACCESS_TOKEN=xxxxxxxxxxx
LINE_USER_ID=xxxxxxxxxxxxxxxxxxx
LINE_NOTIFY_TOKEN=xxxxxxxxxxx

# ข่าว ForexFactory
TIMEZONE=Asia/Bangkok
WEEKLY_ALERT_DAY=monday
WEEKLY_ALERT_TIME=06:30
POLL_INTERVAL_SECONDS=30
```

⚠️ อย่าลืม: `.env` อยู่ใน `.gitignore` แล้ว (ไม่ถูก push ขึ้น GitHub)

### 5.2 ตำแหน่งที่ 2 — Streamlit Cloud (สำหรับหน้า Dashboard)

ขั้นตอน:
1. เข้า https://share.streamlit.io → เปิดแอปของคุณ
2. กด **Manage app** (มุมขวาล่าง)
3. เลือกแท็บ **Secrets** หรือกด **⋮ → Settings → Secrets**
4. วางโค้ดในกล่อง (เก็บเป็นฟอร์แมต **TOML**):
   ```toml
   SYMBOL = "XAUUSDm"
   TIMEFRAME = "M5"
   EMA_FAST = "50"
   EMA_SLOW = "150"
   LINE_CHANNEL_ACCESS_TOKEN = "ใส่-token-จริง"
   LINE_USER_ID = "ใส่-user-id-จริง"
   LINE_NOTIFY_TOKEN = "ใส่-token-จริง-หรือ-ลบบรรทัดนี้"
   TIMEZONE = "Asia/Bangkok"
   POLL_INTERVAL_SECONDS = "60"
   ```
6. กด **Save** → แอปจะ **Rerun อัตโนมัติ** พร้อมโหลดค่าใหม่

> ระบบอ่านค่าจาก Streamlit Secrets ก่อนเสมอ (`_get_secret` ใน `config.py`) ถ้าไม่มีค่อยไปอ่าน `.env`

### 5.3 ตำแหน่งที่ 3 — GitHub Secrets (สำหรับบอทอัตโนมัติใน GitHub Actions)

ขั้นตอน:
1. เปิด GitHub repo ของคุณ (เช่น `JACKTheRicher1997/forex-trading-assistant`)
2. ไปที่ **Settings → Secrets and variables → Actions**
3. กดปุ่มสีเขียว **New repository secret** แล้วเพิ่มทีละตัว:
   - ชื่อ: `LINE_CHANNEL_ACCESS_TOKEN` → ค่า: ใส่ token จริง
   - ชื่อ: `LINE_USER_ID` → ค่า: ใส่ user id จริง
   - (ถ้าใช้ LINE Notify) ชื่อ: `LINE_NOTIFY_TOKEN` → ค่า: ใส่ token จริง
4. กด **Add secret** ทุกครั้งที่เพิ่ม
5. ตรวจสอบว่าในรายการมีครบทั้ง 2-3 ตัวแบบนี้:

   ```
   LINE_CHANNEL_ACCESS_TOKEN     (updated วันที่ที่ตั้ง)
   LINE_USER_ID                  (updated วันที่ที่ตั้ง)
   LINE_NOTIFY_TOKEN             (updated วันที่ที่ตั้ง)
   ```

### 🔑 ตารางค่า Environment Variables ทั้งหมด

| ตัวแปร | ความหมาย | ค่าเริ่มต้น | ต้องตั้งใน |
|--------|----------|------------|-----------|
| `SYMBOL` | คู่สกุลเงินที่ตรวจ | `XAUUSDm` | .env / Streamlit / GitHub |
| `TIMEFRAME` | กรอบเวลา (M5, H1...) | `M5` | .env / Streamlit / GitHub |
| `EMA_FAST` | เส้น EMA เร็ว | `50` | .env / Streamlit |
| `EMA_SLOW` | เส้น EMA ช้า | `150` | .env / Streamlit |
| `LINE_CHANNEL_ACCESS_TOKEN` | Token Messaging API | ว่าง | .env / Streamlit / GitHub |
| `LINE_USER_ID` | ID ส่วนตัวของคุณ | ว่าง | .env / Streamlit / GitHub |
| `LINE_NOTIFY_TOKEN` | Token LINE Notify | ว่าง | .env / Streamlit / GitHub |
| `TIMEZONE` | เวลาไทย | `Asia/Bangkok` | .env / Streamlit |
| `WEEKLY_ALERT_DAY` | วันส่งข่าวสรุป | `monday` | .env |
| `WEEKLY_ALERT_TIME` | เวลาส่งข่าวสรุป (24 ชม.) | `06:30` | .env |
| `WEEKLY_ALERT_CURRENCIES` | สกุลเงินข่าวใน LINE (`ALL` = ทุกสกุล) | `USD` | .env / GitHub |
| `POLL_INTERVAL_SECONDS` | ความถี่ตรวจ EMA | `30` | .env |

---

## 📌 ส่วนที่ 6: GitHub Actions ที่ติดตั้งไว้ (3 ไฟล์)

ไฟล์อยู่ในโฟลเดอร์ `.github/workflows/`:

| Workflow | ตารางเวลา | สั่งการจริง |
|----------|-----------|------------|
| `ema-cross-check.yml` | ทุก 5 นาที (`*/5 * * * *`) | `python main.py --check-ema-now` |
| `weekly-news-alert.yml` | วันจันทร์ 06:30 ไทย (อาทิตย์ 23:30 UTC) | `python main.py --send-news-now` |
| `keep-alive.yml` | วันที่ 1 ของเดือน | สร้าง commit รักษา repo ให้ active |

> **หมายเหตุ**: GitHub จำกัด cron ต่ำสุด **ทุก 5 นาที** (จึงไม่ใช่ 30 วินาทีเหมือนเครื่องของตัวเอง) แต่ bbot ตรวจ EMA จะส่งแจ้งเตือนแค่ครั้งเดียวต่อแท่งเทียน M5 จึงไม่มีการส่งซ้ำ

### วิธีทดสอบ workflow ด้วยมือ
1. ไปที่ repo → **Actions** tab
2. เลือก workflow ทางซ้าย (เช่น "Weekly News Alert (LINE)")
3. กดปุ่ม **Run workflow** → เลือก branch `main` → กด **Run workflow**
4. เห็น status สีเขียว ✓ = สำเร็จ ข้อความควรเข้าสู่ LINE ภายใน ~1 นาที

---

## 📌 ส่วนที่ 7: การแก้ปัญหาเบื้องต้น (FAQ)

**Q: กดส่ง LINE แล้วไม่มีข้อความเข้า**
- ตรวจว่า secrets ครบหรือยัง (ดูส่วนที่ 5.2 / 5.3)
- รัน `py main.py --test-line` ที่เครื่องให้เห็น error ตรง ๆ
- LINE Notify: ตรวจว่า token อยู่ใน "1-on-1 chat" หรือไม่

**Q: Dashboard ไม่โชว์ตัวเลขจริงข่าว (ขึ้น "รอดูผล")**
- ข่าวนั้นยังไม่ออก หรือ ForexFactory โดน block → ระบบจะใช้ JSON Feed fallback (ไม่มีค่า Actual)
- ตรวจใน Manage app → logs ดูข้อความ `dึงข่าวจาก...สำเร็จ` หรือ `fallback`

**Q: GitHub Actions ขึ้น "no workflow runs yet"**
- ปกติเลย — หมายถึงยังไม่ถึงรอบตามตาราง ไปกด **Run workflow** ด้วยมือเพื่อทดสอบ หรือรอจังหวะเวลาที่กำหนด

**Q: อยากให้ตรวจ EMA ถี่กว่านี้ได้ไหม**
- GitHub Actions cron ต่ำสุด 5 นาที แต่ถ้าต้องการ 30 วินาทีจริง ๆ ต้องใช้เครื่องจริง 24/7 เช่น **Oracle Cloud Free VM** (ดูเพิ่มในบันทึกแชท)

**Q: ราคากับโบรกเกอร์ไม่ตรงกัน?**
- ราคามาจาก Yahoo Finance ซึ่งเป็นแหล่งข้อมูลอื่นของโบรกเกอร์ และมี delay เล็กน้อย (ไม่ใช่ tick เรียลไทม์) — ใช้เป็นแนวโน้มประกอบได้

---

🔗 **ภาพรวมสถาปัตยกรรม**: ระบบแยก Dashboard (แสดงผล) และ Bot (แจ้งเตือน) ออกจากกันชัดเจน แต่ใช้ **ค่า Config ชุดเดียวกัน** ผ่าน `config.py` → ตั้งค่าแค่ครั้งเดียวใช้ได้ทั้ง 2 ส่วนครับ