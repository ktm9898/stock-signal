"""
Historical 5-Year Backtest Dataset Incremental Updater
Fetches new daily candles and updates data/stocks_350_real.json with 100% indicator continuity.
Maintains a rolling 5-year (1,250~1,300 trading days) window to keep file size optimal.
"""

import os
import sys
import json
import re
import datetime
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import requests
import pandas as pd
import numpy as np

# Import unified indicator calculation formula from data_loader
from data_loader import calculate_full_indicators

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STOCKS_350_REAL_PATH = os.path.join(DATA_DIR, "stocks_350_real.json")
STOCKS_350_PATH = os.path.join(DATA_DIR, "stocks_350.json")

# Target rolling window size (trading days ~ 5 years)
MAX_WINDOW_DAYS = 1300
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch_candles_and_indicators(ticker_or_symbol, candle_count=120):
    """
    Fetch the latest N candles for a stock or benchmark index from Naver FChart XML,
    and compute rolling technical indicators.
    """
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker_or_symbol}&timeframe=day&count={candle_count}&requestType=0"
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        xml_text = res.content.decode('euc-kr', errors='ignore')
        root = ET.fromstring(xml_text)
        items = root.findall('.//item')
        rows = []
        for item in items:
            data = item.attrib.get('data', '')
            if data:
                parts = data.split('|')
                if len(parts) >= 6:
                    d_str, op, hp, lp, cp, vol = parts[:6]
                    date_formatted = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
                    rows.append({
                        "Date": date_formatted,
                        "시가": float(op),
                        "고가": float(hp),
                        "저가": float(lp),
                        "종가": float(cp),
                        "거래량": float(vol)
                    })
        if len(rows) < 30:
            return None

        df = pd.DataFrame(rows)
        df = calculate_full_indicators(df)
        return df
    except Exception as e:
        return None

def convert_df_to_array_rows(df):
    """Convert indicator DataFrame to ultra-compact row array format."""
    result_rows = []
    is_index = False
    for i in range(len(df)):
        d_val = df['Date'].iloc[i]
        o_val = float(df['시가'].iloc[i])
        h_val = float(df['고가'].iloc[i])
        l_val = float(df['저가'].iloc[i])
        c_val = float(df['종가'].iloc[i])
        v_val = float(df['거래량'].iloc[i])

        # Round indices to 2 decimal places, normal stocks to integers
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

def update_backtest_database():
    """Perform incremental update on data/stocks_350_real.json."""
    if not os.path.exists(STOCKS_350_REAL_PATH):
        print(f"[ERROR] Target dataset not found: {STOCKS_350_REAL_PATH}")
        return False

    print("[INFO] Loading existing backtest dataset...")
    with open(STOCKS_350_REAL_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    stocks_meta = data.get("stocks", [])
    preloaded_data = data.get("preloaded_data", {})
    
    # Load fallback metadata if needed
    if not stocks_meta and os.path.exists(STOCKS_350_PATH):
        try:
            with open(STOCKS_350_PATH, "r", encoding="utf-8") as f:
                stocks_meta = json.load(f)
        except Exception:
            pass

    all_symbols = list(preloaded_data.keys())
    if "KOSPI" not in all_symbols:
        all_symbols.append("KOSPI")
    if "KOSDAQ" not in all_symbols:
        all_symbols.append("KOSDAQ")

    print(f"[INFO] Found {len(all_symbols)} symbols (350 stocks + benchmarks) in backtest database.")

    # Quick pre-check on benchmark/leading ticker to avoid 353 unnecessary network requests
    sample_ticker = "005930" if "005930" in preloaded_data else all_symbols[0]
    sample_history = preloaded_data.get(sample_ticker, [])
    last_known_date = sample_history[-1][0] if sample_history else "2021-01-01"
    print(f"[INFO] Current dataset last trading date: {last_known_date}")

    print(f"[INFO] Pre-checking latest market candles for {sample_ticker}...")
    sample_df = fetch_candles_and_indicators(sample_ticker, candle_count=30)
    if sample_df is not None and len(sample_df) > 0:
        latest_market_date = sample_df['Date'].iloc[-1]
        if latest_market_date <= last_known_date:
            print(f"[INFO] Fast-Exit: Market data is already up-to-date ({last_known_date}). Skipping full symbol sync.")
            return True

    updated_count = 0
    new_dates_added = set()

    def process_symbol(symbol):
        existing_rows = preloaded_data.get(symbol, [])
        sym_last_date = existing_rows[-1][0] if existing_rows else "2021-01-01"

        df = fetch_candles_and_indicators(symbol, candle_count=120)
        if df is None or len(df) == 0:
            return symbol, None, []

        new_array_rows = convert_df_to_array_rows(df)
        # Filter for rows that are strictly newer than existing last date
        append_candidates = [r for r in new_array_rows if r[0] > sym_last_date]
        return symbol, sym_last_date, append_candidates

    print("[INFO] Fetching latest candles in parallel (16 threads)...")
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(process_symbol, all_symbols))

    for symbol, sym_last_date, new_rows in results:
        if new_rows:
            updated_count += 1
            for r in new_rows:
                new_dates_added.add(r[0])
            
            existing = preloaded_data.get(symbol, [])
            combined = existing + new_rows
            # Maintain rolling window of MAX_WINDOW_DAYS
            if len(combined) > MAX_WINDOW_DAYS:
                combined = combined[-MAX_WINDOW_DAYS:]
            preloaded_data[symbol] = combined

    if not new_dates_added:
        print(f"[INFO] Backtest dataset is already 100% up-to-date. (Last date: {last_known_date})")
        return True

    sorted_new_dates = sorted(list(new_dates_added))
    print(f"[SUCCESS] Added {len(sorted_new_dates)} new trading day(s): {', '.join(sorted_new_dates)}")
    print(f"[INFO] Updated {updated_count} symbols successfully.")

    # Save to JSON
    payload = {
        "stocks": stocks_meta,
        "preloaded_data": preloaded_data
    }

    temp_path = STOCKS_350_REAL_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    if os.path.exists(STOCKS_350_REAL_PATH):
        os.remove(STOCKS_350_REAL_PATH)
    os.rename(temp_path, STOCKS_350_REAL_PATH)

    final_size_mb = os.path.getsize(STOCKS_350_REAL_PATH) / (1024 * 1024)
    print(f"[DONE] Saved updated dataset to {STOCKS_350_REAL_PATH} ({final_size_mb:.2f} MB)")
    return True

if __name__ == "__main__":
    success = update_backtest_database()
    if not success:
        sys.exit(1)
