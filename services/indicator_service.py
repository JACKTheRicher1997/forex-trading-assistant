"""
Indicator Service Module
คำนวณ Exponential Moving Average (EMA 50 & EMA 150)
และตรวจจับสัญญาณการตัดกัน (Golden Cross / Death Cross)
พร้อมระบบป้องกันการแจ้งเตือนซ้ำต่อแท่งเทียน
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple
import datetime
import pandas as pd

from logger import get_logger
from config import config

logger = get_logger("IndicatorService")


class TrendState(Enum):
    BULLISH = "BULLISH"   # EMA 50 > EMA 150 (แนวโน้มขาขึ้น)
    BEARISH = "BEARISH"   # EMA 50 < EMA 150 (แนวโน้มขาลง)
    NEUTRAL = "NEUTRAL"   # เท่ากัน หรือยังไม่ชัดเจน


class CrossSignal(Enum):
    NONE = "NONE"
    CROSS_UP = "CROSS_UP"       # EMA 50 ตัดขึ้นเหนือ EMA 150 -> Uptrend / เทรนขาขึ้น
    CROSS_DOWN = "CROSS_DOWN"   # EMA 50 ตัดลงใต้ EMA 150 -> Downtrend / เทรนขาลง


@dataclass
class SignalResult:
    """ผลการวิเคราะห์อินดิเคเตอร์และสัญญาณเทรด"""
    symbol: str
    timeframe: str
    candle_time: datetime.datetime
    close_price: float
    ema_fast: float
    ema_slow: float
    trend: TrendState
    cross_signal: CrossSignal
    is_new_signal: bool = False  # เป็นสัญญาณใหม่ที่ยังไม่เคยแจ้งเตือนหรือไม่

    @property
    def is_bullish(self) -> bool:
        return self.trend == TrendState.BULLISH

    @property
    def is_bearish(self) -> bool:
        return self.trend == TrendState.BEARISH

    def format_line_alert_message(self) -> str:
        """
        จัดรูปแบบข้อความแจ้งเตือนเข้า LINE ทันทีเมื่อเกิดการตัดกัน
        """
        time_str = self.candle_time.strftime("%Y-%m-%d %H:%M น.")
        spread_ema = abs(self.ema_fast - self.ema_slow)

        if self.cross_signal == CrossSignal.CROSS_UP:
            header = "🚀 [Live Signal] EMA Cross UP -> Uptrend / เทรนขาขึ้น 📈"
            detail = f"EMA 50 ({self.ema_fast:.2f}) ตัดขึ้นเหนือ EMA 150 ({self.ema_slow:.2f})"
            sentiment = "🟢 แนวโน้ม: ขาขึ้น (Bullish Momentum)"
        elif self.cross_signal == CrossSignal.CROSS_DOWN:
            header = "🔻 [Live Signal] EMA Cross DOWN -> Downtrend / เทรนขาลง 📉"
            detail = f"EMA 50 ({self.ema_fast:.2f}) ตัดลงใต้ EMA 150 ({self.ema_slow:.2f})"
            sentiment = "🔴 แนวโน้ม: ขาลง (Bearish Momentum)"
        else:
            header = "📊 [Indicator Update] รายงานสถานะ EMA"
            detail = f"EMA 50: {self.ema_fast:.2f} | EMA 150: {self.ema_slow:.2f}"
            sentiment = f"สถานะ: {self.trend.value}"

        lines = [
            header,
            "=" * 28,
            f"สัญลักษณ์: {self.symbol} ({self.timeframe})",
            f"ราคาปิดล่าสุด: {self.close_price:,.2f}",
            f"สัญญาณ: {detail}",
            f"ระยะห่าง EMA: {spread_ema:.2f}",
            sentiment,
            f"เวลาแท่งเทียน: {time_str}",
            "=" * 28,
            "⚠️ คำเตือน: โปรดพิจารณาโครงสร้างราคาและแนวรับแนวต้านร่วมด้วยก่อนออกออเดอร์",
        ]
        return "\n".join(lines)


class IndicatorService:
    """
    คลาสสำหรับคำนวณ EMA และตรวจจับ Live Cross Signal
    มีระบบป้องกันการแจ้งเตือนซ้ำ (ส่งเพียงครั้งเดียวต่อการตัดกันในแท่งเทียนนั้นๆ)
    """

    def __init__(
        self,
        ema_fast_period: Optional[int] = None,
        ema_slow_period: Optional[int] = None,
    ):
        self.fast_period = ema_fast_period or config.indicator.ema_fast
        self.slow_period = ema_slow_period or config.indicator.ema_slow
        # เก็บ Timestamp ของแท่งเทียนที่เคยส่งสัญญาณไปแล้ว ป้องกันการส่งซ้ำ
        self._last_alerted_candle_time: Optional[datetime.datetime] = None
        self._last_alerted_signal_type: Optional[CrossSignal] = None

    def calculate_ema(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        คำนวณเส้น EMA 50 และ EMA 150 ลงใน DataFrame
        :param df: DataFrame แท่งเทียนที่มีคอลัมน์ close
        :return: DataFrame พร้อมคอลัมน์ ema_fast และ ema_slow
        """
        if df is None or len(df) < self.slow_period:
            logger.warning(
                f"จำนวนแท่งเทียนไม่เพียงพอสำหรับการคำนวณ EMA {self.slow_period} (มีเพียง {len(df) if df is not None else 0} แท่ง)"
            )
            return df

        df = df.copy()
        # คำนวณ Exponential Moving Average ตามมาตรฐานเทรด
        df[f"ema_{self.fast_period}"] = (
            df["close"].ewm(span=self.fast_period, adjust=False).mean()
        )
        df[f"ema_{self.slow_period}"] = (
            df["close"].ewm(span=self.slow_period, adjust=False).mean()
        )
        return df

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str = "XAUUSDm",
        timeframe: str = "H1",
    ) -> Optional[SignalResult]:
        """
        วิเคราะห์แท่งเทียนล่าสุดเพื่อตรวจจับการตัดกันของ EMA (Cross Detection)
        :param df: DataFrame แท่งเทียน
        :param symbol: สัญลักษณ์คู่เงิน
        :param timeframe: กรอบเวลา
        :return: SignalResult
        """
        if df is None or len(df) < self.slow_period + 2:
            return None

        df_calc = self.calculate_ema(df)
        fast_col = f"ema_{self.fast_period}"
        slow_col = f"ema_{self.slow_period}"

        # ตรวจสอบแท่งเทียนล่าสุด (index -1) และแท่งก่อนหน้า (index -2)
        curr_row = df_calc.iloc[-1]
        prev_row = df_calc.iloc[-2]

        curr_time = curr_row["time"]
        curr_close = float(curr_row["close"])
        curr_fast = float(curr_row[fast_col])
        curr_slow = float(curr_row[slow_col])

        prev_fast = float(prev_row[fast_col])
        prev_slow = float(prev_row[slow_col])

        # กำหนด Trend ปัจจุบัน
        if curr_fast > curr_slow:
            current_trend = TrendState.BULLISH
        elif curr_fast < curr_slow:
            current_trend = TrendState.BEARISH
        else:
            current_trend = TrendState.NEUTRAL

        # ตรวจสอบการตัดกัน (Cross Detection)
        cross_signal = CrossSignal.NONE

        # 1. EMA 50 ตัดขึ้นเหนือ EMA 150 (Golden Cross)
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            cross_signal = CrossSignal.CROSS_UP

        # 2. EMA 50 ตัดลงใต้ EMA 150 (Death Cross)
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            cross_signal = CrossSignal.CROSS_DOWN

        # ระบบป้องกันการแจ้งเตือนซ้ำ (ส่งเพียงครั้งเดียวต่อการตัดกันในแท่งเทียนนั้นๆ)
        is_new_signal = False
        if cross_signal != CrossSignal.NONE:
            # ตรวจสอบว่าเคยแจ้งเตือนในแท่งเทียนเวลานี้ไปแล้วหรือยัง
            if self._last_alerted_candle_time != curr_time or self._last_alerted_signal_type != cross_signal:
                is_new_signal = True
                self._last_alerted_candle_time = curr_time
                self._last_alerted_signal_type = cross_signal
                logger.info(
                    f"🔥 ตรวจพบสัญญาณ Live Cross ใหม่! {cross_signal.value} บน {symbol} {timeframe} เวลาแท่งเทียน: {curr_time}"
                )
            else:
                logger.debug(f"สัญญาณ {cross_signal.value} ในแท่งเทียน {curr_time} ถูกส่งแจ้งเตือนไปแล้ว (ข้ามการส่งซ้ำ)")

        return SignalResult(
            symbol=symbol,
            timeframe=timeframe,
            candle_time=curr_time,
            close_price=curr_close,
            ema_fast=curr_fast,
            ema_slow=curr_slow,
            trend=current_trend,
            cross_signal=cross_signal,
            is_new_signal=is_new_signal,
        )
