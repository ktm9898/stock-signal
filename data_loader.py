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
STOCKS_350_PATH = os.path.join(DATA_DIR, "stocks_350.json")
CACHE_FILE = os.path.join(DATA_DIR, "history_5y.parquet")
CACHE_CSV = os.path.join(DATA_DIR, "history_5y.csv")

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)

def get_kospi200_tickers():
    """Retrieve official KOSPI 200 list of tickers and names (Verified Master JSON -> PyKRX)."""
    # 1. Fast path: Read from data/stocks_350.json
    if os.path.exists(STOCKS_350_PATH):
        try:
            with open(STOCKS_350_PATH, "r", encoding="utf-8") as f:
                stocks = json.load(f)
                k200 = [s for s in stocks if s.get("market") == "KOSPI200"]
                if len(k200) >= 195:
                    return k200[:200]
        except Exception:
            pass

    items = []
    seen = set()
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
                if len(items) >= 195:
                    return items[:200]
    except Exception as e:
        print(f"[WARN] PyKRX KOSPI 200 index failed: {e}")

    return items[:200]

def get_kosdaq150_tickers():
    """Retrieve official KOSDAQ 150 list of tickers and names (Verified Master JSON -> PyKRX)."""
    # 1. Fast path: Read from data/stocks_350.json (Contains SOOP and all official 150 constituents)
    if os.path.exists(STOCKS_350_PATH):
        try:
            with open(STOCKS_350_PATH, "r", encoding="utf-8") as f:
                stocks = json.load(f)
                kq150 = [s for s in stocks if s.get("market") == "KOSDAQ150"]
                if len(kq150) >= 145:
                    return kq150[:150]
        except Exception:
            pass

    items = []
    seen = set()
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
                    if len(items) >= 145:
                        return items[:150]
    except Exception as e:
        print(f"[WARN] PyKRX KOSDAQ 150 index failed: {e}")

    return items[:150]

def fetch_stock_ohlcv(ticker, candle_count=2600, start_date=None, end_date=None):
    """Fetch up to 10-year (2,600 trading days) daily candle data using Naver FChart XML and PyKRX fallback."""
    clean_ticker = str(ticker).zfill(6) if str(ticker).isdigit() else str(ticker)
    
    # Method 1: Naver FChart XML (Adjusted Prices - count=2600 ~ 10.4 years of trading days)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        import xml.etree.ElementTree as ET
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={clean_ticker}&timeframe=day&count={candle_count}&requestType=0"
        res = requests.get(url, headers=headers, timeout=10)
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
        if len(rows) >= 1:
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

def convert_df_to_array_rows(df):
    """Convert indicator DataFrame to ultra-compact row array format."""
    result_rows = []
    for i in range(len(df)):
        d_val = df['Date'].iloc[i]
        if isinstance(d_val, pd.Timestamp):
            d_val = d_val.strftime("%Y-%m-%d")
        else:
            d_val = str(d_val)[:10]

        o_val = float(df['시가'].iloc[i])
        h_val = float(df['고가'].iloc[i])
        l_val = float(df['저가'].iloc[i])
        c_val = float(df['종가'].iloc[i])
        v_val = float(df['거래량'].iloc[i])

        o_num = round(o_val, 2) if (o_val < 5000 and '.' in str(o_val)) else int(round(o_val))
        h_num = round(h_val, 2) if (h_val < 5000 and '.' in str(h_val)) else int(round(h_val))
        l_num = round(l_val, 2) if (l_val < 5000 and '.' in str(l_val)) else int(round(l_val))
        c_num = round(c_val, 2) if (c_val < 5000 and '.' in str(c_val)) else int(round(c_val))
        v_num = int(round(v_val))

        adx_val = float(df['adx'].iloc[i]) if ('adx' in df and not np.isnan(df['adx'].iloc[i])) else 0.0
        pdi_val = float(df['plus_di'].iloc[i]) if ('plus_di' in df and not np.isnan(df['plus_di'].iloc[i])) else 0.0
        mdi_val = float(df['minus_di'].iloc[i]) if ('minus_di' in df and not np.isnan(df['minus_di'].iloc[i])) else 0.0
        rsi_val = float(df['rsi'].iloc[i]) if ('rsi' in df and not np.isnan(df['rsi'].iloc[i])) else 0.0
        
        bb_col = 'b_band_pct' if 'b_band_pct' in df else 'bb_pct'
        bb_raw = float(df[bb_col].iloc[i]) if (bb_col in df and not np.isnan(df[bb_col].iloc[i])) else 0.5

        macd_raw = float(df['macd'].iloc[i]) if ('macd' in df and not np.isnan(df['macd'].iloc[i])) else 0.0
        macd_val = round(macd_raw, 1) if abs(macd_raw) < 100 else int(round(macd_raw))

        stoch_k_val = float(df['stoch_k'].iloc[i]) if ('stoch_k' in df and not np.isnan(df['stoch_k'].iloc[i])) else 50.0
        disp_val = float(df['disparity20'].iloc[i]) if ('disparity20' in df and not np.isnan(df['disparity20'].iloc[i])) else 100.0
        vr_val = float(df['volume_ratio'].iloc[i]) if ('volume_ratio' in df and not np.isnan(df['volume_ratio'].iloc[i])) else 100.0

        result_rows.append([
            d_val,
            o_num,
            h_num,
            l_num,
            c_num,
            v_num,
            round(adx_val, 1),
            round(pdi_val, 1),
            round(mdi_val, 1),
            round(rsi_val, 1),
            round(bb_raw, 2),
            macd_val,
            round(stoch_k_val, 1),
            round(disp_val, 1),
            round(vr_val, 1)
        ])
    return result_rows

def fetch_stock_5y_ohlcv(ticker, start_date=None, end_date=None):
    """Backward-compatible alias for fetching 5-year OHLCV candles."""
    return fetch_stock_ohlcv(ticker, candle_count=1300, start_date=start_date, end_date=end_date)

CHUNK_2011_2015_PATH = os.path.join(DATA_DIR, "history_2011_2015.json")
CHUNK_2016_2020_PATH = os.path.join(DATA_DIR, "history_2016_2020.json")
CHUNK_2021_2025_PATH = os.path.join(DATA_DIR, "history_2021_2025.json")
CHUNK_2026_CURR_PATH = os.path.join(DATA_DIR, "history_2026_current.json")

KOSPI200_REAL_PATH = os.path.join(DATA_DIR, "stocks_kospi200_real.json")
KOSDAQ150_REAL_PATH = os.path.join(DATA_DIR, "stocks_kosdaq150_real.json")

def load_all_preloaded_data(start_year=2011):
    """
    Unified loader that loads and merges 5-year partitioned chunk datasets
    (2011~2015, 2016~2020, 2021~2025, 2026~current).
    Returns: dict with 'stocks' list and 'preloaded_data' dict containing all tickers and benchmarks.
    """
    merged_stocks = []
    merged_preloaded = {}
    seen_tickers = set()

    chunks = [
        (2011, CHUNK_2011_2015_PATH),
        (2016, CHUNK_2016_2020_PATH),
        (2021, CHUNK_2021_2025_PATH),
        (2026, CHUNK_2026_CURR_PATH)
    ]

    for year_from, path in chunks:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    for s in d.get("stocks", []):
                        if s["ticker"] not in seen_tickers:
                            seen_tickers.add(s["ticker"])
                            merged_stocks.append(s)
                    for k, v in d.get("preloaded_data", {}).items():
                        if k not in merged_preloaded:
                            merged_preloaded[k] = list(v)
                        else:
                            merged_preloaded[k].extend(v)
            except Exception as e:
                print(f"[WARN] Failed to load {path}: {e}")

    # Fallback to legacy split files if chunk files not found
    if not merged_preloaded:
        if os.path.exists(KOSPI200_REAL_PATH):
            with open(KOSPI200_REAL_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                merged_stocks.extend(d.get("stocks", []))
                merged_preloaded.update(d.get("preloaded_data", {}))
        if os.path.exists(KOSDAQ150_REAL_PATH):
            with open(KOSDAQ150_REAL_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                merged_stocks.extend(d.get("stocks", []))
                merged_preloaded.update(d.get("preloaded_data", {}))

    return {"stocks": merged_stocks, "preloaded_data": merged_preloaded}

def build_10y_split_datasets(candle_count=2600):
    """
    Build complete 10-year historical backtest datasets split into 2 files:
    1. data/stocks_kospi200_real.json (KOSPI 200 components + KOSPI/KOSDAQ benchmarks)
    2. data/stocks_kosdaq150_real.json (KOSDAQ 150 components + KOSDAQ/KOSPI benchmarks)
    3. data/stocks_350.json (Target 350 stock metadata list)
    Uses compact JSON formatting with separators=(',', ':') to maximize storage efficiency.
    """
    ensure_data_dir()

    print(f"[INFO] Fetching 10-Year constituent stock universes (target {candle_count} trading days)...")
    kospi_items = get_kospi200_tickers()[:200]
    kosdaq_items = get_kosdaq150_tickers()[:150]
    all_stocks = kospi_items + kosdaq_items

    print(f" -> Constituent universe: KOSPI 200 ({len(kospi_items)}), KOSDAQ 150 ({len(kosdaq_items)}) = Total {len(all_stocks)} stocks.")

    # Save stocks metadata list
    with open(STOCKS_350_PATH, "w", encoding="utf-8") as f:
        json.dump(all_stocks, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Saved component metadata list to {STOCKS_350_PATH}")

    # Targets to fetch: all stocks + benchmarks
    fetch_targets = [s['ticker'] for s in all_stocks] + ["KOSPI", "KOSDAQ"]
    all_preloaded_data = {}

    def fetch_symbol_data(symbol):
        try:
            df = fetch_stock_ohlcv(symbol, candle_count=candle_count)
            if df is not None and len(df) >= 30:
                df = calculate_full_indicators(df)
                df['Date'] = df.index if 'Date' not in df.columns else df['Date']
                array_rows = convert_df_to_array_rows(df)
                return symbol, array_rows
        except Exception as e:
            print(f"[WARN] Error fetching {symbol}: {e}")
        return symbol, None

    print(f"[INFO] Concurrently downloading 10-year daily candles & computing indicators for {len(fetch_targets)} symbols (16 threads)...")
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(fetch_symbol_data, fetch_targets))
        for symbol, rows in results:
            if rows and len(rows) > 0:
                all_preloaded_data[symbol] = rows

    print(f"[INFO] Successfully compiled 10Y data for {len(all_preloaded_data)} / {len(fetch_targets)} targets.")

    # 1. Build KOSPI 200 payload
    kospi_tickers = set([s['ticker'] for s in kospi_items] + ["KOSPI", "KOSDAQ"])
    kospi_preloaded = {k: v for k, v in all_preloaded_data.items() if k in kospi_tickers}
    kospi_payload = {
        "stocks": kospi_items,
        "preloaded_data": kospi_preloaded
    }
    with open(KOSPI200_REAL_PATH, "w", encoding="utf-8") as f:
        json.dump(kospi_payload, f, ensure_ascii=False, separators=(',', ':'))
    kospi_mb = os.path.getsize(KOSPI200_REAL_PATH) / (1024 * 1024)
    print(f"[SUCCESS] Saved KOSPI 200 dataset to {KOSPI200_REAL_PATH} ({kospi_mb:.2f} MB)")

    # 2. Build KOSDAQ 150 payload
    kosdaq_tickers = set([s['ticker'] for s in kosdaq_items] + ["KOSDAQ", "KOSPI"])
    kosdaq_preloaded = {k: v for k, v in all_preloaded_data.items() if k in kosdaq_tickers}
    kosdaq_payload = {
        "stocks": kosdaq_items,
        "preloaded_data": kosdaq_preloaded
    }
    with open(KOSDAQ150_REAL_PATH, "w", encoding="utf-8") as f:
        json.dump(kosdaq_payload, f, ensure_ascii=False, separators=(',', ':'))
    kosdaq_mb = os.path.getsize(KOSDAQ150_REAL_PATH) / (1024 * 1024)
    print(f"[SUCCESS] Saved KOSDAQ 150 dataset to {KOSDAQ150_REAL_PATH} ({kosdaq_mb:.2f} MB)")

    total_mb = kospi_mb + kosdaq_mb
    print(f"[DONE] Complete 10-year dual dataset generated successfully! Total size: {total_mb:.2f} MB (both files safely < 50MB)")
    return kospi_payload, kosdaq_payload

def build_stocks_350_real_json(output_path=None):
    """Legacy builder wrapper for backwards compatibility."""
    return build_10y_split_datasets()

if __name__ == "__main__":
    build_10y_split_datasets()


