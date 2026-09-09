"""
ForexFactory News Service Module
ดึงข้อมูลตารางข่าวเศรษฐกิจจาก ForexFactory กรองเฉพาะข่าวสีแดง (High-Impact)
และจัดรูปแบบข้อความแจ้งเตือนสรุปรายสัปดาห์
"""

import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional
import requests

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

try:
    import pytz
except ImportError:
    pytz = None

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

    @property
    def is_high_impact(self) -> bool:
        """ตรวจสอบว่าเป็นข่าวสีแดง (High Impact) หรือไม่"""
        return self.impact.lower() == "high"

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

    def __init__(self, target_timezone: str = None):
        self.timezone_name = target_timezone or config.news.timezone
        self.tz = self._init_timezone(self.timezone_name)
        self._cached_news: List[ForexNewsItem] = []
        self._last_fetched: Optional[datetime.datetime] = None

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
        :param force_refresh: บังคับดึงข้อมูลใหม่โดยไม่ใช้แคช
        :param only_high_impact: กรองเอาเฉพาะข่าวสีแดง (High Impact) เท่านั้น
        :return: รายการ ForexNewsItem
        """
        now = datetime.datetime.now(self.tz)
        # ใช้แคชถ้าเพิ่งดึงไปไม่เกิน 15 นาที
        if not force_refresh and self._cached_news and self._last_fetched:
            if (now - self._last_fetched).total_seconds() < 900:
                logger.debug("ใช้ข้อมูลข่าวจากหน่วยความจำแคช")
                return [n for n in self._cached_news if not only_high_impact or n.is_high_impact]

        logger.info("กำลังดึงข้อมูลข่าวเศรษฐกิจสัปดาห์นี้จาก ForexFactory...")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

        try:
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

                news_item = ForexNewsItem(
                    title=item.get("title", "Unknown"),
                    country=item.get("country", ""),
                    date_utc=dt_obj,
                    date_local=local_dt,
                    impact=item.get("impact", "Low"),
                    forecast=item.get("forecast", ""),
                    previous=item.get("previous", ""),
                    actual=item.get("actual", ""),
                )
                parsed_items.append(news_item)

            self._cached_news = parsed_items
            self._last_fetched = now
            logger.info(f"ดึงข้อมูลข่าวสำเร็จ: พบข่าวทั้งหมด {len(parsed_items)} รายการ")

        except Exception as e:
            logger.error(f"เกิดข้อผิดพลาดในการดึงข่าวจาก ForexFactory: {e}", exc_info=True)
            # ถ้าดึงไม่สำเร็จและไม่มีแคชเดิม ให้คืนค่าแคชที่มีหรือข้อมูลสำรอง
            if not self._cached_news:
                logger.warning("ไม่มีข้อมูลข่าวในแคช ใช้รายการว่าง")
                return []

        if only_high_impact:
            filtered = [item for item in self._cached_news if item.is_high_impact]
            logger.info(f"กรองเฉพาะข่าวสีแดง (High-Impact): พบ {len(filtered)} รายการ")
            return filtered

        return self._cached_news

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

        # กรองเอาเฉพาะข่าวของ USD เท่านั้นสำหรับการแจ้งเตือน
        news_items = [n for n in news_items if n.country == "USD"]

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
            f"⚠️ จำนวนข่าวสีแดง (High-Impact) ทั้งหมด: {total_high_impact} ข่าว",
            "=" * 28,
        ]

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
