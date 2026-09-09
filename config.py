"""
Configuration Module for Forex Trading Assistant & Alert System
โหลดและจัดการการตั้งค่าจากไฟล์ .env อย่างปลอดภัยและเป็นระบบ
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# โหลด Environment Variables จากไฟล์ .env ในไดเรกทอรีปัจจุบัน
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)


@dataclass(frozen=True)
class MT5Config:
    """
    การตั้งค่าสัญลักษณ์และ Timeframe
    (เปลี่ยนจาก MT5Config เดิม - ลบ MT5 login ออก ใช้สำหรับ PriceService แทน)
    """
    symbol: str = field(default_factory=lambda: os.getenv("SYMBOL", "XAUUSDm"))
    timeframe: str = field(default_factory=lambda: os.getenv("TIMEFRAME", "M5"))


@dataclass(frozen=True)
class IndicatorConfig:
    """การตั้งค่าอินดิเคเตอร์ EMA"""
    ema_fast: int = field(default_factory=lambda: int(os.getenv("EMA_FAST", "50")))
    ema_slow: int = field(default_factory=lambda: int(os.getenv("EMA_SLOW", "150")))
    bars_count: int = field(default_factory=lambda: int(os.getenv("BARS_COUNT", "300")))


@dataclass(frozen=True)
class LineConfig:
    """
    การตั้งค่าการแจ้งเตือน LINE
    รองรับทั้ง LINE Notify Token ดั้งเดิม และ LINE Messaging API (Official Account)
    """
    notify_token: str = field(default_factory=lambda: os.getenv("LINE_NOTIFY_TOKEN", ""))
    channel_access_token: str = field(default_factory=lambda: os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""))
    user_id: str = field(default_factory=lambda: os.getenv("LINE_USER_ID", ""))


@dataclass(frozen=True)
class NewsConfig:
    """การตั้งค่าระบบดึงข่าว ForexFactory"""
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Bangkok"))
    weekly_alert_day: str = field(default_factory=lambda: os.getenv("WEEKLY_ALERT_DAY", "monday"))
    weekly_alert_time: str = field(default_factory=lambda: os.getenv("WEEKLY_ALERT_TIME", "06:30"))  # 06:30 เช้าวันจันทร์ ก่อนตลาดเปิด


@dataclass(frozen=True)
class AppConfig:
    """คลาสศูนย์รวมการตั้งค่าทั้งหมดของระบบ (Centralized Configuration)"""
    mt5: MT5Config = field(default_factory=MT5Config)
    indicator: IndicatorConfig = field(default_factory=IndicatorConfig)
    line: LineConfig = field(default_factory=LineConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
    poll_interval_seconds: int = field(default_factory=lambda: int(os.getenv("POLL_INTERVAL_SECONDS", "30")))


# สร้าง Global Config Object พร้อมใช้งาน
config = AppConfig()
