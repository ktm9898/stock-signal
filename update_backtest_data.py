"""
Historical Backtest Dataset Incremental Updater
Updates data/history_2026_current.json with 100% indicator continuity.
Preserves all historical candles without truncating, appending new daily trading candles.
"""

import os
import sys
import json
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import requests
import pandas as pd
import numpy as np

from data_loader import (
    calculate_full_indicators,
    get_kospi200_tickers,
    get_kosdaq150_tickers,
    fetch_stock_ohlcv
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CHUNK_2026_CURR_PATH = os.path.join(DATA_DIR, "history_2026_current.json")
STOCKS_350_PATH = os.path.join(DATA_DIR, "stocks_350.json")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch_candles_and_indicators(ticker_or_symbol, candle_count=120):
    clean_sym = str(ticker_or_symbol).zfill(6) if str(ticker_or_symbol).isdigit() else str(ticker_or_symbol)
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={clean_sym}&timeframe=day&count={candle_count}&requestType=0"
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
        if len(rows) < 1:
            return None

        df = pd.DataFrame(rows)
        df = calculate_full_indicators(df)
        return df
    except Exception:
        return None

def convert_df_to_array_rows(df):
    array_rows = []
    for idx, row in df.iterrows():
        d_val = row.get("Date")
        if pd.isna(d_val):
            d_val = str(idx)
        else:
            d_val = str(d_val)[:10]

        def get_val(*keys, default=0.0):
            for k in keys:
                for candidate in [k, k.lower(), k.upper(), k.capitalize()]:
                    if candidate in row:
                        val = row.get(candidate)
                        if val is not None and not pd.isna(val) and not np.isinf(val):
                            return float(val)
            return default

        r_open = round(get_val("시가", "open"), 2)
        r_high = round(get_val("고가", "high"), 2)
        r_low = round(get_val("저가", "low"), 2)
        r_close = round(get_val("종가", "close"), 2)
        r_vol = round(get_val("거래량", "volume"), 0)

        r_adx = round(get_val("adx", "ADX", default=0.0), 2)
        r_pdi = round(get_val("plus_di", "Plus_DI", "+DI", default=0.0), 2)
        r_mdi = round(get_val("minus_di", "Minus_DI", "-DI", default=0.0), 2)
        r_rsi = round(get_val("rsi", "RSI", default=50.0), 2)
        r_bb = round(get_val("b_band_pct", "bb_pct", "BB_Pct", "BB_%b", default=0.5), 4)
        r_macd = round(get_val("macd", "MACD", default=0.0), 2)
        r_stoch_k = round(get_val("stoch_k", "Slow_K", "slow_k", default=50.0), 2)
        r_disp20 = round(get_val("disparity20", "Disparity20", "disp20", default=100.0), 2)
        r_vr = round(get_val("volume_ratio", "Volume_Ratio", "vol_ratio", default=100.0), 2)

        array_rows.append([
            d_val,
            r_open, r_high, r_low, r_close, r_vol,
            r_adx, r_pdi, r_mdi, r_rsi, r_bb,
            r_macd, r_stoch_k, r_disp20, r_vr
        ])
    return array_rows

def sync_current_year_chunk():
    """
    Incrementally sync data/history_2026_current.json (4MB) with new daily candles.
    """
    print("[INFO] Checking live index constituents (KOSPI 200 + KOSDAQ 150)...")
    kospi_items = get_kospi200_tickers()[:200]
    kosdaq_items = get_kosdaq150_tickers()[:150]
    all_target_stocks = kospi_items + kosdaq_items
    all_symbols = [s['ticker'] for s in all_target_stocks] + ["KOSPI", "KOSDAQ"]

    # 1. Update stocks_350.json
    try:
        with open(STOCKS_350_PATH, "w", encoding="utf-8") as f:
            json.dump(all_target_stocks, f, ensure_ascii=False, indent=2)
        print(f"[INFO] Updated {STOCKS_350_PATH}")
    except Exception as e:
        print(f"[WARN] Could not update {STOCKS_350_PATH}: {e}")

    # 2. Load existing 2026_current file
    preloaded_data = {}
    if os.path.exists(CHUNK_2026_CURR_PATH):
        try:
            with open(CHUNK_2026_CURR_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                preloaded_data = d.get("preloaded_data", {})
        except Exception as e:
            print(f"[WARN] Could not read {CHUNK_2026_CURR_PATH}: {e}")

    print(f"[INFO] Syncing daily candles across {len(all_symbols)} active symbols into 2026~current chunk...")

    def process_symbol(symbol):
        existing_rows = preloaded_data.get(symbol, [])
        sym_last_date = existing_rows[-1][0] if existing_rows else "2026-01-01"

        df = fetch_candles_and_indicators(symbol, candle_count=120)
        if df is None or len(df) == 0:
            return symbol, sym_last_date, []

        new_array_rows = convert_df_to_array_rows(df)
        append_candidates = [r for r in new_array_rows if r[0] > sym_last_date]
        return symbol, sym_last_date, append_candidates

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(process_symbol, all_symbols))

    updated_count = 0
    new_dates_added = set()

    for symbol, sym_last_date, new_rows in results:
        if new_rows:
            updated_count += 1
            for r in new_rows:
                new_dates_added.add(r[0])
            
            existing = preloaded_data.get(symbol, [])
            combined = existing + new_rows
            preloaded_data[symbol] = combined
        elif symbol not in preloaded_data or not preloaded_data[symbol]:
            df_full = fetch_stock_ohlcv(symbol, candle_count=500)
            if df_full is not None and len(df_full) >= 1:
                df_full = calculate_full_indicators(df_full)
                df_full['Date'] = df_full.index if 'Date' not in df_full.columns else df_full['Date']
                df_full = df_full[df_full['Date'].astype(str) >= '2026-01-01'].copy()
                preloaded_data[symbol] = convert_df_to_array_rows(df_full)
                updated_count += 1

    if new_dates_added:
        sorted_new_dates = sorted(list(new_dates_added))
        print(f"[SUCCESS] Added {len(sorted_new_dates)} new trading day(s): {', '.join(sorted_new_dates)}")
    else:
        print("[INFO] No new dates to append (dataset is up-to-date).")

    payload = {
        "stocks": all_target_stocks,
        "preloaded_data": preloaded_data
    }

    temp_path = CHUNK_2026_CURR_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))

    if os.path.exists(CHUNK_2026_CURR_PATH):
        os.remove(CHUNK_2026_CURR_PATH)
    os.rename(temp_path, CHUNK_2026_CURR_PATH)

    final_size_mb = os.path.getsize(CHUNK_2026_CURR_PATH) / (1024 * 1024)
    print(f"[DONE] Saved 2026~current dataset ({final_size_mb:.2f} MB)")
    return True

if __name__ == "__main__":
    sync_current_year_chunk()
