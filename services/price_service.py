"""
Price Service Module - Free Cloud API
จัดการการดึงข้อมูลราคาจาก Yahoo Finance (yfinance)
แทน MetaTrader 5 เพื่อใช้งานบน Streamlit Community Cloud ได้ฟรี
"""

from typing import Optional, Tuple
import datetime
import pandas as pd
import yfinance as yf

from logger import get_logger
from config import config

logger = get_logger("PriceService")


# Symbol Mapping: แปลงสัญลักษณ์ MT5 เป็น Yahoo Finance Symbol
SYMBOL_MAP = {
    "XAUUSD": "GC=F",      # Gold Futures
    "XAUUSDm": "GC=F",     # Gold Futures (Exness suffix)
    "XAUUSDM": "GC=F",     # Gold Futures (Exness suffix uppercase)
    "EURUSD": "EURUSD=X",
    "EURUSDm": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "GBPUSDm": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDJPYm": "USDJPY=X",
    "BTCUSD": "BTC-USD",
    "BTCUSDm": "BTC-USD",
    "ETHUSD": "ETH-USD",
    "ETHUSDm": "ETH-USD",
    "USDCHF": "USDCHF=X",
    "USDCHFm": "USDCHF=X",
    "AUDUSD": "AUDUSD=X",
    "AUDUSDm": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X",
    "NZDUSDm": "NZDUSD=X",
    "USDCAD": "USDCAD=X",
    "USDCADm": "USDCAD=X",
}

# Timeframe Mapping: แปลง Timeframe เป็น yfinance Interval
TIMEFRAME_MAP = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "1d",    # yfinance ไม่มี 4h, ใช้ daily แทน
    "D1": "1d",
}


class PriceService:
    """
    คลาสสำหรับดึงข้อมูลราคาจาก Yahoo Finance (yfinance)
    ใช้แทน MT5Service สำหรับการดึงข้อมูลราคาฟรี
    
    ข้อจำกัด:
    - ราคาอาจไม่ตรง 100% กับ Exness (ต่างกันเล็กน้อย)
    - ข้อมูลมี delay เล็กน้อย (ไม่ใช่ tick-by-tick)
    - ไม่สามารถเทรดผ่านระบบนี้ได้
    """

    def __init__(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ):
        self.symbol = (symbol or config.mt5.symbol).upper()
        self.timeframe_str = (timeframe or config.mt5.timeframe).upper()
        
        # แปลง Symbol เป็น Yahoo Finance Symbol
        self.yf_symbol = SYMBOL_MAP.get(self.symbol, self.symbol)
        
        # แปลง Timeframe เป็น yfinance Interval
        self.interval = TIMEFRAME_MAP.get(self.timeframe_str, "1h")
        
        self.is_connected = True  # yfinance ไม่ต้อง login
        logger.info(f"PriceService initialized: {self.yf_symbol} ({self.timeframe_str} -> {self.interval})")

    def connect(self) -> bool:
        """
        ตรวจสอบการเชื่อมต่อ (yfinance ไม่ต้อง login)
        :return: True เสมอ
        """
        logger.info(f"กำลังเชื่อมต่อกับ Yahoo Finance...")
        try:
            # ทดสอบดึงข้อมูลเล็กน้อย
            ticker = yf.Ticker(self.yf_symbol)
            _ = ticker.history(period="1d")
            self.is_connected = True
            logger.info(f"✅ เชื่อมต่อ Yahoo Finance สำเร็จ! Symbol: {self.yf_symbol}")
            return True
        except Exception as e:
            logger.error(f"❌ เชื่อมต่อ Yahoo Finance ล้มเหลว: {e}")
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
        :param timeframe_str: Timeframe เช่น H1, M15
        :param count: จำนวนแท่งเทียนที่ต้องการ (yfinance จะคำนวณ period อัตโนมัติ)
        :return: pandas.DataFrame ที่มีคอลัมน์ time, open, high, low, close, tick_volume
        """
        sym = symbol or self.symbol
        tf_str = (timeframe_str or self.timeframe_str).upper()
        
        # แปลง symbol และ timeframe
        yf_sym = SYMBOL_MAP.get(sym, sym)
        yf_interval = TIMEFRAME_MAP.get(tf_str, "1h")
        
        # คำนวณ period จาก count (yfinance ใช้ period แทน count)
        period = self._calculate_period(count, yf_interval)
        
        try:
            logger.info(f"กำลังดึงข้อมูลแท่งเทียน: {yf_sym} ({yf_interval}, period={period})...")
            
            ticker = yf.Ticker(yf_sym)
            df = ticker.history(period=period, interval=yf_interval)
            
            if df is None or len(df) == 0:
                logger.error(f"ไม่สามารถดึงแท่งเทียนสำหรับ {yf_sym} ({yf_interval}) ได้: ไม่มีข้อมูล")
                return None
            
            # แปลงชื่อคอลัมน์ให้ตรงกับ MT5 format
            df = df.reset_index()
            df = df.rename(columns={
                "Datetime": "time",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "tick_volume",
            })
            
            # ตรวจสอบว่า time column มีชื่อถูกต้อง
            if "time" not in df.columns:
                # ถ้า index เป็น time (สำหรับ daily data)
                df = df.reset_index()
                if "Date" in df.columns:
                    df = df.rename(columns={"Date": "time"})
            
            # เลือกเฉพาะคอลัมน์ที่ต้องการ
            required_cols = ["time", "open", "high", "low", "close", "tick_volume"]
            available_cols = [col for col in required_cols if col in df.columns]
            
            if "time" not in available_cols:
                logger.error(f"ไม่พบคอลัมน์ 'time' ในข้อมูล: {df.columns.tolist()}")
                return None
            
            df = df[available_cols]
            
            # เรียงลำดับจากอดีตไปปัจจุบัน
            df.sort_values("time", ascending=True, inplace=True)
            df.reset_index(drop=True, inplace=True)
            
            # จำกัดจำนวน rows ตาม count
            if len(df) > count:
                df = df.tail(count).reset_index(drop=True)
            
            logger.info(f"✅ ดึงข้อมูลสำเร็จ: {len(df)} แท่งเทียน")
            return df
            
        except Exception as e:
            logger.error(f"เกิดข้อผิดพลาดในการดึงแท่งเทียน: {e}")
            return None

    def get_current_tick(self, symbol: Optional[str] = None) -> Optional[Tuple[float, float, float]]:
        """
        ดึงข้อมูลราคา Live ล่าสุด (Bid, Ask, Spread)
        :return: Tuple ของ (bid, ask, spread) หรือ None
        """
        sym = symbol or self.symbol
        yf_sym = SYMBOL_MAP.get(sym, sym)
        
        try:
            ticker = yf.Ticker(yf_sym)
            info = ticker.info
            
            # ดึงราคาล่าสุด
            if "regularMarketPrice" in info:
                price = info["regularMarketPrice"]
                # yfinance ไม่มี bid/ask แยก ใช้ราคาล่าสุดแทน
                bid = price
                ask = price
                spread = 0.0
                return bid, ask, spread
            else:
                logger.warning(f"ไม่สามารถดึงราคาล่าสุดสำหรับ {yf_sym}")
                return None
                
        except Exception as e:
            logger.error(f"เกิดข้อผิดพลาดในการดึงราคาล่าสุด: {e}")
            return None

    def _calculate_period(self, count: int, interval: str) -> str:
        """
        คำนวณ period จาก count และ interval
        :param count: จำนวนแท่งเทียน
        :param interval: yfinance interval (1m, 5m, 15m, 1h, 1d)
        :return: yfinance period string
        """
        # กำหนด period ขั้นต่ำตาม interval เพื่อให้ได้ข้อมูลเพียงพอเสมอ
        # (yfinance มีข้อจำกัด: ข้อมูล 1m-30m มีให้แค่ 60 วัน, 1h มีแค่ 730 วัน)
        min_period_by_interval = {
            "1m": "1d",
            "5m": "5d",
            "15m": "1mo",
            "30m": "1mo",
            "1h": "3mo",
            "1d": "1y",
        }
        min_period = min_period_by_interval.get(interval, "1mo")

        # คำนวณระยะเวลาทั้งหมดที่ต้องการ
        interval_minutes = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "1d": 1440,
        }
        minutes_per_bar = interval_minutes.get(interval, 60)
        total_minutes = count * minutes_per_bar

        # แปลงเป็น period string ตามระยะเวลาทั้งหมดและเงื่อนไขขั้นต่ำ
        rank = {"1d": 1, "5d": 2, "1mo": 3, "3mo": 4, "6mo": 5, "1y": 6}
        min_rank = rank.get(min_period, 3)

        if total_minutes <= 60 * 24:  # ไม่เกิน 1 วัน
            return max("1d", min_period, key=lambda p: rank[p])
        elif total_minutes <= 60 * 24 * 5:  # ไม่เกิน 5 วัน
            if min_rank >= rank["5d"]:
                return min_period
            return "5d"
        elif total_minutes <= 60 * 24 * 30:  # ไม่เกิน 1 เดือน
            if min_rank >= rank["1mo"]:
                return min_period
            return "1mo"
        elif total_minutes <= 60 * 24 * 90:  # ไม่เกิน 3 เดือน
            if min_rank >= rank["3mo"]:
                return min_period
            return "3mo"
        elif total_minutes <= 60 * 24 * 180:  # ไม่เกิน 6 เดือน
            if min_rank >= rank["6mo"]:
                return min_period
            return "6mo"
        else:
            if min_rank >= rank["1y"]:
                return min_period
            return "1y"

    def shutdown(self) -> None:
        """ปิดการเชื่อมต่อ (yfinance ไม่ต้องปิด)"""
        logger.info("PriceService: ไม่ต้องปิดการเชื่อมต่อ (yfinance ไม่ต้อง login)")
        self.is_connected = False
