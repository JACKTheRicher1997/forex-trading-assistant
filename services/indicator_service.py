"""
Indicator Service Module
คำนวณ Exponential Moving Average (EMA 50 & EMA 150)
และตรวจจับสัญญาณการตัดกัน (Golden Cross / Death Cross)
พร้อมระบบป้องกันการแจ้งเตือนซ้ำต่อแท่งเทียน
"""

import json
import threading
import datetime
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import pandas as pd

from logger import get_logger
from config import config

logger = get_logger("IndicatorService")

# ---------------------------
# Persistent Cross State (dedup ข้ามรอบการทำงาน / ข้าม GH Actions run)
# เพราะ GitHub Actions สร้าง Process ใหม่ทุกครั้ง (5 นาที) หน่วยความจำในตัว
# IndicatorService จะรีเซ็ตทุก run -> ต้องเก็บสถานะ "แจ้งเตือนไปแล้ว" ไว้ในไฟล์
# เพื่อกันส่งซ้ำข้าม run และกันพลาดสัญญาณที่ถูกสแกนย้อนหลัง
# ---------------------------
_STATE_DIR = Path(__file__).resolve().parent.parent / "state"
_STATE_FILE = _STATE_DIR / "ema_cross_state.json"
_state_write_lock = threading.Lock()


def _to_aware_utc(ts) -> datetime.datetime:
    """แปลงเวลาให้เป็น timezone-aware UTC เสมอ เพื่อเปรียบเทียบกันได้อย่างถูต้อง"""
    if isinstance(ts, str):
        ts = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.timezone.utc)
    return ts.astimezone(datetime.timezone.utc)


def _load_cross_state() -> dict:
    """โหลดสถานะสัญญาณที่เคยแจ้งเตือนไปแล้วจากไฟล์ state"""
    try:
        if _STATE_FILE.exists():
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries", {})
            if isinstance(entries, dict):
                return entries
    except Exception as e:
        logger.warning(f"ไม่สามารถอ่านไฟล์ state EMA Cross ได้ (จะเริ่มจากสถานะว่าง): {e}")
    return {}


def _save_cross_state(entries_to_update: dict) -> None:
    """อัปเดตสถานะสัญญาณที่แจ้งเตือนแล้วลงไฟล์ state (merge กับข้อมูลเดิม)"""
    with _state_write_lock:
        try:
            _STATE_DIR.mkdir(parents=True, exist_ok=True)
            disk = _load_cross_state()
            disk.update(entries_to_update)
            with open(_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "entries": disk}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"ไม่สามารถบันทึกไฟล์ state EMA Cross ได้: {e}")


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

    def _format_candle_time_thai(self) -> str:
        """แปลงเวลาแท่งเทียนเป็นเวลาไทย (ICT UTC+7) สำหรับแสดงในข้อความ LINE"""
        ts = self.candle_time
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.timezone.utc)
        utc_ts = ts.astimezone(datetime.timezone.utc)
        bangkok_ts = utc_ts + datetime.timedelta(hours=7)
        return bangkok_ts.strftime("%Y-%m-%d %H:%M น.")

    def format_line_alert_message(self) -> str:
        """
        จัดรูปแบบข้อความแจ้งเตือนเข้า LINE ทันทีเมื่อเกิดการตัดกัน
        """
        time_str = self._format_candle_time_thai()
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

    # ------------------------------------------------------------------
    # analyze(): สำหรับ Dashboard ยังคงเดิม — แสดงสถานะล่าสุดของแท่งเทียนล่าสุด
    # ------------------------------------------------------------------
    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str = "XAUUSDm",
        timeframe: str = "H1",
    ) -> Optional[SignalResult]:
        """
        วิเคราะห์แท่งเทียนล่าสุดเพื่อตรวจจับการตัดกันของ EMA (Cross Detection)
        ใช้สำหรับ Dashboard — แสดงสถานะล่าสุดของแท่งเทียนล่าสุดเท่านั้น
        """
        if df is None or len(df) < self.slow_period + 2:
            return None

        df_calc = self.calculate_ema(df)
        fast_col = f"ema_{self.fast_period}"
        slow_col = f"ema_{self.slow_period}"

        curr_row = df_calc.iloc[-1]
        prev_row = df_calc.iloc[-2]

        curr_time = curr_row["time"]
        curr_close = float(curr_row["close"])
        curr_fast = float(curr_row[fast_col])
        curr_slow = float(curr_row[slow_col])
        prev_fast = float(prev_row[fast_col])
        prev_slow = float(prev_row[slow_col])

        if curr_fast > curr_slow:
            current_trend = TrendState.BULLISH
        elif curr_fast < curr_slow:
            current_trend = TrendState.BEARISH
        else:
            current_trend = TrendState.NEUTRAL

        cross_signal = CrossSignal.NONE
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            cross_signal = CrossSignal.CROSS_UP
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            cross_signal = CrossSignal.CROSS_DOWN

        is_new_signal = False
        if cross_signal != CrossSignal.NONE:
            if self._last_alerted_candle_time != curr_time or self._last_alerted_signal_type != cross_signal:
                is_new_signal = True
                self._last_alerted_candle_time = curr_time
                self._last_alerted_signal_type = cross_signal
            else:
                logger.debug(f"สัญญาณ {cross_signal.value} ในแท่งเทียน {curr_time} ถูกส่งแจ้งเตือนไปแล้ว")

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

    # ------------------------------------------------------------------
    # analyze_live_crosses(): สำหรับ GH Actions / Live Alert
    # - สแกนทุกแท่งเทียนที่ดึงมา (ต้องใช้ history เยอะ ~800 แท่ง ให้ EMA ล็อกเข้ารูป)
    # - คืนค่า Cross ใหม่ทั้งหมด (ทุกครั้งที่ EMA50 ตัด EMA150) ไม่ใช่แค่ครั้งล่าสุด
    # - ใช้ไฟล์ state ข้าม run กันส่งซ้ำ (แจ้งครั้งเดียวต่อแท่ง Cross)
    # - แจ้งเตือนด้วยค่า ณ ตอนเกิด Cross (ไม่ใช่แท่งล่าสุด)
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_alerted_set(record) -> set:
        """แปลง state record เป็น set ของ (candle_time_iso, signal)"""
        result = set()
        if not isinstance(record, dict):
            return result
        entries = record.get("alerted")
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and e.get("candle_time") and e.get("signal"):
                    result.add((str(e["candle_time"]), str(e["signal"])))
        elif record.get("candle_time"):  # รูปแบบเก่า -> แปลงเป็นรายการเดียว
            result.add((str(record["candle_time"]), str(record.get("signal", ""))))
        return result

    @staticmethod
    def _prune_alerted(entries: list, now_utc: datetime.datetime) -> list:
        """ตัดรายการที่แจ้งนานเกิน 3 วันแล้วออก กัน state โตเกินจำเป็น"""
        cutoff = now_utc - datetime.timedelta(days=3)
        out = []
        for e in entries:
            try:
                if _to_aware_utc(e.get("candle_time")) >= cutoff:
                    out.append(e)
            except Exception:
                continue
        return out

    def analyze_live_crosses(
        self,
        df: pd.DataFrame,
        symbol: str = "XAUUSDm",
        timeframe: str = "M5",
    ) -> list:
        """
        สแกนแท่งเทียนทั้งหมด แล้วคืนค่า Cross ใหม่ทุกรายการที่ยังไม่เคยแจ้ง
        (แจ้งครบทุกครั้งที่ EMA50 ตัด EMA150 ตลอดวัน — ไม่ใช่แค่ครั้งล่าสุด)
        :return: List[SignalResult] เรียงตามเวลาก่อน -> หลัง
        """
        if df is None or len(df) < self.slow_period + 2:
            return []

        df_calc = self.calculate_ema(df)
        fast_col = f"ema_{self.fast_period}"
        slow_col = f"ema_{self.slow_period}"

        fast = df_calc[fast_col].astype(float)
        slow = df_calc[slow_col].astype(float)
        bullish = fast > slow

        # สแกนหา Cross ทุกจุดที่มีสัญญาณเปลี่ยน (เรียงเวลาขึ้นเรื่อย ๆ ตามลำดับ)
        crosses = []
        prev_is_bull = bool(bullish.iloc[0])
        for i in range(1, len(df_calc)):
            cur_is_bull = bool(bullish.iloc[i])
            if cur_is_bull != prev_is_bull:
                crosses.append((i, CrossSignal.CROSS_UP if cur_is_bull else CrossSignal.CROSS_DOWN))
            prev_is_bull = cur_is_bull

        if not crosses:
            return []

        # -----------------------------------------------------------
        # Persistent dedup (กันส่งซ้ำข้าม run / ข้าม process)
        # -----------------------------------------------------------
        state_key = f"{symbol}::{timeframe}"
        state_entries = _load_cross_state()
        record = state_entries.get(state_key)
        alerted_set = self._parse_alerted_set(record)

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        twenty4h_ago = now_utc - datetime.timedelta(hours=24)

        results = []          # Cross ใหม่ที่จะแจ้ง (เรียงเวลาก่อน->หลัง)
        new_entries = []      # รายการ (candle_time_iso, signal) ที่แจ้งไปแล้วรอบนี้

        for idx, cross_signal in crosses:
            cross_row = df_calc.iloc[idx]
            cross_time = cross_row["time"]
            cross_utc = _to_aware_utc(cross_time)

            # แจ้งเฉพาะ Cross ที่เพิ่งเกิด (~24 ชม.) ป้องกัน replay ย้อนหลังไกล ๆ
            if cross_utc < twenty4h_ago:
                continue

            entry_id = (cross_utc.isoformat(), cross_signal.value)
            if entry_id in alerted_set:
                continue  # เคยแจ้งแล้ว

            results.append(SignalResult(
                symbol=symbol,
                timeframe=timeframe,
                candle_time=cross_time,
                close_price=float(cross_row["close"]),
                ema_fast=float(cross_row[fast_col]),
                ema_slow=float(cross_row[slow_col]),
                trend=(
                    TrendState.BULLISH if float(cross_row[fast_col]) > float(cross_row[slow_col])
                    else TrendState.BEARISH if float(cross_row[fast_col]) < float(cross_row[slow_col])
                    else TrendState.NEUTRAL
                ),
                cross_signal=cross_signal,
                is_new_signal=True,
            ))
            new_entries.append({"candle_time": cross_utc.isoformat(), "signal": cross_signal.value})

        # บันทึก state ถ้ามี Cross ใหม่
        if new_entries:
            existing_entries = record.get("alerted") if isinstance(record, dict) and isinstance(record.get("alerted"), list) else []
            # ถ้า record เป็นรูปแบบเก่าให้เริ่มจากรายการเดียว
            if not existing_entries and isinstance(record, dict) and record.get("candle_time"):
                existing_entries = [{"candle_time": record["candle_time"], "signal": record.get("signal", "")}]
            merged = existing_entries + new_entries
            merged = self._prune_alerted(merged, now_utc)
            _save_cross_state({
                state_key: {
                    "alerted": merged,
                    "updated_at": now_utc.isoformat(),
                }
            })
            # อัปเดตหน่วยความจำ (กันส่งซ้ำใน process เดียวกันด้วย)
            latest_idx, latest_signal = crosses[-1]
            self._last_alerted_candle_time = df_calc.iloc[latest_idx]["time"]
            self._last_alerted_signal_type = latest_signal
            for r in results:
                logger.info(
                    f"🔥 ตรวจพบสัญญาณ Live Cross ใหม่! {r.cross_signal.value} บน "
                    f"{symbol} {timeframe} เวลาแท่งเทียน: {r.candle_time}"
                )

        return results
