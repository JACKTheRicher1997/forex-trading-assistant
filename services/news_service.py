"""
ForexFactory News Service Module
ดึงข้อมูลตารางข่าวเศรษฐกิจจาก ForexFactory กรองเฉพาะข่าวสีแดง (High-Impact)
และจัดรูปแบบข้อความแจ้งเตือนสรุปรายสัปดาห์

แหล่งข้อมูล:
1. หน้า Calendar ของเว็บ ForexFactory (https://www.forexfactory.com/calendar)
   - ให้ค่าที่แท้จริงครบ: Actual / Forecast / Previous
2. JSON Feed (https://nfs.faireconomy.media/ff_calendar_thisweek.json)
   - ใช้เป็น Fallback เมื่อ scrape เว็บไม่ได้ (feed นี้ไม่มีค่า Actual)
"""

import datetime
import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

try:
    import pytz
except ImportError:
    pytz = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from logger import get_logger
from config import config

logger = get_logger("NewsService")



@dataclass
class ForexNewsItem:
    """โครงสร้างข้อมูลข่าวเศรษฐกิจ ForexFactory"""
    title: str
    country: str  # สกุลเงิน เช่น USD, EUR, GBP
    date_utc: datetime.datetime
    date_local: datetime.datetime
    impact: str  # High, Medium, Low, Holiday
    forecast: str = ""
    previous: str = ""
    actual: str = ""  # ค่าที่ออกจริง (ถ้ามี)
    actual_color: str = ""  # สีของตัวเลขจริง: "better" (เขียว), "worse" (แดง), "" (ปกติ)

    @property
    def is_high_impact(self) -> bool:
        """ตรวจสอบว่าเป็นข่าวสีแดง (High Impact) หรือไม่"""
        return self.impact.lower() == "high"

    @property
    def is_actual_better(self) -> bool:
        """ตรวจสอบว่าตัวเลขจริงดีกว่าคาดการณ์ (สีเขียว) หรือไม่"""
        return self.actual_color == "better"

    @property
    def is_actual_worse(self) -> bool:
        """ตรวจสอบว่าตัวเลขจริงแย่กว่าคาดการณ์ (สีแดง) หรือไม่"""
        return self.actual_color == "worse"

    @property
    def time_str(self) -> str:
        """เวลาออกข่าวในเวลาท้องถิ่น (HH:MM น.)"""
        return self.date_local.strftime("%H:%M น.")

    @property
    def day_name_th(self) -> str:
        """ชื่อวันภาษาไทย"""
        thai_days = {
            0: "วันจันทร์",
            1: "วันอังคาร",
            2: "วันพุธ",
            3: "วันพฤหัสบดี",
            4: "วันศุกร์",
            5: "วันเสาร์",
            6: "วันอาทิตย์",
        }
        return thai_days.get(self.date_local.weekday(), "วันไม่ระบุ")


class ForexFactoryNewsService:
    """
    คลาสสำหรับดึงและประมวลผลข่าวเศรษฐกิจจาก ForexFactory
    ตามหลักการ Single Responsibility Principle (SRP)
    """

    # Endpoint ทางการของ Fair Economy / ForexFactory JSON feed
    THIS_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    NEXT_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

    # หน้า Calendar อย่างเป็นทางการของเว็บ ForexFactory (มีค่า Actual/Forecast/Previous จริง)
    CALENDAR_URL = "https://www.forexfactory.com/calendar"

    # แปลง CSS Class ของ Icon ระดับความสำคัญ (Impact) บนหน้าเว็บ
    _IMPACT_MAP = {
        "icon--ff-impact-red": "High",
        "icon--ff-impact-ora": "Medium",
        "icon--ff-impact-yel": "Low",
        "icon--ff-impact-gra": "Holiday",
    }

    # หน้า Calendar ของ ForexFactory จะเรนเดอร์เวลาเป็น Timezone ของผู้เข้าชม (ไม่ใช่ NY เสมอไป)
    # เช่น เปิดจากเครื่องในไทย -> เวลาจะเป็นเวลาไทย, เปิดจาก Server ฝั่ง US -> เวลา US
    # ดังนั้นต้องตรวจสอบ Timezone จริงจากหน้าเว็บก่อนเสมอ (ดู _detect_render_timezone)
    _BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(self, target_timezone: str = None):
        self.timezone_name = target_timezone or config.news.timezone
        self.tz = self._init_timezone(self.timezone_name)
        self._cached_news: List[ForexNewsItem] = []
        self._last_fetched: Optional[datetime.datetime] = None

    def _new_york_tz(self):
        """Timezone ของ ForexFactory Calendar (America/New_York)"""
        if ZoneInfo:
            try:
                return ZoneInfo("America/New_York")
            except Exception:
                pass
        if pytz:
            return pytz.timezone("America/New_York")
        return datetime.timezone(datetime.timedelta(hours=-4))

    def _detect_render_timezone(self, html: str):
        """
        ตรวจสอบ Timezone ที่ ForexFactory ใช้เรนเดอร์เวลาในหน้า Calendar
        (หน้าเว็บจะเรนเดอร์ตาม Timezone ของผู้เข้าชม เช่น Asia/Bangkok, America/New_York)
        - ตรวจจาก Google Analytics user_properties ก่อน: 'timezone': 'Asia/Bangkok'
        - ถ้าไม่เจอ ให้เช็คจากส่วนหัวตอนพิมพ์: "Calendar Time Zone: Asia/Bangkok (GMT +7)"
        - ถ้าเจอ timezone ที่ไม่รู้จัก ให้ Fallback เป็น New York ตามพฤติกรรมเดิม
        """
        name = None
        m = re.search(r"'timezone':\s*'([^']+)'", html)
        if not m:
            m = re.search(r"Calendar Time Zone:\s*([^<(]+?)\s*\(", html)
        if m:
            name = m.group(1).strip()
            tz = self._init_timezone(name)
            if tz is not None:
                logger.debug(f"ตรวจพบ Timezone ของหน้า Calendar: {name}")
                return tz
        logger.warning(f"ไม่พบ Timezone ของหน้า Calendar (ค้นหาได้: {name!r}) ใช้ New York เป็นค่าเริ่มต้น")
        return self._new_york_tz()

    def _init_timezone(self, tz_name: str):
        """กำหนด Timezone โดยรองรับ ZoneInfo, pytz หรือ Fallback เป็น GMT+7"""
        if ZoneInfo:
            try:
                return ZoneInfo(tz_name)
            except Exception:
                pass
        if pytz:
            try:
                return pytz.timezone(tz_name)
            except Exception:
                pass
        # Fallback เป็น GMT+7 (เวลาไทย)
        return datetime.timezone(datetime.timedelta(hours=7))

    def fetch_this_week_news(self, force_refresh: bool = False, only_high_impact: bool = True) -> List[ForexNewsItem]:
        """
        ดึงข้อมูลข่าวประจำสัปดาห์นี้จาก ForexFactory
        ลำดับข้อมูล: scrape หน้า Calendar ของเว็บก่อน (มีค่า Actual) -> ใช้ JSON Feed เป็น Fallback
        :param force_refresh: บังคับดึงข้อมูลใหม่โดยไม่ใช้แคช
        :param only_high_impact: กรองเอาเฉพาะข่าวสีแดง (High Impact) เท่านั้น
        :return: รายการ ForexNewsItem
        """
        now = datetime.datetime.now(self.tz)
        # ใช้แคชถ้าเพิ่งดึงไปไม่เกิน 5 นาที
        if not force_refresh and self._cached_news and self._last_fetched:
            if (now - self._last_fetched).total_seconds() < 300:
                logger.debug("ใช้ข้อมูลข่าวจากหน่วยความจำแคช")
                return [n for n in self._cached_news if not only_high_impact or n.is_high_impact]

        logger.info("กำลังดึงข้อมูลข่าวเศรษฐกิจสัปดาห์นี้จาก ForexFactory...")

        # 1) ลอง scrape หน้า Calendar ของเว็บก่อน เพราะมีค่า Actual/Forecast/Previous จริง
        html_items = self._scrape_html_items()
        if html_items:
            # ตรวจสอบและปรับเวลาข่าวที่ได้จาก HTML ให้ตรงกับเวลาจริง (ใช้ JSON Feed ที่ระบุ UTC Offset ชัดเจน)
            html_items = self._reconcile_html_times_with_json(html_items)
            self._cached_news = html_items
            self._last_fetched = now
            logger.info(f"ดึงข่าวจากหน้า Calendar ของเว็บ ForexFactory สำเร็จ: พบจำนวน {len(html_items)} รายการ")
        else:
            # 2) Fallback เป็น JSON Feed (feed นี้จะไม่มีค่า Actual)
            self._fetch_from_json_feed(now)

        if only_high_impact:
            filtered = [item for item in self._cached_news if item.is_high_impact]
            logger.info(f"กรองเฉพาะข่าวสีแดง (High-Impact): พบจำนวน {len(filtered)} รายการ")
            return filtered

        return self._cached_news

    def _fetch_from_json_feed(self, now: datetime.datetime) -> bool:
        """ดึงข้อมูลจาก JSON Feed ของ Fair Economy (ไม่มีค่า Actual ใช้เป็น Fallback)"""
        try:
            headers = {
                "User-Agent": self._BROWSER_HEADERS["User-Agent"],
                "Accept": "application/json",
            }
            response = requests.get(self.THIS_WEEK_URL, headers=headers, timeout=12)
            response.raise_for_status()
            data = response.json()

            parsed_items: List[ForexNewsItem] = []
            for item in data:
                # ตัวอย่าง date string: 2026-09-08T08:30:00-04:00 หรือ 2026-09-08T12:30:00Z
                date_str = item.get("date", "")
                dt_obj = self._parse_datetime(date_str)
                if not dt_obj:
                    continue

                # แปลงเวลาเป็น Local Timezone (เช่น Asia/Bangkok)
                local_dt = dt_obj.astimezone(self.tz)

                parsed_items.append(
                    ForexNewsItem(
                        title=item.get("title", "Unknown"),
                        country=item.get("country", ""),
                        date_utc=dt_obj,
                        date_local=local_dt,
                        impact=item.get("impact", "Low"),
                        forecast=item.get("forecast", ""),
                        previous=item.get("previous", ""),
                        actual=item.get("actual", ""),
                    )
                )

            if not parsed_items:
                logger.warning("JSON Feed กลับมารายการว่าง ไม่มีข้อมูล")
                return False

            self._cached_news = parsed_items
            self._last_fetched = now
            logger.info(f"ดึงข้อมูลข่าวจาก JSON Feed สำเร็จ: พบข่าวทั้งหมด {len(parsed_items)} รายการ")
            return True

        except Exception as e:
            logger.error(f"เกิดข้อผิดพลาดในการดึงข่าวจาก ForexFactory: {e}", exc_info=True)
            return False

    def _reconcile_html_times_with_json(self, items: List[ForexNewsItem]) -> List[ForexNewsItem]:
        """
        ตรวจสอบความถูกต้องของเวลาข่าวที่ parse จาก HTML โดยเทียบกับ JSON Feed
        (JSON Feed ระบุ Timezone Offset ชัดเจน เช่น -04:00 จึงถือเป็นเวลามาตรฐาน)

        สาเหตุที่ต้องมีขั้นตอนนี้: ForexFactory เรนเดอร์เวลาในหน้าเว็บตาม Timezone ของผู้เข้าชม
        ถ้าตรวจจับ Timezone ผิด (เช่น Page เรนเดอร์เวลาเดิมถูกต้องแต่อ่านผิดโซน) เวลาจะเพี้ยน
        เป็นค่าคงที่ เช่น 3 ชั่วโมง (คลาดเคลื่อนตามผู้ใช้รายงาน) ฟังก์ชันนี้จะปรับเวลาทั้งหมดให้ตรงใหม่
        """
        try:
            headers = {
                "User-Agent": self._BROWSER_HEADERS["User-Agent"],
                "Accept": "application/json",
            }
            resp = requests.get(self.THIS_WEEK_URL, headers=headers, timeout=12)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.debug(f"ไม่สามารถดึง JSON Feed เพื่อเทียบเวลาได้ ข้ามการปรับเวลา: {e}")
            return items

        # สร้างตารางค้นหา: (สกุล, ชื่อข่าว) -> รายการเวลา UTC จริง
        lookup: Dict[Tuple[str, str], List[datetime.datetime]] = {}
        for row in data:
            dt_obj = self._parse_datetime(row.get("date", ""))
            if dt_obj is None:
                continue
            key = (str(row.get("country", "")).strip().upper(), str(row.get("title", "")).strip())
            lookup.setdefault(key, []).append(dt_obj)

        # หาค่าเบี่ยงเบน (ชั่วโมง) ระหว่างเวลาจาก HTML กับเวลาจาก JSON ของข่าวที่ตรงกัน
        deltas = []
        for it in items:
            key = (it.country.strip().upper(), it.title.strip())
            for jdt in lookup.get(key, []) or []:
                # เปรียบเทียบเฉพาะรายการที่ตรงวันเดียวกันในเวลาไทย
                if it.date_local.date() != jdt.astimezone(self.tz).date():
                    continue
                delta_hours = (it.date_utc - jdt).total_seconds() / 3600.0
                deltas.append(round(delta_hours))
                break

        if not deltas:
            logger.debug("ไม่มีรายการข่าวที่ตรงกับ JSON Feed สำหรับเทียบเวลา")
            return items

        # หาค่าเบี่ยงเบนที่พบบ่อยที่สุด
        common_delta, common_count = Counter(deltas).most_common(1)[0]
        match_ratio = common_count / len(deltas)

        # ปลอดภัยเมื่อ: ส่วนใหญ่เห็นตรงกัน, เบี่ยงเบนไม่เกิน 14 ชม. (หลีกเลี่ยงผิดวันทั้งสัปดาห์)
        if common_delta == 0 or abs(common_delta) > 14 or match_ratio < 0.6:
            logger.debug(
                f"เวลา HTML ตรงกับ JSON แล้วหรือไม่มั่นใจพอ (delta={common_delta}h, ratio={match_ratio:.0%})"
            )
            return items

        logger.warning(
            f"พบเวลา HTML บนหน้าเว็บคลาดเคลื่อนจากเวลาจริง {common_delta:+d} ชั่วโมง "
            f"(เทียบ JSON Feed {match_ratio:.0%} รายการ) กำลังปรับเวลาให้ตรงทั้งหมด..."
        )
        shift = datetime.timedelta(hours=-common_delta)
        for it in items:
            it.date_utc = it.date_utc + shift
            it.date_local = it.date_utc.astimezone(self.tz)
        return items

    def _scrape_html_items(self) -> List[ForexNewsItem]:
        """
        ดึงข้อมูลจากหน้า Calendar ของเว็บ ForexFactory โดยตรง
        จุดประสงค์หลัก: ให้ได้ค่า Actual/Previous จริงที่ JSON Feed ไม่มี
        """
        if BeautifulSoup is None:
            logger.warning("ไม่พบไลบรารี beautifulsoup4 ใช้ข้อมูลจาก JSON Feed แทน")
            return []

        resp = None
        try:
            r = requests.get(self.CALENDAR_URL, headers=self._BROWSER_HEADERS, timeout=15)
            # หน้า Calendar จริงมีขนาดใหญ่ (~400KB) ส่วนหน้า Block/Challenge มักเล็กกว่า 50KB
            if r.ok and len(r.text) > 50000:
                resp = r
        except Exception as e:
            logger.debug(f"ดึงหน้า Calendar ด้วย requests ไม่สำเร็จ: {e!r}")

        if resp is None:
            # ลองเฟชด้วย curl_cffi (TLS impersonate เบราว์เซอร์) เป็นตัวสำรอง
            try:
                from curl_cffi import requests as cffi_requests

                r2 = cffi_requests.get(
                    self.CALENDAR_URL,
                    impersonate="chrome",
                    headers=self._BROWSER_HEADERS,
                    timeout=15,
                )
                if r2.ok and len(r2.text) > 50000:
                    resp = r2
            except Exception as e:
                logger.debug(f"ดึงหน้า Calendar ด้วย curl_cffi ไม่สำเร็จ: {e!r}")

        if resp is None:
            logger.warning("ไม่สามารถ scrape หน้า Calendar ได้ (อาจโดน Block) ใช้ JSON Feed แทน")
            return []

        items = self._parse_html_calendar(resp.text)
        logger.info(f"parse หน้า Calendar สำเร็จ: พบ {len(items)} รายการ")
        return items

    def _parse_html_calendar(self, html: str) -> List[ForexNewsItem]:
        """แยกข้อมูลตารางข่าวจาก HTML หน้า ForexFactory Calendar"""
        soup = BeautifulSoup(html, "html.parser")
        items: List[ForexNewsItem] = []
        # ForexFactory เรนเดอร์เวลาเป็น Timezone ของผู้เข้าชม -> ต้องตรวจสอบจากหน้าเว็บ
        render_tz = self._detect_render_timezone(html)
        current_day_epoch: Optional[int] = None
        # เหตุการณ์ที่ออกพร้อมกัน (เช่น CPI m/m + CPI y/y) มักไม่มีเวลาในแถวรอง
        # ให้ใช้เวลาจากแถวก่อนหน้าที่เหลือในวันเดียวกัน
        last_hour: Optional[int] = None
        last_minute: int = 0

        for tr in soup.select("tr.calendar__row"):
            classes = tr.get("class", []) or []
            if "calendar__row--day-breaker" in classes:
                continue
            if "calendar__row--no-event" in classes:
                continue

            # วันที่ (Epoch) จะอยู่เฉพาะแถวแรกของแต่ละวัน (--new-day) แถวถัด ๆ ไปใช้ค่าวันเดิม
            # Epoch นี้คือเที่ยงคืนของวันนั้นใน Timezone ที่ ForexFactory เรนเดอร์ (ตัวเดียวกับ time string)
            epoch_str = tr.get("data-day-dateline")
            if epoch_str:
                try:
                    current_day_epoch = int(epoch_str)
                except (TypeError, ValueError):
                    continue
            if current_day_epoch is None:
                continue

            try:
                day_ts = datetime.datetime.fromtimestamp(current_day_epoch, tz=render_tz)
            except (OSError, ValueError, OverflowError):
                continue

            time_str = self._extract_text(tr, ".calendar__time")
            hour, minute = self._parse_ff_time(time_str)
            if hour is not None:
                last_hour, last_minute = hour, minute
            else:
                hour, minute = last_hour, last_minute
                if hour is None:
                    continue

            utc_dt = day_ts.replace(hour=hour, minute=minute, second=0, microsecond=0)
            utc_dt = utc_dt.astimezone(datetime.timezone.utc)

            impact_class = ""
            impact_el = tr.select_one(".calendar__impact .icon")
            if impact_el:
                for c in impact_el.get("class", []) or []:
                    if str(c).startswith("icon--ff-impact"):
                        impact_class = str(c)
            impact = self._IMPACT_MAP.get(impact_class, "Low")

            actual_text, actual_color = self._extract_actual_with_color(tr)

            items.append(
                ForexNewsItem(
                    title=self._extract_text(tr, ".calendar__event-title") or "Unknown",
                    country=self._extract_text(tr, ".calendar__currency"),
                    date_utc=utc_dt,
                    date_local=utc_dt.astimezone(self.tz),
                    impact=impact,
                    forecast=self._clean_value(self._extract_text(tr, ".calendar__forecast")),
                    previous=self._clean_value(self._extract_text(tr, ".calendar__previous")),
                    actual=self._clean_value(actual_text),
                    actual_color=actual_color,
                )
            )

        return items

    @staticmethod
    def _extract_text(container, selector: str) -> str:
        """ดึงข้อความจาก Element แรกที่ตรง Selector"""
        el = container.select_one(selector)
        if el is None:
            return ""
        return el.get_text(" ", strip=True).replace("\xa0", " ")

    @staticmethod
    def _extract_actual_with_color(container) -> Tuple[str, str]:
        """
        ดึงข้อความและสีของตัวเลขจริง (Actual) จากหน้า ForexFactory
        ForexFactory ใช้ CSS class 'better' (สีเขียว) หรือ 'worse' (สีแดง)
        บน <span> ที่ครอบค่า Actual เพื่อแสดงว่าดีกว่าหรือแย่กว่าคาดการณ์
        :return: (actual_text, actual_color) เช่น ("2.5%", "better") หรือ ("1.2%", "worse")
        """
        el = container.select_one(".calendar__actual")
        if el is None:
            return "", ""
        # หา <span> ที่มี class 'better' หรือ 'worse' (ตัวเลขที่มีสี)
        span = el.select_one("span.better, span.worse")
        if span:
            color = "better" if "better" in span.get("class", []) else "worse"
            text = span.get_text(" ", strip=True).replace("\xa0", " ")
            return text, color
        # ถ้าไม่มี span ที่มีสี ให้ดึงข้อความปกติ
        text = el.get_text(" ", strip=True).replace("\xa0", " ")
        return text, ""

    @staticmethod
    def _clean_value(value: str) -> str:
        """ทำความสะอาดค่า Actual/Forecast/Previous (จับ '-' เป็นค่าว่าง = ยังไม่มีข้อมูล)"""
        value = (value or "").strip()
        if value in ("-", ""):
            return ""
        return value

    @staticmethod
    def _parse_ff_time(time_str: str) -> Tuple[Optional[int], int]:
        """แปลงเวลาจาก ForexFactory เช่น '8:30am', '12:00pm', 'All Day' -> (hour, minute)"""
        low = (time_str or "").strip().lower()
        if not low:
            return None, 0
        try:
            if low == "all day":
                return 0, 0
            if "am" in low or "pm" in low:
                meridiem = "am" if "am" in low else "pm"
                part = low.split(meridiem)[0].strip()
                hh = int(part.split(":")[0])
                mm = int(part.split(":")[1]) if ":" in part else 0
                hour = 0 if hh == 12 else hh
                if meridiem == "pm":
                    hour = 12 if hh == 12 else hh + 12
                return hour, mm
            if ":" in low and low[0].isdigit():
                hh = int(low.split(":")[0])
                mm = int(low.split(":")[1][:2])
                return hh % 24, mm
        except Exception:
            return None, 0
        return None, 0

    def _parse_datetime(self, date_str: str) -> Optional[datetime.datetime]:
        """แปลง ISO String เป็น timezone-aware datetime object"""
        if not date_str:
            return None
        try:
            # รองรับ format ISO 8601 เช่น 2026-09-08T08:30:00-04:00 หรือ Z
            dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except Exception:
            try:
                # fallback parse ด้วย strptime ทั่วไป
                raw_dt = datetime.datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S")
                return raw_dt.replace(tzinfo=datetime.timezone.utc)
            except Exception:
                return None

    def _filter_alert_currencies(self, news_items: List[ForexNewsItem]) -> List[ForexNewsItem]:
        """
        กรองข่าวตามสกุลเงินที่ตั้งค่าไว้ใน LINE (WEEKLY_ALERT_CURRENCIES)
        เช่น "USD" -> เฉพาะข่าว USD, "USD,EUR" -> USD + EUR
        - ค่าว่าง/ไม่ตั้งค่า -> ใช้ค่าเริ่มต้นเป็น USD
        - ตั้ง "ALL" -> ส่งทุกสกุลเงิน
        """
        raw = (getattr(config.news, "weekly_alert_currencies", "") or "").strip()
        currencies = [c.strip().upper() for c in raw.split(",") if c.strip()]
        if not currencies:
            currencies = ["USD"]
        logger.info(f"สกุลเงินที่ตั้งค่าไว้ (WEEKLY_ALERT_CURRENCIES): {currencies}")
        if "ALL" in currencies:
            return news_items
        filtered = [n for n in news_items if n.country.upper() in currencies]
        logger.info(
            f"กรองข่าวตามสกุลเงิน {currencies} สำหรับ LINE: เหลือ {len(filtered)} จาก {len(news_items)} รายการ"
        )
        return filtered

    def group_by_day(self, news_items: List[ForexNewsItem]) -> Dict[str, List[ForexNewsItem]]:
        """
        จัดกลุ่มข่าวตามวันที่ (วันจันทร์ ถึง วันศุกร์)
        :param news_items: รายการข่าว
        :return: Dict ที่มี Key เป็นวันที่ 'YYYY-MM-DD'
        """
        grouped: Dict[str, List[ForexNewsItem]] = {}
        for item in news_items:
            day_key = item.date_local.strftime("%Y-%m-%d")
            if day_key not in grouped:
                grouped[day_key] = []
            grouped[day_key].append(item)
        return grouped

    def get_week_business_days(self, reference_date: Optional[datetime.date] = None) -> List[datetime.date]:
        """
        หาช่วงวันทำการ (วันจันทร์ ถึง วันศุกร์) ของสัปดาห์
        :param reference_date: วันอ้างอิง (ค่าเริ่มต้นคือวันปัจจุบัน)
        :return: รายการวันจันทร์-วันศุกร์
        """
        if reference_date is None:
            reference_date = datetime.datetime.now(self.tz).date()

        # หาวันจันทร์ของสัปดาห์นั้น (weekday = 0)
        monday = reference_date - datetime.timedelta(days=reference_date.weekday())
        # วันจันทร์ (0) ถึง วันศุกร์ (4)
        return [monday + datetime.timedelta(days=i) for i in range(5)]

    def format_weekly_line_message(
        self, news_items: Optional[List[ForexNewsItem]] = None, reference_date: Optional[datetime.date] = None
    ) -> str:
        """
        จัดรูปแบบข้อความแจ้งเตือนสรุปภาพรวมข่าวสีแดงประจำสัปดาห์สำหรับส่ง LINE
        ตรงตามข้อกำหนด:
        1. จำนวนข่าวสีแดงทั้งหมดในสัปดาห์นั้น
        2. รายละเอียดข่าวแดงในแต่ละวัน (ชื่อข่าว, สกุลเงิน, เวลาที่ข่าวออก)
        3. หากวันไหน 'ไม่มีข่าวสีแดง' ให้พิมพ์บอกสถานะอย่างชัดเจนว่า 'วันนี้ไม่มีข่าวสีแดง สามารถเทรดได้ตลอดวัน'
        """
        if news_items is None:
            news_items = self.fetch_this_week_news(only_high_impact=True)
        else:
            news_items = [n for n in news_items if n.is_high_impact]

        # กรองเฉพาะสกุลเงินที่ตั้งค่าไว้ใน LINE (ค่า default: USD)
        news_items = self._filter_alert_currencies(news_items)

        # สกุลเงินที่ใช้กรอง (แสดงไว้บนหัวข้อความ เพื่อให้เห็นชัดเจนว่าส่งเฉพาะสกุลไหน)
        raw_cfg = (getattr(config.news, "weekly_alert_currencies", "") or "").strip()
        filter_currencies = [c.strip().upper() for c in raw_cfg.split(",") if c.strip()] or ["USD"]

        business_days = self.get_week_business_days(reference_date)
        start_date_str = business_days[0].strftime("%d/%m/%Y")
        end_date_str = business_days[-1].strftime("%d/%m/%Y")

        grouped = self.group_by_day(news_items)
        total_high_impact = len(news_items)

        thai_day_names = {
            0: "วันจันทร์",
            1: "วันอังคาร",
            2: "วันพุธ",
            3: "วันพฤหัสบดี",
            4: "วันศุกร์",
        }

        # สร้างเนื้อหาข้อความ
        lines = [
            "🔴 [ForexFactory] สรุปข่าวแดงประจำสัปดาห์ 🔴",
            f"📅 ประจำวันที่: {start_date_str} - {end_date_str}",
        ]
        if "ALL" not in filter_currencies:
            lines.append(f"💱 สกุลเงินที่ติดตาม: {', '.join(filter_currencies)}")
        lines.append(
            f"⚠️ จำนวนข่าวสีแดง (High-Impact) ทั้งหมด: {total_high_impact} ข่าว"
        )
        lines.append("=" * 28)

        for day in business_days:
            day_key = day.strftime("%Y-%m-%d")
            day_name = thai_day_names.get(day.weekday(), day.strftime("%A"))
            date_formatted = day.strftime("%d/%m")

            lines.append(f"\n📌 {day_name} ({date_formatted}):")

            day_events = grouped.get(day_key, [])
            if not day_events:
                # ข้อกำหนด: หากวันไหน 'ไม่มีข่าวสีแดง' ให้พิมพ์บอกสถานะอย่างชัดเจน
                lines.append("   🟢 วันนี้ไม่มีข่าวสีแดง สามารถเทรดได้ตลอดวัน")
            else:
                for idx, event in enumerate(day_events, start=1):
                    lines.append(
                        f"   {idx}. ⏰ {event.time_str} | [{event.country}] {event.title}"
                    )

        lines.append("\n" + "=" * 28)
        lines.append("💡 คำแนะนำ: วางแผนการเทรดและบริหารความเสี่ยง (Risk Management) อย่างรัดกุมก่อนเวลาข่าวออกครับ")

        return "\n".join(lines)
