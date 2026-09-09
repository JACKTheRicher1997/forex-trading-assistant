"""
Main Trading Assistant & Alert System Controller
คลาสหลักควบคุมระบบ (Core Orchestrator) ตามหลักการ OOP
ทำหน้าที่ผสานการทำงานระหว่าง Yahoo Finance, ForexFactory News, Indicator และ LINE Notification
"""

import sys
import time
import signal
import argparse
from typing import Optional

# จัดการ UTF-8 สำหรับ Windows Console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from logger import get_logger, AppLogger
from config import config
from services.price_service import PriceService
from services.indicator_service import IndicatorService, CrossSignal
from services.news_service import ForexFactoryNewsService
from services.notifier import NotificationService
from services.scheduler_service import AlertScheduler

logger = get_logger("TradingAssistant")


class TradingAssistant:
    """
    คลาสหลักควบคุมระบบผู้ช่วยเทรด Forex (Trading Assistant Controller)
    ออกแบบตามหลัก Clean Architecture และ Dependency Injection
    """

    def __init__(
        self,
        price_service: Optional[PriceService] = None,
        indicator_service: Optional[IndicatorService] = None,
        news_service: Optional[ForexFactoryNewsService] = None,
        notifier: Optional[NotificationService] = None,
    ):
        # 1. จัดการ Dependency Injection
        self.price_service = price_service or PriceService()
        self.indicator_service = indicator_service or IndicatorService()
        self.news_service = news_service or ForexFactoryNewsService()
        self.notifier = notifier or NotificationService()

        # 2. ตัวควบคุม Scheduler
        self.scheduler = AlertScheduler(
            news_job_callback=self.broadcast_weekly_news_alert,
            ema_check_callback=self.check_live_ema_cross,
        )

        self._is_running = False

    def initialize(self) -> bool:
        """เตรียมความพร้อมของระบบและตรวจสอบการเชื่อมต่อ"""
        logger.info("=" * 60)
        logger.info("🚀 กำลังเริ่มต้นระบบผู้ช่วยเทรด Forex และระบบแจ้งเตือน 🚀")
        logger.info("=" * 60)

        # เชื่อมต่อ Yahoo Finance
        connected = self.price_service.connect()
        if not connected:
            logger.warning("⚠️ ไม่สามารถเชื่อมต่อ Yahoo Finance ได้ในขณะนี้ ระบบจะพยายามเชื่อมต่อใหม่อัตโนมัติเมื่อเริ่มรอบตรวจ")

        # ตรวจสอบการดึงข่าว
        try:
            news = self.news_service.fetch_this_week_news(only_high_impact=True)
            logger.info(f"📰 ดึงข่าว ForexFactory สำเร็จ: มีข่าวแดงสัปดาห์นี้ {len(news)} ข่าว")
        except Exception as e:
            logger.error(f"⚠️ เกิดข้อผิดพลาดในการดึงข่าวเบื้องต้น: {e}")

        return True

    def check_live_ema_cross(self) -> None:
        """
        ตรวจสอบการตัดกันของ EMA 50 และ EMA 150 แบบ Live
        หากเกิดการตัดกันขึ้นหรือลง จะส่งแจ้งเตือนเข้า LINE ทันที (ป้องกันการส่งซ้ำ)
        """
        symbol = self.price_service.symbol
        timeframe = self.price_service.timeframe_str

        # เงื่อนไขพิเศษ: ตรวจจับและแจ้งเตือนเฉพาะ Timeframe 5 นาที (M5) เท่านั้น
        if timeframe != "M5":
            return

        # ดึงข้อมูลแท่งเทียนย้อนหลัง
        df = self.price_service.get_rates(count=300)
        if df is None or len(df) == 0:
            logger.warning(f"ไม่สามารถดึงแท่งเทียนสำหรับ {symbol} ({timeframe}) เพื่อตรวจ EMA Cross ได้")
            return

        # คำนวณและวิเคราะห์อินดิเคเตอร์
        result = self.indicator_service.analyze(df, symbol=symbol, timeframe=timeframe)
        if result is None:
            return

        logger.debug(
            f"[{symbol} {timeframe}] Close: {result.close_price:.2f} | "
            f"EMA50: {result.ema_fast:.2f} | EMA150: {result.ema_slow:.2f} | "
            f"Trend: {result.trend.value} | Cross: {result.cross_signal.value}"
        )

        # ตรวจสอบว่าเกิดสัญญาณตัดกันใหม่หรือไม่
        if result.is_new_signal and result.cross_signal != CrossSignal.NONE:
            message = result.format_line_alert_message()
            logger.info(f"🔥 ส่งการแจ้งเตือน Live EMA Signal ({result.cross_signal.value}) ไปยัง LINE!")
            self.notifier.send_live_ema_cross_alert(message)

    def broadcast_weekly_news_alert(self) -> None:
        """
        ดึงและส่งสรุปภาพรวมข่าวสีแดงประจำสัปดาห์เข้า LINE
        ตรงตามข้อกำหนดสำหรับเช้าวันจันทร์
        """
        logger.info("📢 กำลังสร้างและส่งข้อความสรุปข่าวแดงประจำสัปดาห์...")
        try:
            news_items = self.news_service.fetch_this_week_news(force_refresh=True, only_high_impact=True)
            formatted_message = self.news_service.format_weekly_line_message(news_items)
            success = self.notifier.send_weekly_news_alert(formatted_message)
            if success:
                logger.info("✅ ส่งข้อความสรุปข่าวแดงประจำสัปดาห์เรียบร้อยแล้ว")
            else:
                logger.error("❌ ส่งข้อความสรุปข่าวแดงประจำสัปดาห์ไม่สำเร็จ")
        except Exception as e:
            logger.error(f"เกิดข้อผิดพลาดขณะส่งสรุปข่าวประจำสัปดาห์: {e}", exc_info=True)

    def start(self) -> None:
        """เริ่มการทำงานของระบบหลัก"""
        self.initialize()
        self._is_running = True

        # ผูกฟังก์ชันดักจับ Ctrl + C
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

        # เริ่มต้น Scheduler ใน Background Thread
        self.scheduler.start_background()

        logger.info("🎯 ระบบ Trading Assistant เริ่มต้นทำงานเต็มรูปแบบแล้ว (กด Ctrl+C เพื่อหยุดการทำงาน)")

        # ทำงานรอบแรกทันที
        self.check_live_ema_cross()

        # Main thread loop
        try:
            while self._is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            self._handle_exit(None, None)

    def _handle_exit(self, signum, frame) -> None:
        """จัดการการหยุดทำงานอย่างปลอดภัย (Graceful Shutdown)"""
        if not self._is_running:
            return
        logger.info("\n🛑 ได้รับคำสั่งให้หยุดการทำงาน กำลังปิดระบบ...")
        self._is_running = False
        self.scheduler.stop()
        self.price_service.shutdown()
        logger.info("👋 ปิดระบบผู้ช่วยเทรดเรียบร้อยแล้ว ขอบคุณที่ใช้งานครับ")
        sys.exit(0)


def parse_arguments():
    """จัดการ Command Line Arguments สำหรับการทดสอบฟังก์ชันต่างๆ"""
    parser = argparse.ArgumentParser(description="Forex Trading Assistant & Alert System")
    parser.add_argument("--test-line", action="store_true", help="ทดสอบส่งข้อความเข้า LINE ทันที")
    parser.add_argument("--send-news-now", action="store_true", help="ดึงและส่งสรุปข่าวแดงประจำสัปดาห์เข้า LINE ทันที")
    parser.add_argument("--check-ema-now", action="store_true", help="ตรวจสอบสถานะ EMA 50/150 และแสดงผลทันที")
    return parser.parse_args()


def main():
    """ฟังก์ชัน Entry Point หลัก"""
    args = parse_arguments()
    assistant = TradingAssistant()

    # โหมดทดสอบส่ง LINE
    if args.test_line:
        logger.info("--- โหมดทดสอบส่ง LINE ---")
        assistant.notifier.send_test_message()
        return

    # โหมดทดสอบส่งข่าวสัปดาห์นี้
    if args.send_news_now:
        logger.info("--- โหมดทดสอบส่งสรุปข่าวแดงประจำสัปดาห์ ---")
        assistant.broadcast_weekly_news_alert()
        return

    # โหมดตรวจ EMA ทันที 1 ครั้ง
    if args.check_ema_now:
        logger.info("--- โหมดตรวจสอบ EMA ทันที ---")
        assistant.initialize()
        assistant.check_live_ema_cross()
        assistant.price_service.shutdown()
        return

    # รันโหมดปกติ (Continuous Background Bot)
    assistant.start()


if __name__ == "__main__":
    main()
