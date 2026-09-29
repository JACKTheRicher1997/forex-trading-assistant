"""
Indicator Service Module
คำนวณ Exponential Moving Average (EMA 50 & EMA 150)
ตรวจจับสัญญาณการตัดกัน (Golden Cross / Death Cross)
คำนวณ RSI (Relative Strength Index) และ Divergence
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

    def calculate_rsi_series(self, closes, period: int = 14) -> list:
        """
        คำนวณ RSI แบบ Wilder's Smoothing (มาตรฐานเดียวกับ TradingView)
        :param closes: รายการราคาปิดเรียงจากเก่าไปใหม่
        :return: รายการ RSI ความยาวเท่ากับ closes (ค่าต้นยังเป็น None)
        """
        values = [float(c) for c in closes]
        out = [None] * len(values)
        if period <= 0 or len(values) <= period:
            return out

        gains, losses = [], []
        for i in range(1, len(values)):
            diff = values[i] - values[i - 1]
            gains.append(max(diff, 0.0))
            losses.append(max(-diff, 0.0))

        # ค่าเฉลี่ยเริ่มต้น = ค่าเฉลี่ยเคลื่อนที่ของ period แท่งแรก
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        out[period] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = (avg_gain / avg_loss) if avg_loss else None
            out[i + 1] = 100.0 if rs is None else 100.0 - (100.0 / (1.0 + rs))
        return out

    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> Optional[float]:
        """คำนวณค่า RSI ล่าสุด (คืน None ถ้าข้อมูลไม่พอ)"""
        if df is None or len(df) <= period:
            return None
        series = self.calculate_rsi_series(df["close"].tolist(), period)
        return series[-1] if series else None

    def compute_rsi_divergence(
        self,
        df: pd.DataFrame,
        rsi_period: int = 14,
        lookback: int = 60,
        pivot_window: int = 2,
    ) -> dict:
        """
        ตรวจ RSI Divergence จากจุดสูงสุด/ต่ำสุดเชิงโครงสร้าง (swing pivot)
        - Bearish Divergence: ราคาทำจุดสูงใหม่ แต่ RSI ทำจุดสูงต่ำกว่า -> แนวโน้มอ่อน
        - Bullish Divergence: ราคาทำจุดต่ำใหม่ แต่ RSI ทำจุดต่ำสูงกว่า -> แนวโน้มฟื้น
        :return: dict พร้อม type/ราคา/RSI ของจุดทั้งสองและคำแนะนำ
        """
        empty = {
            "type": None, "rsi": None, "price1": None, "rsi1": None,
            "price2": None, "rsi2": None, "note": "", "bars": 0,
        }
        if df is None or len(df) < rsi_period + pivot_window * 2 + 5:
            return empty

        closes = [float(c) for c in df["close"].tolist()]
        rsi_series = self.calculate_rsi_series(closes, rsi_period)
        window = min(lookback, len(closes))
        c_win = closes[-window:]
        r_win = rsi_series[-window:]

        start = 0
        while start < len(r_win) and r_win[start] is None:
            start += 1
        if len(r_win) - start < pivot_window * 2 + 3:
            return empty

        piv_hi, piv_lo = [], []
        for i in range(pivot_window, len(c_win) - pivot_window):
            seg_c = c_win[i - pivot_window: i + pivot_window + 1]
            seg_r = [
                v for v in r_win[i - pivot_window: i + pivot_window + 1] if v is not None
            ]
            if not seg_r:
                continue
            # จุดสูงสุด/ต่ำสุดเฉพาะแท่งนั้น (ไม่มีแท่งอื่นเท่ากัน)
            if c_win[i] == max(seg_c) and seg_c.count(c_win[i]) == 1 and r_win[i] is not None:
                piv_hi.append((i, c_win[i], r_win[i]))
            if c_win[i] == min(seg_c) and seg_c.count(c_win[i]) == 1 and r_win[i] is not None:
                piv_lo.append((i, c_win[i], r_win[i]))

        # กรองจุดสูง/ต่ำที่ "สำคัญ" เท่านั้น เพื่อไม่ให้จับการแกว่งเล็ก ๆ เป็นจุดเทียบ
        min_gap = max(3, pivot_window * 2 + 1)
        sig_hi = self._significant_pivots(piv_hi, min_gap, higher=True)
        sig_lo = self._significant_pivots(piv_lo, min_gap, higher=False)

        result = dict(empty)
        result["rsi"] = rsi_series[-1]
        result["bars"] = window

        if len(sig_hi) >= 2:
            (_, p1, r1), (_, p2, r2) = sig_hi[-2], sig_hi[-1]
            if p2 > p1 and r2 < r1:
                result.update({
                    "type": "BEARISH", "price1": p1, "rsi1": r1, "price2": p2, "rsi2": r2,
                    "note": (
                        f'ราคาทำจุดสูงใหม่ ({p1:,.2f} → {p2:,.2f}) แต่ RSI อ่อนลง '
                        f'({r1:.1f} → {r2:.1f}) — โมเมนตัมกำลังหมด ระวังกลับตัว'
                    ),
                })
                return result
        if len(sig_lo) >= 2:
            (_, p1, r1), (_, p2, r2) = sig_lo[-2], sig_lo[-1]
            if p2 < p1 and r2 > r1:
                result.update({
                    "type": "BULLISH", "price1": p1, "rsi1": r1, "price2": p2, "rsi2": r2,
                    "note": (
                        f'ราคาทำจุดต่ำใหม่ ({p1:,.2f} → {p2:,.2f}) แต่ RSI แข็งขึ้น '
                        f'({r1:.1f} → {r2:.1f}) — โมเมนตัมกำลังฟื้น มองหาจังหวะกลับตัว'
                    ),
                })
                return result

        result["note"] = "ยังไม่พบ RSI Divergence ที่ชัดเจนในช่วงข้อมูลล่าสุด"
        return result

    @staticmethod
    def _significant_pivots(pivots: list, min_gap: int, higher: bool) -> list:
        """
        คัดเฉพาะจุดสูง/ต่ำที่มีนัยสำคัญ (ห่างกันอย่างน้อย min_gap แท่ง)
        โดยเดินจากแท่งล่าสุดย้อนกลับ และเลือกตัวที่ "รุนแรง" ที่สุดในช่วงนั้น
        :param pivots: รายการ (index, ราคา, rsi) เรียงตามเวลา
        :param higher: True = จุดสูง, False = จุดต่ำ
        """
        kept: list = []
        for item in reversed(pivots):
            if not kept or (kept[-1][0] - item[0]) >= min_gap:
                kept.append(item)
                continue
            # ห่างกันน้อยเกินไป -> เก็บตัวที่ extreme กว่าไว้แทน
            prev = kept[-1]
            more_extreme = item[1] > prev[1] if higher else item[1] < prev[1]
            if more_extreme:
                kept[-1] = item
        return list(reversed(kept))

    # ------------------------------------------------------------------
    def _advance_last_cross(self, state_key: str, record, new_time, new_signal) -> Optional[dict]:
        """
        เลื่อน "เข็ม" last_cross ในฐานข้อมูลสัญญาณไปที่ EMA Cross ครั้งล่าสุด
        (บันทึกถาวร ไม่ prune ตาม 24 ชม. — เพื่อบอกเวลาครั้งล่าสุดได้ทุกไทม์เฟรม)
        :return: dict ใหม่ที่บันทึกลง state หรือ None ถ้าไม่มีอะไรใหม่กว่าเดิม
        """
        old_last = record.get("last_cross") if isinstance(record, dict) else None
        new_lc = {"candle_time": _to_aware_utc(new_time).isoformat(), "signal": new_signal}
        if old_last is not None:
            try:
                if _to_aware_utc(old_last["candle_time"]) >= _to_aware_utc(new_time):
                    return None
            except Exception:
                pass
        merged = dict(record) if isinstance(record, dict) else {}
        merged["last_cross"] = new_lc
        merged["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _save_cross_state({state_key: merged})
        return new_lc

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

        curr_time = curr_row["time"]
        curr_close = float(curr_row["close"])
        curr_fast = float(curr_row[fast_col])
        curr_slow = float(curr_row[slow_col])

        if curr_fast > curr_slow:
            current_trend = TrendState.BULLISH
        elif curr_fast < curr_slow:
            current_trend = TrendState.BEARISH
        else:
            current_trend = TrendState.NEUTRAL

        # หา Cross ล่าสุดภายในหน้าต่างข้อมูลทั้งหมด (ไม่ใช่แค่แท่งสุดท้าย)
        # เพื่อให้ Dashboard แสดง "สัญญาณล่าสุด" ตรงกับความเป็นจริงจนกว่าจะมี Cross ใหม่
        # และไม่ให้สัญญาณหายไปเมื่อ Cross เก่านานกว่า 300 แท่ง (เช่น M5 ~25 ชม.)
        last_cross_signal = CrossSignal.NONE
        last_cross_time = None
        fast_arr = df_calc[fast_col].astype(float)
        slow_arr = df_calc[slow_col].astype(float)
        prev_is_bull = bool(fast_arr.iloc[0] > slow_arr.iloc[0])
        for i in range(1, len(df_calc)):
            cur_is_bull = bool(fast_arr.iloc[i] > slow_arr.iloc[i])
            if cur_is_bull != prev_is_bull:
                last_cross_signal = CrossSignal.CROSS_UP if cur_is_bull else CrossSignal.CROSS_DOWN
                last_cross_time = df_calc.iloc[i]["time"]
            prev_is_bull = cur_is_bull

        cross_signal = last_cross_signal
        cross_time_for_result = last_cross_time if last_cross_time is not None else curr_time

        # เลื่อนเข็ม last_cross (ครั้งล่าสุดที่เกิด Cross) ลงฐานข้อมูลสัญญาณ
        # เพื่อให้ทุกไทม์เฟรมบนหน้า Dashboard บอกเวลาที่ตัดกันล่าสุดได้
        # แม้ Cross จะเก่ากว่าช่วงข้อมูลที่แสดงอยู่ (สแกนจากหน้าต่างข้อมูลเต็ม 800 แท่ง)
        if last_cross_signal != CrossSignal.NONE:
            _state_key = f"{symbol}::{timeframe}"
            _st_entries = _load_cross_state()
            self._advance_last_cross(_state_key, _st_entries.get(_state_key), last_cross_time, last_cross_signal.value)

        is_new_signal = False
        if cross_signal != CrossSignal.NONE:
            if (
                self._last_alerted_candle_time != cross_time_for_result
                or self._last_alerted_signal_type != cross_signal
            ):
                is_new_signal = True
                self._last_alerted_candle_time = cross_time_for_result
                self._last_alerted_signal_type = cross_signal
            else:
                logger.debug(f"สัญญาณ {cross_signal.value} ในแท่งเทียน {cross_time_for_result} ถูกส่งแจ้งเตือนไปแล้ว")

        return SignalResult(
            symbol=symbol,
            timeframe=timeframe,
            candle_time=cross_time_for_result,
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
    # - แจ้งเฉพาะ "Cross ใหม่ล่าสุด" ที่เกิดหลัง anchor ตัวเดียว กันข้อความท่วมเป็นชุด
    # - บันทึก Cross ที่พบทั้งหมดลงไฟล์ state (ข้ามช่วงที่ bot หยุด) ไม่เท replay ย้อนหลัง
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
        """ตัดรายการที่แจ้งนานเกิน 3 วันออกแล้ว กัน state โตเกินจำเป็น"""
        cutoff = now_utc - datetime.timedelta(days=3)
        out = []
        for e in entries:
            try:
                if _to_aware_utc(e.get("candle_time")) >= cutoff:
                    out.append(e)
            except Exception:
                continue
        return out

    @staticmethod
    def _get_last_alerted_time(record) -> Optional[datetime.datetime]:
        """อ่านเวลาแท่งเทียนล่าสุดที่เคยแจ้งเตือน (anchor) จาก state"""
        if not isinstance(record, dict):
            return None
        entries = record.get("alerted")
        times = []
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and e.get("candle_time"):
                    times.append(e["candle_time"])
        elif record.get("candle_time"):
            times.append(record["candle_time"])
        if not times:
            return None
        aware = []
        for t in times:
            try:
                aware.append(_to_aware_utc(t))
            except Exception:
                continue
        return max(aware) if aware else None

    def analyze_live_crosses(
        self,
        df: pd.DataFrame,
        symbol: str = "XAUUSDm",
        timeframe: str = "M5",
    ) -> list:
        """
        สแกนแท่งเทียนทั้งหมด แล้วคืนค่า Cross ใหม่ล่าสุดที่ยังไม่เคยแจ้ง
        (แจ้งครั้งละ 1 รายการเท่านั้น — Cross ล่าสุด เพื่อกันข้อความท่วมเป็นชุด)
        :return: List[SignalResult] อย่างมาก 1 รายการ (Cross ล่าสุด)
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

        # ----------------------------------------------------------
        # บันทึก EMA Cross "ครั้งล่าสุด" แบบถาวร (เข็มนาฬิกาไว้บอกเวลาที่เคยเกิด Cross)
        # ต่างจากรายการ `alerted` ที่ prune เหลือแค่ 24 ชม. — อันนี้เก็บไว้ตลอด
        # เพื่อให้หน้า Dashboard ย้อนบอกเวลาครั้งล่าสุดได้ทุกไทม์เฟรม (M5/M15/M30/H1/H4/D1)
        # ----------------------------------------------------------
        _last_idx, _last_sig = crosses[-1]
        _last_cross_time = _to_aware_utc(df_calc.iloc[_last_idx]["time"])
        _old_last_cross = record.get("last_cross") if isinstance(record, dict) else None
        # เลื่อนเข็ม last_cross ไปครั้งล่าสุด (บันทึกลง state ทันที ไม่รอให้ผ่าน 24 ชม.)
        new_last_cross = self._advance_last_cross(state_key, record, _last_cross_time, _last_sig.value)
        _last_cross_changed = new_last_cross is not None
        if not _last_cross_changed:
            new_last_cross = _old_last_cross

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        twenty4h_ago = now_utc - datetime.timedelta(hours=24)

        # anchor = เวลา Cross ล่าสุดที่เคยแจ้งเตือน/บันทึกไว้แล้ว
        last_alerted_time = self._get_last_alerted_time(record)

        # รวบรวมเฉพาะ Cross ที่เกิดใหม่จริง ๆ หลัง anchor (ไม่เท replay ย้อนหลัง)
        candidates = []
        for idx, cross_signal in crosses:
            cross_row = df_calc.iloc[idx]
            cross_time = cross_row["time"]
            cross_utc = _to_aware_utc(cross_time)

            # พิจารณาเฉพาะ Cross ที่เพิ่งเกิด (~24 ชม.) ป้องกัน replay ไกล ๆ
            if cross_utc < twenty4h_ago:
                continue
            # ข้าม Cross ที่เก่ากว่าหรือเท่ากับ anchor (แจ้ง/บันทึกไปแล้ว)
            if last_alerted_time is not None and cross_utc <= last_alerted_time:
                continue
            entry_id = (cross_utc.isoformat(), cross_signal.value)
            if entry_id in alerted_set:
                continue

            candidates.append(SignalResult(
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
                is_new_signal=False,
            ))

        if not candidates:
            # ไม่พบ Cross ใหม่ในช่วง 24 ชม. (เข็ม last_cross อัปเดตไปแล้วข้างบนถ้ามีใหม่)
            return []

        # บันทึก Cross ที่พบทั้งหมดลง state (เลื่อน anchor ข้ามช่วงที่ bot หยุด)
        # แล้วแจ้งเฉพาะ Cross "ใหม่ล่าสุด" ตัวเดียว กันข้อความท่วมเป็นชุด (burst)
        new_entries = [
            {"candle_time": _to_aware_utc(r.candle_time).isoformat(), "signal": r.cross_signal.value}
            for r in candidates
        ]
        existing_entries = record.get("alerted") if isinstance(record, dict) and isinstance(record.get("alerted"), list) else []
        # ถ้า record เป็นรูปแบบเก่าให้เริ่มจากรายการเดียว
        if not existing_entries and isinstance(record, dict) and record.get("candle_time"):
            existing_entries = [{"candle_time": record["candle_time"], "signal": record.get("signal", "")}]
        merged = existing_entries + new_entries
        merged = self._prune_alerted(merged, now_utc)
        _save_cross_state({
            state_key: {
                "alerted": merged,
                "last_cross": new_last_cross if _last_cross_changed else _old_last_cross,
                "updated_at": now_utc.isoformat(),
            }
        })

        # อัปเดตหน่วยความจำ (กันส่งซ้ำใน process เดียวกันด้วย)
        self._last_alerted_candle_time = _to_aware_utc(candidates[-1].candle_time)
        self._last_alerted_signal_type = candidates[-1].cross_signal

        # ยังไม่มีประวัติ anchor มาก่อน -> ตั้ง baseline ครั้งแรก โดยบันทึกแต่ไม่ส่ง
        # (กันเท Cross ย้อนหลังมาแจ้งเป็นชุดตอนติดตั้งใหม่ / เปลี่ยนแหล่งข้อมูล)
        if last_alerted_time is None:
            logger.info(
                f"📋 ตั้ง baseline EMA Cross ({symbol} {timeframe}): "
                f"บันทึก {len(candidates)} สัญญาณย้อนหลัง โดยไม่ส่งแจ้งเตือน"
            )
            return []

        # แจ้งเฉพาะ Cross ใหม่ล่าสุดตัวเดียวเท่านั้น
        results = [candidates[-1]]
        results[0].is_new_signal = True
        if len(candidates) > 1:
            logger.info(
                f"⏸️ ข้าม Cross เก่ากว่า {len(candidates) - 1} รายการ "
                f"(บันทึก baseline) เพื่อไม่ให้ข้อความท่วมเป็นชุด"
            )
        return results
