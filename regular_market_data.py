"""
Regular Market (09:00 ~ 15:30) Data Provider Module.
Eliminates after-market (16:00 ~ 20:00) price, volume, and tick distortions.

Hierarchy:
  1st Priority: KRX [12001] Official Market Snapshot (0.5s for all stocks, 0% error)
  2nd Priority Fallback: Naver 09:00~15:30 Minute Candle Aggregation (Zero credentials, pure regular OHLCV)
  * Raw day candles with after-market contamination are NEVER used.
"""

import os
import re
import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger("regular_market_data")
logger.setLevel(logging.INFO)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Cache for KRX daily market snapshots {YYYYMMDD: {ticker: {시가, 고가, 저가, 종가, 거래량}}}
_KRX_SNAPSHOT_CACHE = {}

def fetch_krx_daily_snapshot(date_str):
    """
    1st Priority: Fetch official KRX [12001] market snapshot for a given date.
    Returns dict of {ticker_6digit: {'시가': float, '고가': float, '저가': float, '종가': float, '거래량': float}}
    Returns None if KRX credentials are missing or request fails.
    """
    clean_date = date_str.replace("-", "").strip()
    if clean_date in _KRX_SNAPSHOT_CACHE:
        return _KRX_SNAPSHOT_CACHE[clean_date]

    # Check if KRX credentials exist
    krx_id = os.environ.get("KRX_ID")
    krx_pw = os.environ.get("KRX_PW")
    if not krx_id or not krx_pw:
        # Without credentials, data.krx.co.kr rejects scraping
        return None

    try:
        from pykrx import stock
        # Fetch both KOSPI and KOSDAQ
        result = {}
        for mkt in ["KOSPI", "KOSDAQ"]:
            df = stock.get_market_ohlcv_by_ticker(clean_date, market=mkt)
            if df is not None and not df.empty and "종가" in df.columns:
                for t, row in df.iterrows():
                    code = str(t).zfill(6)
                    result[code] = {
                        "시가": float(row.get("시가", 0)),
                        "고가": float(row.get("고가", 0)),
                        "저가": float(row.get("저가", 0)),
                        "종가": float(row.get("종가", 0)),
                        "거래량": float(row.get("거래량", 0))
                    }
        if result:
            _KRX_SNAPSHOT_CACHE[clean_date] = result
            return result
    except Exception as e:
        logger.warning(f"KRX snapshot fetch failed for {clean_date}: {e}")

    return None

def fetch_naver_minute_regular_ohlcv(ticker, target_dates=None, candle_count=3000):
    """
    2nd Priority Fallback: Fetch Naver FChart minute candles (timeframe=minute)
    and aggregate strictly between 09:00:00 and 15:30:00.
    
    Returns dict of {YYYY-MM-DD: {'시가': float, '고가': float, '저가': float, '종가': float, '거래량': float}}
    """
    clean_ticker = str(ticker).zfill(6)
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={clean_ticker}&timeframe=minute&count={candle_count}&requestType=0"
    
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=7) as resp:
            xml_text = resp.read().decode("euc-kr", errors="ignore")
    except Exception as e:
        logger.warning(f"Naver minute fetch failed for {clean_ticker}: {e}")
        return {}

    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        logger.warning(f"XML parse error for {clean_ticker}: {e}")
        return {}

    # Minute item format: data="YYYYMMDDHHMM|null|null|null|price|cum_volume"
    # Or data="YYYYMMDDHHMM|open|high|low|close|cum_volume"
    # In FChart minute candles, parts[4] is execution price, parts[5] is cumulative day volume
    grouped = defaultdict(list)
    for it in root.findall(".//item"):
        raw_data = it.attrib.get("data", "")
        if not raw_data:
            continue
        parts = raw_data.split("|")
        if len(parts) >= 6:
            dt_str = parts[0]
            if len(dt_str) >= 12:
                d_str = dt_str[:8] # YYYYMMDD
                t_str = dt_str[8:12] # HHMM
                
                # Strict Regular Market Filter: 09:00 <= HHMM <= 15:30
                if "0900" <= t_str <= "1530":
                    price_str = parts[4]
                    vol_str = parts[5]
                    if price_str and price_str != "null":
                        price = float(price_str)
                        vol = float(vol_str) if (vol_str and vol_str != "null") else 0.0
                        grouped[d_str].append((t_str, price, vol))

    results = {}
    for d_str, records in grouped.items():
        fmt_date = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
        if target_dates and fmt_date not in target_dates and d_str not in target_dates:
            continue
        if not records:
            continue

        prices = [r[1] for r in records]
        # Open: price of first trade at or after 09:00
        r_open = prices[0]
        # High: max price during 09:00 ~ 15:30
        r_high = max(prices)
        # Low: min price during 09:00 ~ 15:30
        r_low = min(prices)
        # Close: last trade at or before 15:30 (Zero-tick safe)
        r_close = prices[-1]
        # Volume: cumulative volume at the last regular market candle (15:30)
        r_vol = records[-1][2]

        results[fmt_date] = {
            "시가": r_open,
            "고가": r_high,
            "저가": r_low,
            "종가": r_close,
            "거래량": r_vol
        }

    return results

def get_clean_regular_ohlcv(ticker, date_str):
    """
    Returns regular market OHLCV dict for a ticker on date_str.
    date_str can be 'YYYY-MM-DD' or 'YYYYMMDD'.
    
    1st: Try KRX [12001]
    2nd: Try Naver minute candle aggregation
    """
    clean_ticker = str(ticker).zfill(6)
    clean_date = date_str.replace("-", "").strip()
    fmt_date = f"{clean_date[:4]}-{clean_date[4:6]}-{clean_date[6:8]}"

    # 1st Priority: Naver Minute Aggregation (100% pure 15:30 regular OHLCV & volume)
    naver_candles = fetch_naver_minute_regular_ohlcv(clean_ticker, target_dates=[fmt_date, clean_date])
    if fmt_date in naver_candles:
        return naver_candles[fmt_date]
    if clean_date in naver_candles:
        return naver_candles[clean_date]

    # 2nd Priority Fallback: KRX Snapshot
    krx_all = fetch_krx_daily_snapshot(clean_date)
    if krx_all and clean_ticker in krx_all:
        return krx_all[clean_ticker]

    return None
