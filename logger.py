"""
Logger Module for Forex Trading Assistant & Alert System
จัดการระบบ Logging ทั้งแสดงผลบน Console และบันทึกลงไฟล์อย่างเป็นระบบ
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional


class AppLogger:
    """
    Singleton Logger Manager สำหรับระบบเทรด
    ช่วยสร้างและจัดการ Logger ให้กับทุก Service ในระบบ
    """

    _instance: Optional["AppLogger"] = None
    _configured: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(AppLogger, cls).__new__(cls)
        return cls._instance

    def __init__(
        self,
        log_file: str = "bot.log",
        log_level: int = logging.INFO,
        max_bytes: int = 5 * 1024 * 1024,  # 5 MB
        backup_count: int = 5,
    ):
        if not self._configured:
            self.log_file = log_file
            self.log_level = log_level
            self.max_bytes = max_bytes
            self.backup_count = backup_count
            self._setup_logging()
            self._configured = True

    def _setup_logging(self) -> None:
        """ตั้งค่า Root Logger ทั้ง StreamHandler และ RotatingFileHandler"""
        root_logger = logging.getLogger()
        root_logger.setLevel(self.log_level)

        # หลีกเลี่ยง Handler ซ้ำซ้อน
        if root_logger.hasHandlers():
            root_logger.handlers.clear()

        # รูปแบบ Log: [วันเวลา] [ระดับ] [โมดูล] ข้อความ
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # รองรับ UTF-8 บน Windows Console ป้องกัน UnicodeEncodeError เมื่อพิมพ์ Emoji
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass

        # 1. Console Handler (แสดงบน Terminal / Command Line)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.log_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # 2. Rotating File Handler (บันทึกลงไฟล์ หมุนวนเมื่อครบขนาด ป้องกันไฟล์ใหญ่เกินไป)
        try:
            file_handler = RotatingFileHandler(
                filename=self.log_file,
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(self.log_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            print(f"[Warning] ไม่สามารถเปิดไฟล์ log ได้: {e}", file=sys.stderr)

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        ดึง Logger ประจำโมดูล
        :param name: ชื่อโมดูล เช่น __name__ หรือชื่อคลาส
        :return: logging.Logger instance
        """
        if not cls._configured:
            cls()
        return logging.getLogger(name)


def get_logger(name: str) -> logging.Logger:
    """Helper function สำหรับดึง logger ได้อย่างสะดวก"""
    return AppLogger.get_logger(name)
