import sys
import datetime
from pathlib import Path
sys.path.append(str(Path("d:/BotAlert")))
from services.notifier import NotificationService

# ข้อความจำลอง Cross UP
msg_up = f'''🚀 [Live Signal] EMA Cross UP -> Uptrend / เทรนขาขึ้น 📈
============================
สัญลักษณ์: XAUUSDm (H1)
ราคาปิดล่าสุด: 2,520.50
สัญญาณ: EMA 50 (2515.20) ตัดขึ้นเหนือ EMA 150 (2510.30)
ระยะห่าง EMA: 4.90
🟢 แนวโน้ม: ขาขึ้น (Bullish Momentum)
เวลาแท่งเทียน: {datetime.datetime.now().strftime("%Y-%m-%d %H:00 น.")}
============================
⚠️ คำเตือน: โปรดพิจารณาโครงสร้างราคาและแนวรับแนวต้านร่วมด้วยก่อนออกออเดอร์'''

# ข้อความจำลอง Cross DOWN
msg_down = f'''🔻 [Live Signal] EMA Cross DOWN -> Downtrend / เทรนขาลง 📉
============================
สัญลักษณ์: XAUUSDm (H1)
ราคาปิดล่าสุด: 2,490.15
สัญญาณ: EMA 50 (2495.80) ตัดลงใต้ EMA 150 (2500.20)
ระยะห่าง EMA: 4.40
🔴 แนวโน้ม: ขาลง (Bearish Momentum)
เวลาแท่งเทียน: {datetime.datetime.now().strftime("%Y-%m-%d %H:00 น.")}
============================
⚠️ คำเตือน: โปรดพิจารณาโครงสร้างราคาและแนวรับแนวต้านร่วมด้วยก่อนออกออเดอร์'''

ns = NotificationService()
print("Sending test Cross UP...")
ns.send_live_ema_cross_alert(msg_up)
print("Sending test Cross DOWN...")
ns.send_live_ema_cross_alert(msg_down)
print("Done!")
