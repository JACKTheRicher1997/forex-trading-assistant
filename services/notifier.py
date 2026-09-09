"""
Notification Service Module
ระบบส่งการแจ้งเตือนเข้า LINE
รองรับทั้ง LINE Notify API และ LINE Messaging API (Channel Access Token + Push)
พร้อมระบบบันทึก Log และการตรวจสอบความถูกต้อง
"""

from typing import Optional, Dict, Any
import requests

from logger import get_logger
from config import config

logger = get_logger("NotificationService")


class LineNotifier:
    """
    คลาสจัดการการส่งข้อความผ่าน LINE
    รองรับ:
    1. LINE Messaging API (Push Message) -> แนะนำ เพราะไม่มีวันหมดอายุ
    2. LINE Notify API (Token) -> ทางเลือกคลาสสิก
    """

    LINE_NOTIFY_API_URL = "https://notify-api.line.me/api/notify"
    LINE_PUSH_API_URL = "https://api.line.me/v2/bot/message/push"

    def __init__(
        self,
        notify_token: Optional[str] = None,
        channel_access_token: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        self.notify_token = notify_token or config.line.notify_token
        self.channel_access_token = channel_access_token or config.line.channel_access_token
        self.user_id = user_id or config.line.user_id

    def send_via_line_notify(self, message: str) -> bool:
        """ส่งข้อความผ่าน LINE Notify Service"""
        if not self.notify_token:
            logger.debug("ไม่ได้ตั้งค่า LINE_NOTIFY_TOKEN")
            return False

        headers = {
            "Authorization": f"Bearer {self.notify_token}",
        }
        payload = {"message": message}

        try:
            logger.info("กำลังส่งแจ้งเตือนผ่าน LINE Notify...")
            response = requests.post(
                self.LINE_NOTIFY_API_URL,
                headers=headers,
                data=payload,
                timeout=10,
            )
            if response.status_code == 200:
                logger.info("✅ ส่งข้อความผ่าน LINE Notify สำเร็จ")
                return True
            else:
                logger.error(
                    f"❌ ส่ง LINE Notify ล้มเหลว! รหัส HTTP: {response.status_code}, ข้อความ: {response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"❌ เกิดข้อผิดพลาดขณะส่ง LINE Notify: {e}")
            return False

    def send_via_messaging_api(self, message: str) -> bool:
        """ส่งข้อความผ่าน LINE Messaging API (Push Message ไปยัง User ID)"""
        if not self.channel_access_token or not self.user_id:
            logger.debug("ไม่ได้ตั้งค่า LINE_CHANNEL_ACCESS_TOKEN หรือ LINE_USER_ID")
            return False

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.channel_access_token}",
        }
        payload: Dict[str, Any] = {
            "to": self.user_id,
            "messages": [
                {
                    "type": "text",
                    "text": message,
                }
            ],
        }

        try:
            logger.info(f"กำลังส่งข้อความผ่าน LINE Messaging API ไปยัง User ID: {self.user_id[:6]}***...")
            response = requests.post(
                self.LINE_PUSH_API_URL,
                headers=headers,
                json=payload,
                timeout=10,
            )
            if response.status_code == 200:
                logger.info("✅ ส่งข้อความผ่าน LINE Messaging API สำเร็จ")
                return True
            else:
                logger.error(
                    f"❌ ส่ง LINE Messaging API ล้มเหลว! รหัส HTTP: {response.status_code}, ข้อความ: {response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"❌ เกิดข้อผิดพลาดขณะส่ง LINE Messaging API: {e}")
            return False

    def send(self, message: str) -> bool:
        """
        ส่งข้อความไปยัง LINE โดยจะพยายามส่งทั้ง LINE Messaging API และ LINE Notify ที่มี
        :param message: เนื้อหาข้อความ
        :return: True หากส่งผ่านช่องทางใดช่องทางหนึ่งสำเร็จ
        """
        success = False

        # 1. พยายามส่งผ่าน LINE Messaging API (หากมี Access Token & User ID)
        if self.channel_access_token and self.user_id:
            if self.send_via_messaging_api(message):
                success = True

        # 2. หากมี LINE Notify Token ให้ส่งด้วย
        if self.notify_token:
            if self.send_via_line_notify(message):
                success = True

        if not success:
            logger.warning("⚠️ ไม่สามารถส่งข้อความได้เนื่องจากไม่มี Token หรือ Token ไม่ถูกต้อง")

        return success


class NotificationService:
    """
    คลาส Facade ประสานงานระบบแจ้งเตือนทั้งหมดของแอพพลิเคชัน
    """

    def __init__(self, notifier: Optional[LineNotifier] = None):
        self.notifier = notifier or LineNotifier()

    def send_weekly_news_alert(self, formatted_message: str) -> bool:
        """ส่งการแจ้งเตือนสรุปข่าวสีแดงประจำสัปดาห์"""
        logger.info("🔔 กำลังส่งการแจ้งเตือนสรุปข่าวแดงประจำสัปดาห์...")
        return self.notifier.send(formatted_message)

    def send_live_ema_cross_alert(self, signal_message: str) -> bool:
        """ส่งการแจ้งเตือน Live EMA Cross ทันที"""
        logger.info("🔔 กำลังส่งการแจ้งเตือน Live EMA Cross...")
        return self.notifier.send(signal_message)

    def send_test_message(self) -> bool:
        """ส่งข้อความทดสอบการเชื่อมต่อระบบแจ้งเตือน"""
        test_msg = (
            "🔔 [Test Alert] ทดสอบการเชื่อมต่อระบบแจ้งเตือน\n"
            "ระบบผู้ช่วยเทรด Forex (Trading Assistant & Alert System)\n"
            "สถานะ: ระบบทำงานปกติ พร้อมส่งสัญญาณ Live Cross และข่าวเศรษฐกิจครับ 🚀"
        )
        return self.notifier.send(test_msg)
