"""
Scheduler Service Module
จัดการตารางเวลาการส่งสรุปข่าวแดงทุกเช้าวันจันทร์
และรอบการตรวจสอบสัญญาณ Live EMA Cross อย่างต่อเนื่อง
"""

import time
import threading
from typing import Callable, Optional
import schedule

from logger import get_logger
from config import config

logger = get_logger("SchedulerService")


class AlertScheduler:
    """
    คลาสควบคุมตารางเวลา (Scheduler) ตามหลัก OOP
    - ส่งสรุปข่าวแดงทุกเช้าวันจันทร์
    - วนลูปตรวจสอบ Live EMA Cross ตามรอบเวลาที่กำหนด
    """

    def __init__(
        self,
        news_job_callback: Callable[[], None],
        ema_check_callback: Callable[[], None],
        check_interval_seconds: Optional[int] = None,
    ):
        self.news_job_callback = news_job_callback
        self.ema_check_callback = ema_check_callback
        self.check_interval_seconds = check_interval_seconds or config.poll_interval_seconds
        self._is_running = False
        self._thread: Optional[threading.Thread] = None

    def setup_schedules(self) -> None:
        """ตั้งค่าตารางงานสำหรับส่งสรุปข่าวและตรวจสัญญาณ"""
        schedule.clear()

        # 1. งานส่งสรุปข่าวแดง: สัปดาห์ละ 1 ครั้ง ในทุกๆ เช้าวันจันทร์ (เช่น 06:30 น.)
        alert_day = config.news.weekly_alert_day.lower()
        alert_time = config.news.weekly_alert_time

        logger.info(f"📅 กำหนดตารางส่งสรุปข่าวแดง: ทุกวัน {alert_day.capitalize()} เวลา {alert_time} น.")

        if alert_day == "monday":
            schedule.every().monday.at(alert_time).do(self._safe_run_news_job)
        elif alert_day == "sunday":
            schedule.every().sunday.at(alert_time).do(self._safe_run_news_job)
        else:
            schedule.every().monday.at(alert_time).do(self._safe_run_news_job)

    def _safe_run_news_job(self) -> None:
        """เรียกใช้งานฟังก์ชันส่งข่าวพร้อมดักจับ Exception"""
        logger.info("⏰ ถึงเวลาส่งสรุปข่าวประจำสัปดาห์ตามตารางนัดหมาย!")
        try:
            self.news_job_callback()
        except Exception as e:
            logger.error(f"เกิดข้อผิดพลาดในการรันงานสรุปข่าว: {e}", exc_info=True)

    def start_background(self) -> None:
        """เริ่มการทำงาน Scheduler ใน Background Thread"""
        if self._is_running:
            logger.warning("Scheduler กำลังทำงานอยู่แล้ว")
            return

        self.setup_schedules()
        self._is_running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="SchedulerThread")
        self._thread.start()
        logger.info("🚀 Scheduler เริ่มทำงานใน Background Thread เรียบร้อยแล้ว")

    def _run_loop(self) -> None:
        """ลูปหลักในการรัน Schedule และตรวจสอบ EMA Cross"""
        last_ema_check = 0.0

        while self._is_running:
            try:
                now = time.time()

                # 1. ตรวจสอบตาราง schedule (สรุปข่าววันจันทร์)
                schedule.run_pending()

                # 2. ตรวจสอบ EMA Live Cross ทุกๆ check_interval_seconds วินาที
                if now - last_ema_check >= self.check_interval_seconds:
                    try:
                        self.ema_check_callback()
                    except Exception as e:
                        logger.error(f"ข้อผิดพลาดขณะตรวจสอบ EMA Cross: {e}")
                    last_ema_check = now

                time.sleep(1)
            except Exception as e:
                logger.error(f"ข้อผิดพลาดที่ไม่คาดคิดใน Scheduler Loop: {e}")
                time.sleep(5)

    def stop(self) -> None:
        """หยุดการทำงานของ Scheduler"""
        logger.info("กำลังหยุดการทำงานของ Scheduler...")
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        schedule.clear()
        logger.info("Scheduler หยุดทำงานแล้ว")
