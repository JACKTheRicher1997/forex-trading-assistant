"""
TwelveData Price Service - Real Spot Price (XAU/USD)
ดึงข้อมูลราคาทองคำแบบ Spot (XAU/USD) จาก TwelveData API
ตรงกับ MT5/Exness มากกว่า Yahoo Finance (GC=F Futures)

การสมัคร: https://twelvedata.com (Free plan 800 requests/day)
Free plan: 8 requests/นาที, 800 requests/วัน -> เพียงพอสำหรับ GH Actions ทุก 5 นาที (288/day)

ข้อจำกัด Free tier:
- ข้อมูลมี delay เล็กน้อย (ไม่ใช่ tick-by-tick)
"""

from typing import Optional
import datetime
import requests
import pandas as pd

from logger import get_logger
from config import config

logger = get_logger("PriceService")

BASE_URL = "https://api.twelvedata.com/time_series"

# Symbol Mapping: แปลงสัญลักษณ์ MT5 เป็น TwelveData Symbol (Forex/Spot)
SYMBOL_MAP = {
    "XAUUSD": "XAU/USD",   # Gold Spot
    "XAUUSDm": "XAU/USD",  # Gold Spot (Exness suffix)
    "XAUUSDM": "XAU/USD",  # Gold Spot (Exness suffix uppercase)
    "EURUSD": "EUR/USD",
    "EURUSDm": "EUR/USD",
    "EURUSDM": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "GBPUSDm": "GBP/USD",
    "GBPUSDM": "GBP/USD",
    "USDJPY": "USD/JPY",
    "USDJPYm": "USD/JPY",
    "USDJPYM": "USD/JPY",
    "USDCHF": "USD/CHF",
    "USDCHFm": "USD/CHF",
    "USDCHFM": "USD/CHF",
    "AUDUSD": "AUD/USD",
    "AUDUSDm": "AUD/USD",
    "AUDUSDM": "AUD/USD",
    "NZDUSD": "NZD/USD",
    "NZDUSDm": "NZD/USD",
    "NZDUSDM": "NZD/USD",
    "USDCAD": "USD/CAD",
    "USDCADm": "USD/CAD",
    "USDCADM": "USD/CAD",
    "BTCUSD": "BTC/USD",
    "BTCUSDm": "BTC/USD",
    "BTCUSDM": "BTC/USD",
    "ETHUSD": "ETH/USD",
    "ETHUSDm": "ETH/USD",
    "ETHUSDM": "ETH/USD",
}

# Timeframe Mapping: แปลง Timeframe MT5 เป็น TwelveData Interval
TIMEFRAME_MAP = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
    "D1": "1day",
}


class TwelveDataPriceService:
    """
    คลาสสำหรับดึงข้อมูลราคา Spot จาก TwelveData API
    หน้า API เหมือน PriceService (connect, get_rates, shutdown) เพื่อสลับใช้งานได้ทันที

    ข้อจำกัด:
    - ต้องมี TWELVEDATA_API_KEY (สมัครฟรีที่ twelvedata.com)
    - Free plan 800 requests/วัน, 8 requests/นาที
    - ข้อมูลมี delay เล็กน้อย (ไม่ใช่ tick-by-tick)
    """

    def __init__(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ):
        self.symbol = (symbol or config.mt5.symbol).upper()
        self.timeframe_str = (timeframe or config.mt5.timeframe).upper()
        self.tw_symbol = SYMBOL_MAP.get(self.symbol, self.symbol)
        self.interval = TIMEFRAME_MAP.get(self.timeframe_str, "5min")
        self.api_key = config.twelvedata_api_key
        self.is_connected = False
        logger.info(
            f"TwelveDataPriceService initialized: {self.tw_symbol} ({self.timeframe_str} -> {self.interval})"
        )

    def _fetch(self, tw_symbol: str, interval: str, outputsize: int) -> Optional[pd.DataFrame]:
        """ดึงข้อมูลแท่งเทียนจาก TwelveData API"""
        try:
            params = {
                "symbol": tw_symbol,
                "interval": interval,
                "outputsize": outputsize,
                "apikey": self.api_key,
                # ขอเป็น UTC (เวลาใน DataFrame จะเป็น timezone-aware UTC
                # ระบบตรวจ EMA / แจ้งเตือนแปลงเป็นเวลาไทย (ICT) ให้อัตโนมัติ)
                "timezone": "UTC",
                "dp": "3",  # ทศนิยม 3 ตำแหน่ง (เหมาะกับทอง USD)
            }
            resp = requests.get(BASE_URL, params=params, timeout=15)
            data = resp.json()

            if data.get("status") != "ok":
                code = data.get("code", "")
                message = data.get("message", "")
                logger.error(f"TwelveData API error (code={code}): {message}")
                return None

            values = data.get("values") or []
            if not values:
                logger.error(f"TwelveData ไม่มีข้อมูลแท่งเทียนสำหรับ {tw_symbol} ({interval})")
                return None

            rows = []
            for row in values:
                try:
                    ts = pd.to_datetime(row["datetime"], utc=True)
                    rows.append({
                        "time": ts,
                        "open": float(row.get("open", 0.0)),
                        "high": float(row.get("high", 0.0)),
                        "low": float(row.get("low", 0.0)),
                        "close": float(row.get("close", 0.0)),
                        "tick_volume": float(row.get("volume", 0.0) or 0.0),
                    })
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(f"ข้ามข้อมูลแถวที่ผิดปกติ (TwelveData): {row} -> {e}")

            if not rows:
                logger.error(f"TwelveData แปลงข้อมูลไม่สำเร็จสำหรับ {tw_symbol}")
                return None

            df = pd.DataFrame(rows)
            # เรียงลำดับจากอดีตไปปัจจุบัน
            df.sort_values("time", ascending=True, inplace=True)
            df.reset_index(drop=True, inplace=True)
            return df

        except requests.RequestException as e:
            logger.error(f"เชื่อมต่อ TwelveData ไม่สำเร็จ: {e}")
            return None
        except ValueError as e:
            logger.error(f"ตอบกลับจาก TwelveData ไม่ใช่ JSON ที่ถูกต้อง: {e}")
            return None

    def connect(self) -> bool:
        """ตรวจสอบ API key และการเชื่อมต่อ"""
        if not self.api_key:
            logger.error("❌ TwelveData ต้องตั้งค่า TWELVEDATA_API_KEY ก่อน (ดู .env.example)")
            return False
        try:
            # ทดสอบดึงข้อมูลเล็กน้อย (outputsize=1) กันเปลืองโควต้า
            df = self._fetch(self.tw_symbol, self.interval, outputsize=1)
            self.is_connected = df is not None and len(df) > 0
            if self.is_connected:
                logger.info(f"✅ เชื่อมต่อ TwelveData สำเร็จ! Symbol: {self.tw_symbol}")
            else:
                logger.error(f"❌ เชื่อมต่อ TwelveData ล้มเหลว (id: {self.tw_symbol})")
            return self.is_connected
        except Exception as e:
            logger.error(f"❌ เชื่อมต่อ TwelveData ล้มเหลว: {e}")
            self.is_connected = False
            return False

    def check_connection(self) -> bool:
        """ตรวจสอบการเชื่อมต่อ"""
        return self.is_connected

    def get_rates(
        self,
        symbol: Optional[str] = None,
        timeframe_str: Optional[str] = None,
        count: int = 300,
    ) -> Optional[pd.DataFrame]:
        """
        ดึงข้อมูลแท่งเทียนย้อนหลัง (Rates OHLCV)
        :param symbol: สัญลักษณ์คู่เงิน (เช่น XAUUSDm, EURUSD)
        :param timeframe_str: Timeframe เช่น M5, H1
        :param count: จำนวนแท่งเทียนที่ต้องการ (TwelveData รองรับสูงสุด 800)
        :return: pandas.DataFrame ที่มีคอลัมน์ time, open, high, low, close, tick_volume
        """
        if not self.api_key:
            logger.error("TwelveData ต้องตั้งค่า TWELVEDATA_API_KEY ก่อน")
            return None

        sym = (symbol or self.symbol).upper()
        tf_str = (timeframe_str or self.timeframe_str).upper()

        # แปลง symbol และ timeframe
        tw_sym = SYMBOL_MAP.get(sym, sym)
        interval = TIMEFRAME_MAP.get(tf_str, "5min")

        outputsize = min(count, 800)
        logger.info(f"กำลังดึงข้อมูลแท่งเทียน: {tw_sym} ({interval}, outputsize={outputsize})...")

        df = self._fetch(tw_sym, interval, outputsize)
        if df is None or len(df) == 0:
            logger.error(f"ไม่สามารถดึงแท่งเทียนสำหรับ {tw_sym} ({interval}) ได้")
            return None

        # จำกัดจำนวน rows ตาม count
        if len(df) > count:
            df = df.tail(count).reset_index(drop=True)

        logger.info(f"✅ ดึงข้อมูลสำเร็จ: {len(df)} แท่งเทียน")
        return df

    def get_current_tick(self, symbol: Optional[str] = None) -> Optional[tuple]:
        """
        ดึงข้อมูลราคา Live ล่าสุด (TwelveData ไม่มี bid/ask แยก ใช้ราคาล่าสุดแทน)
        :return: Tuple ของ (bid, ask, spread) หรือ None
        """
        sym = (symbol or self.symbol).upper()
        tw_sym = SYMBOL_MAP.get(sym, sym)
        df = self._fetch(tw_sym, self.interval, outputsize=1)
        if df is None or len(df) == 0:
            return None
        price = float(df.iloc[-1]["close"])
        return price, price, 0.0

    def shutdown(self) -> None:
        """ปิดการเชื่อมต่อ (REST API ไม่ต้องปิด)"""
        logger.info("TwelveDataPriceService: ไม่ต้องปิดการเชื่อมต่อ (REST API)")
        self.is_connected = False