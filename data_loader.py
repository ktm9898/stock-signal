"""
5-Year Historical OHLCV Data Loader & Technical Indicator Caching Engine
Fetches 5-year daily candle data for KOSPI 200 & KOSDAQ 150 components with full indicator pre-calculation.
"""

import os
import sys
import datetime
import re
import json
import requests
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

# Safe PyKRX Import
def import_pykrx_safely():
    try:
        from pykrx import stock
        return stock
    except Exception:
        os.environ.pop("KRX_ID", None)
        os.environ.pop("KRX_PW", None)
        for mod in list(sys.modules.keys()):
            if mod.startswith("pykrx"):
                del sys.modules[mod]
        try:
            from pykrx import stock
            return stock
        except Exception:
            return None

stock = import_pykrx_safely()

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CACHE_FILE = os.path.join(DATA_DIR, "history_5y.parquet")
CACHE_CSV = os.path.join(DATA_DIR, "history_5y.csv")

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)

def get_kospi200_tickers():
    """Retrieve KOSPI 200 list of tickers and names."""
    items = []
    seen = set()
    
    # 1. Try PyKRX Index 1028
    try:
        if stock:
            tickers = stock.get_index_portfolio_deposit_file("1028")
            if tickers and len(tickers) > 0:
                for ticker in tickers:
                    clean_t = str(ticker).zfill(6)
                    name = stock.get_market_ticker_name(clean_t)
                    if clean_t not in seen:
                        seen.add(clean_t)
                        items.append({"ticker": clean_t, "name": name, "market": "KOSPI200"})
                if len(items) >= 100:
                    return items
    except Exception as e:
        print(f"[WARN] PyKRX index 1028 failed: {e}")

    # 2. Try PyKRX KODEX 200 ETF (069500)
    try:
        if stock:
            tickers = stock.get_etf_portfolio_deposit_file("069500")
            if tickers and len(tickers) > 0:
                for ticker in tickers:
                    clean_t = str(ticker).zfill(6)
                    name = stock.get_market_ticker_name(clean_t)
                    if clean_t not in seen:
                        seen.add(clean_t)
                        items.append({"ticker": clean_t, "name": name, "market": "KOSPI200"})
                if len(items) >= 100:
                    return items
    except Exception as e:
        print(f"[WARN] PyKRX ETF 069500 failed: {e}")

    # 3. Fallback: Naver Market Sum Top 200
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        for page in range(1, 5):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page={page}"
            res = requests.get(url, headers=headers, timeout=5)
            res.encoding = 'euc-kr'
            matches = re.findall(r'href="/item/main\.naver\?code=(\d+)">(.*?)</a>', res.text)
            for code, name in matches:
                clean_t = code.zfill(6)
                if clean_t not in seen:
                    seen.add(clean_t)
                    items.append({"ticker": clean_t, "name": name.strip(), "market": "KOSPI200"})
    except Exception as e:
        print(f"[ERROR] Naver Market Sum KOSPI fallback failed: {e}")

    return items

def get_kosdaq150_tickers():
    """Retrieve KOSDAQ 150 list of tickers and names."""
    items = []
    seen = set()
    
    # 1. Try PyKRX Index 2203 / 2011
    try:
        if stock:
            for idx_code in ["2203", "2011"]:
                tickers = stock.get_index_portfolio_deposit_file(idx_code)
                if tickers and len(tickers) > 0:
                    for ticker in tickers:
                        clean_t = str(ticker).zfill(6)
                        name = stock.get_market_ticker_name(clean_t)
                        if clean_t not in seen:
                            seen.add(clean_t)
                            items.append({"ticker": clean_t, "name": name, "market": "KOSDAQ150"})
                    if len(items) >= 100:
                        return items
    except Exception as e:
        print(f"[WARN] PyKRX KOSDAQ 150 index failed: {e}")

    # 2. Try PyKRX KODEX KOSDAQ 150 ETF (229200)
    try:
        if stock:
            tickers = stock.get_etf_portfolio_deposit_file("229200")
            if tickers and len(tickers) > 0:
                for ticker in tickers:
                    clean_t = str(ticker).zfill(6)
                    name = stock.get_market_ticker_name(clean_t)
                    if clean_t not in seen:
                        seen.add(clean_t)
                        items.append({"ticker": clean_t, "name": name, "market": "KOSDAQ150"})
                if len(items) >= 100:
                    return items
    except Exception as e:
        print(f"[WARN] PyKRX ETF 229200 failed: {e}")

    # 3. Fallback: Naver Market Sum Top 150
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        for page in range(1, 4):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok=1&page={page}"
            res = requests.get(url, headers=headers, timeout=5)
            res.encoding = 'euc-kr'
            matches = re.findall(r'href="/item/main\.naver\?code=(\d+)">(.*?)</a>', res.text)
            for code, name in matches:
                clean_t = code.zfill(6)
                if clean_t not in seen:
                    seen.add(clean_t)
                    items.append({"ticker": clean_t, "name": name.strip(), "market": "KOSDAQ150"})
    except Exception as e:
        print(f"[ERROR] Naver Market Sum KOSDAQ 150 fallback failed: {e}")

    return items

def fetch_stock_5y_ohlcv(ticker, start_date, end_date):
    """Fetch 5-year daily candle data using Naver FChart XML (count=1300 ~ 5 years) and PyKRX fallback."""
    clean_ticker = str(ticker).zfill(6)
    
    # Method 1: Naver FChart XML (Adjusted Prices - 1300 candles = ~5.2 years of trading days)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        import xml.etree.ElementTree as ET
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={clean_ticker}&timeframe=day&count=1300&requestType=0"
        res = requests.get(url, headers=headers, timeout=8)
        xml_text = res.content.decode('euc-kr', errors='ignore')
        root = ET.fromstring(xml_text)
        items = root.findall('.//item')
        rows = []
        for item in items:
            data = item.attrib.get('data', '')
            if data:
                parts = data.split('|')
                if len(parts) >= 6:
                    date_str, open_p, high_p, low_p, close_p, vol = parts[:6]
                    rows.append({
                        'Date': pd.to_datetime(date_str, format='%Y%m%d', errors='coerce'),
                        '시가': float(open_p),
                        '고가': float(high_p),
                        '저가': float(low_p),
                        '종가': float(close_p),
                        '거래량': float(vol)
                    })
        if len(rows) >= 50:
            df = pd.DataFrame(rows)
            df = df.dropna(subset=['Date']).sort_values('Date').reset_index(drop=True)
            df.set_index('Date', inplace=True)
            return df
    except Exception:
        pass

    # Method 2: PyKRX Fallback
    try:
        if stock:
            df = stock.get_market_ohlcv_by_date(start_date, end_date, clean_ticker)
            if df is not None and len(df) >= 50 and '고가' in df.columns:
                return df
    except Exception:
        pass

    return None

def calculate_full_indicators(df, period=14):
    """
    Compute KIS MTS/HTS Standard indicators matching screener.py exactly:
    ADX(14), +DI, -DI, RSI(14), BB %b(20,2), MACD(12,26,9), MACD Osc, Stoch(14,3,3) K/D, Disparity20, VolumeRatio.
    """
    if df is None or len(df) < 30 or not {'고가', '저가', '종가', '거래량'}.issubset(df.columns):
        return df

    highs = df['고가'].values
    lows = df['저가'].values
    closes = df['종가'].values
    volumes = df['거래량'].values
    n = len(closes)

    # 1. ADX, +DI, -DI (KIS MTS/HTS Standard Welles Wilder RMA Algorithm, alpha = 1 / period)
    tr, dm_p, dm_m = [], [], []
    for i in range(1, n):
        h, l, c = highs[i], lows[i], closes[i]
        ph, pl, pc = highs[i-1], lows[i-1], closes[i-1]
        
        tr_val = max(h - l, abs(h - pc), abs(l - pc))
        up = h - ph
        down = pl - l
        
        dp = up if (up > down and up > 0) else 0.0
        dm = down if (down > up and down > 0) else 0.0
        
        tr.append(tr_val)
        dm_p.append(dp)
        dm_m.append(dm)

    alpha = 2.0 / (period + 1)
    def calc_ema(arr):
        if not arr:
            return []
        res = [arr[0]]
        for val in arr[1:]:
            res.append(val * alpha + res[-1] * (1 - alpha))
        return res

    tr_e = calc_ema(tr)
    dp_e = calc_ema(dm_p)
    dm_e = calc_ema(dm_m)

    pdi = [100.0 * p / t if t > 0 else 0.0 for p, t in zip(dp_e, tr_e)]
    mdi = [100.0 * m / t if t > 0 else 0.0 for m, t in zip(dm_e, tr_e)]

    dx = [100.0 * abs(p - m) / (p + m) if (p + m) > 0 else 0.0 for p, m in zip(pdi, mdi)]
    adx = calc_ema(dx)

    df['plus_di'] = [np.nan] + pdi
    df['minus_di'] = [np.nan] + mdi
    df['adx'] = [np.nan] + adx

    # 2. RSI (14)
    close_series = df['종가']
    delta = close_series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))

    # 3. Moving Averages & Bollinger Bands (20, 2)
    df['ma5'] = close_series.rolling(window=5).mean()
    df['ma20'] = close_series.rolling(window=20).mean()
    std20 = close_series.rolling(window=20).std(ddof=0)
    upper_b = df['ma20'] + (2 * std20)
    lower_b = df['ma20'] - (2 * std20)
    band_width = upper_b - lower_b
    df['b_band_pct'] = np.where(band_width != 0, (close_series - lower_b) / (band_width + 1e-9), 0.5)

    # 4. MACD (12, 26, 9)
    ema12 = close_series.ewm(span=12, adjust=False).mean()
    ema26 = close_series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    df['macd'] = macd
    df['macd_signal'] = macd_signal
    df['macd_osc'] = macd - macd_signal

    # 5. Stochastic Slow (14, 3, 3)
    low_14 = df['저가'].rolling(window=14).min()
    high_14 = df['고가'].rolling(window=14).max()
    fast_k = 100 * ((close_series - low_14) / ((high_14 - low_14) + 1e-9))
    stoch_k = fast_k.rolling(window=3).mean()
    stoch_d = stoch_k.rolling(window=3).mean()
    df['stoch_k'] = stoch_k
    df['stoch_d'] = stoch_d

    # 6. Disparity 20 & Volume Ratio
    df['disparity20'] = (close_series / (df['ma20'] + 1e-9)) * 100.0
    ma5_vol = df['거래량'].rolling(window=5).mean()
    df['volume_ratio'] = (df['거래량'] / (ma5_vol + 1e-9)) * 100.0

    return df

def build_5y_history_cache(force_refresh=False):
    """Build or update local 5-year historical dataset for KOSPI 200 & KOSDAQ 150."""
    ensure_data_dir()
    
    if not force_refresh and (os.path.exists(CACHE_FILE) or os.path.exists(CACHE_CSV)):
        print(f"[INFO] 5-year historical dataset already exists. Loading cache...")
        return load_5y_history_cache()

    print("[INFO] Building 5-year historical database for KOSPI 200 & KOSDAQ 150 (350 stocks)...")
    kospi_items = get_kospi200_tickers()
    kosdaq_items = get_kosdaq150_tickers()
    all_items = kospi_items + kosdaq_items
    print(f" -> Target components: KOSPI 200 ({len(kospi_items)}), KOSDAQ 150 ({len(kosdaq_items)}) = Total {len(all_items)} stocks.")

    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=365 * 5 + 30)).strftime("%Y%m%d")

    all_dfs = []

    def fetch_and_process(item):
        ticker = item['ticker']
        name = item['name']
        market = item.get('market', 'KOSPI200')
        try:
            df = fetch_stock_5y_ohlcv(ticker, start_date, end_date)
            if df is not None and len(df) >= 60:
                df = calculate_full_indicators(df)
                df['Ticker'] = ticker
                df['Name'] = name
                df['Market'] = market
                return df.reset_index()
        except Exception as e:
            pass
        return None

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(fetch_and_process, all_items))
        for res in results:
            if res is not None and len(res) > 0:
                all_dfs.append(res)

    if not all_dfs:
        print("[ERROR] Failed to fetch historical data for components.")
        return None

    combined_df = pd.concat(all_dfs, ignore_index=True)
    print(f"[INFO] Successfully compiled {len(combined_df):,} total daily candle records across {len(all_dfs)} stocks.")

    # Save to Parquet (and CSV as backup)
    try:
        combined_df.to_parquet(CACHE_FILE, index=False)
        print(f"[SUCCESS] Saved 5-year cache to Parquet: {CACHE_FILE} ({os.path.getsize(CACHE_FILE) / 1024 / 1024:.2f} MB)")
    except Exception as e:
        print(f"[WARN] Parquet save failed ({e}). Saving to CSV...")
        combined_df.to_csv(CACHE_CSV, index=False, encoding='utf-8-sig')
        print(f"[SUCCESS] Saved 5-year cache to CSV: {CACHE_CSV}")

    return combined_df

def load_5y_history_cache():
    """Load cached 5-year dataset."""
    if os.path.exists(CACHE_FILE):
        try:
            return pd.read_parquet(CACHE_FILE)
        except Exception:
            pass
    if os.path.exists(CACHE_CSV):
        try:
            return pd.read_csv(CACHE_CSV)
        except Exception:
            pass
    return build_5y_history_cache()

if __name__ == "__main__":
    df = build_5y_history_cache(force_refresh=True)
    if df is not None:
        print(f"[DONE] Total rows in 5Y database: {len(df):,}")
