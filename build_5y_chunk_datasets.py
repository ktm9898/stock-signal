"""
Fast 5-Year Time-Partitioned Chunk Datasets Builder:
1. data/history_2011_2015.json (2011-01-03 ~ 2015-12-30) -> Batch downloaded via yfinance/Naver
2. data/history_2016_2020.json (2016-01-04 ~ 2020-12-30) -> Sliced from verified 2016~ data
3. data/history_2021_2025.json (2021-01-04 ~ 2025-12-30) -> Sliced from verified 2016~ data
4. data/history_2026_current.json (2026-01-02 ~ 2026-08-21...) -> Sliced from verified 2016~ data
Each file contains integrated KOSPI 200 + KOSDAQ 150 + Benchmarks (KOSPI, KOSDAQ).
"""

import os
import sys
import json
import pandas as pd
import numpy as np
import yfinance as yf

from data_loader import (
    calculate_full_indicators,
    get_kospi200_tickers,
    get_kosdaq150_tickers
)
from update_backtest_data import convert_df_to_array_rows

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

CHUNK_2011_2015_PATH = os.path.join(DATA_DIR, "history_2011_2015.json")
CHUNK_2016_2020_PATH = os.path.join(DATA_DIR, "history_2016_2020.json")
CHUNK_2021_2025_PATH = os.path.join(DATA_DIR, "history_2021_2025.json")
CHUNK_2026_CURR_PATH = os.path.join(DATA_DIR, "history_2026_current.json")

KOSPI200_OLD_PATH = os.path.join(DATA_DIR, "stocks_kospi200_real.json")
KOSDAQ150_OLD_PATH = os.path.join(DATA_DIR, "stocks_kosdaq150_real.json")

def build_all_chunks_fast():
    print("=== [1/3] Loading 2016~2026 Verified Base Datasets ===")
    kospi_items = get_kospi200_tickers()[:200]
    kosdaq_items = get_kosdaq150_tickers()[:150]
    all_stocks = kospi_items + kosdaq_items
    
    # Read existing verified 2016-2026 datasets
    preloaded_2016_all = {}
    if os.path.exists(KOSPI200_OLD_PATH):
        with open(KOSPI200_OLD_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
            preloaded_2016_all.update(d.get("preloaded_data", {}))
            
    if os.path.exists(KOSDAQ150_OLD_PATH):
        with open(KOSDAQ150_OLD_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
            preloaded_2016_all.update(d.get("preloaded_data", {}))
            
    print(f"Loaded {len(preloaded_2016_all)} symbols for 2016~2026.")

    # Slice 2016~2020, 2021~2025, 2026~current
    data_2016_2020 = {}
    data_2021_2025 = {}
    data_2026_curr = {}
    
    for sym, rows in preloaded_2016_all.items():
        data_2016_2020[sym] = [r for r in rows if '2016-01-01' <= r[0] <= '2020-12-31']
        data_2021_2025[sym] = [r for r in rows if '2021-01-01' <= r[0] <= '2025-12-31']
        data_2026_curr[sym] = [r for r in rows if r[0] >= '2026-01-01']

    # Step 2: Batch download 2011~2015 historical data via yfinance
    print("\n=== [2/3] Batch Downloading 2011~2015 Data for 350 Symbols ===")
    sym_map = {}
    for item in all_stocks:
        t = item['ticker']
        m = item.get('market', '')
        suffix = ".KQ" if m == "KOSDAQ150" else ".KS"
        sym_map[f"{t}{suffix}"] = t
    sym_map["^KS11"] = "KOSPI"
    sym_map["^KQ11"] = "KOSDAQ"

    yf_ticker_list = list(sym_map.keys())
    print(f"Downloading batch of {len(yf_ticker_list)} tickers from yfinance (start=2010-06-01, end=2015-12-31)...")
    
    try:
        batch_df = yf.download(
            yf_ticker_list,
            start="2010-06-01",
            end="2015-12-31",
            group_by='ticker',
            progress=True,
            threads=True
        )
    except Exception as e:
        print(f"[WARN] yfinance batch download failed: {e}")
        batch_df = None

    data_2011_2015 = {}
    if batch_df is not None:
        print("Calculating technical indicators for 2011~2015 data...")
        for yf_sym, clean_sym in sym_map.items():
            try:
                if yf_sym in batch_df.columns.levels[0]:
                    df_sym = batch_df[yf_sym].dropna(how='all').copy()
                else:
                    df_sym = pd.DataFrame()
                    
                if len(df_sym) >= 30:
                    df_sym = df_sym.rename(columns={
                        'Open': '시가', 'High': '고가', 'Low': '저가', 'Close': '종가', 'Volume': '거래량'
                    })
                    df_sym = df_sym.dropna(subset=['시가', '고가', '저가', '종가'])
                    df_sym = calculate_full_indicators(df_sym)
                    df_sym['Date'] = df_sym.index.strftime('%Y-%m-%d')
                    df_sym = df_sym[(df_sym['Date'] >= '2011-01-01') & (df_sym['Date'] <= '2015-12-31')].copy()
                    if len(df_sym) > 0:
                        data_2011_2015[clean_sym] = convert_df_to_array_rows(df_sym)
            except Exception:
                pass

    print(f"Constructed 2011~2015 dataset for {len(data_2011_2015)} symbols.")

    # Step 3: Save all 4 files
    print("\n=== [3/3] Saving 4 Chunk Files to disk ===")
    chunks = [
        (CHUNK_2011_2015_PATH, data_2011_2015, "2011~2015"),
        (CHUNK_2016_2020_PATH, data_2016_2020, "2016~2020"),
        (CHUNK_2021_2025_PATH, data_2021_2025, "2021~2025"),
        (CHUNK_2026_CURR_PATH, data_2026_curr, "2026~Current")
    ]
    
    for path, d_dict, label in chunks:
        payload = {
            "stocks": all_stocks,
            "preloaded_data": d_dict
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
        size_mb = os.path.getsize(path) / (1024 * 1024)
        
        min_d, max_d = '9999-99-99', '0000-00-00'
        for sym, r_list in d_dict.items():
            if r_list:
                if r_list[0][0] < min_d: min_d = r_list[0][0]
                if r_list[-1][0] > max_d: max_d = r_list[-1][0]
        print(f"[{label}] Saved {path} ({size_mb:.2f} MB) | Symbols: {len(d_dict)} | Span: {min_d} ~ {max_d}")

    # Save stocks_350.json
    with open(os.path.join(DATA_DIR, "stocks_350.json"), "w", encoding="utf-8") as f:
        json.dump(all_stocks, f, ensure_ascii=False, indent=2)
        
    print("\n[ALL COMPLETE] 4-Chunk Partitioned Architecture Successfully Built!")

if __name__ == "__main__":
    build_all_chunks_fast()
