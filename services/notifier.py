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
    LINE_QUOTA_URL = "https://api.line.me/v2/bot/message/quota"
    LINE_QUOTA_CONSUMPTION_URL = "https://api.line.me/v2/bot/message/quota/consumption"

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

    def _quota_footer(self) -> str:
        """
        สร้างส่วนท้ายข้อความแสดงจำนวนข้อความ LINE ที่ใช้ไปแล้ว / เหลือ / วันรีเซ็ต
        ใช้ได้เฉพาะ LINE Messaging API ถ้าไม่ตั้งค่าหรือเรียกไม่ได้จะคืนค่าว่าง
        """
        try:
            usage = self.get_consumption()
            if usage is None:
                return ""
            used = int(usage.get("totalUsage", 0) or 0)
            quota = self.get_quota()
            if quota is None:
                return ""
            if quota.get("type") == "none":
                return (
                    "\n\n📊 สถานะข้อความ LINE\n"
                    f"📨 ใช้ไปแล้ว: {used} ข้อความ (แผนนี้ไม่มีวงเงิน)"
                )
            total = int(quota.get("value", 0) or 0)
            remaining = max(total - used, 0)
            return (
                "\n\n📊 สถานะข้อความ LINE (เดือนนี้)\n"
                f"📨 ใช้ไปแล้ว: {used} / {total} ข้อความ\n"
                f"✅ เหลือ: {remaining} ข้อความ\n"
                f"🔄 รีเซ็ต: วันที่ 1 ของทุกเดือน"
            )
        except Exception as e:
            logger.debug(f"ไม่สามารถแนบสรุปยอดโควต้าได้: {e}")
            return ""

    def send(self, message: str) -> bool:
        """
        ส่งข้อความไปยัง LINE โดยจะพยายามส่งทั้ง LINE Messaging API และ LINE Notify ที่มี
        :param message: เนื้อหาข้อความ
        :return: True หากส่งผ่านช่องทางใดช่องทางหนึ่งสำเร็จ
        """
        success = False

        # ต่อท้ายส่วนสรุปยอดโควต้า (เฉพาะเมื่อตรวจได้)
        footer = self._quota_footer()
        full_message = message + footer if footer else message

        # 1. พยายามส่งผ่าน LINE Messaging API (หากมี Access Token & User ID)
        if self.channel_access_token and self.user_id:
            if self.send_via_messaging_api(full_message):
                success = True

        # 2. หากมี LINE Notify Token ให้ส่งด้วย
        if self.notify_token:
            if self.send_via_line_notify(full_message):
                success = True

        if not success:
            logger.warning("⚠️ ไม่สามารถส่งข้อความได้เนื่องจากไม่มี Token หรือ Token ไม่ถูกต้อง")

        return success

    def get_quota(self) -> Optional[Dict[str, Any]]:
        """
        ดึงวงเงิน (Target Limit) การส่งข้อความประจำเดือนของ LINE Messaging API
        :return: {"type": "limited", "value": 200} หรือ {"type": "none"} (ไม่มีวงเงิน) หรือ None
        """
        if not self.channel_access_token:
            logger.debug("ไม่ได้ตั้งค่า LINE_CHANNEL_ACCESS_TOKEN ข้ามการตรวจโควต้า")
            return None
        try:
            headers = {"Authorization": f"Bearer {self.channel_access_token}"}
            resp = requests.get(self.LINE_QUOTA_URL, headers=headers, timeout=10)
            if resp.status_code != 200:
                logger.error(f"ดึงโควต้าไม่สำเร็จ HTTP {resp.status_code}: {resp.text}")
                return None
            data = resp.json()
            logger.info(f"โควต้า LINE API: {data}")
            return data
        except Exception as e:
            logger.error(f"เกิดข้อผิดพลาดการดึงโควต้า: {e}")
            return None

    def get_consumption(self) -> Optional[Dict[str, Any]]:
        """
        ดึงจำนวนข้อความที่ส่งไปแล้วในเดือนนี้ (ใช้ผ่าน LINE Messaging API)
        :return: {"totalUsage": 5} หรือ None
        """
        if not self.channel_access_token:
            logger.debug("ไม่ได้ตั้งค่า LINE_CHANNEL_ACCESS_TOKEN ข้ามการตรวจการใช้ข้อความ")
            return None
        try:
            headers = {"Authorization": f"Bearer {self.channel_access_token}"}
            resp = requests.get(self.LINE_QUOTA_CONSUMPTION_URL, headers=headers, timeout=10)
            if resp.status_code != 200:
                logger.error(f"ดึงยอดใช้ข้อความไม่สำเร็จ HTTP {resp.status_code}: {resp.text}")
                return None
            data = resp.json()
            logger.info(f"ยอดใช้ข้อความ LINE API เดือนนี้: {data}")
            return data
        except Exception as e:
            logger.error(f"เกิดข้อผิดพลาดการดึงยอดใช้ข้อความ: {e}")
            return None


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

    def get_message_usage_summary(self) -> Optional[Dict[str, Any]]:
        """
        สรุปการใช้งานข้อความ LINE API ประจำเดือน (เฉพาะ LINE Messaging API)
        :return: dict เช่น {"type": "limited", "total": 200, "used": 5, "remaining": 195}
                 หรือ {"type": "none", "usage": 5} (แผนไม่มีวงเงิน)
                 หรือ None (ไม่มี Messaging API / เรียกไม่สำเร็จ)
        """
        quota = self.notifier.get_quota()
        usage = self.notifier.get_consumption()
        if quota is None or usage is None:
            return None

        used = int(usage.get("totalUsage", 0) or 0)
        if quota.get("type") == "none":
            return {"type": "none", "used": used}

        total = int(quota.get("value", 0) or 0)
        return {
            "type": "limited",
            "total": total,
            "used": used,
            "remaining": max(total - used, 0),
        }
