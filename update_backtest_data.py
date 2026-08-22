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

# Import unified indicator calculation formula and ticker scrapers from data_loader
from data_loader import (
    calculate_full_indicators,
    get_kospi200_tickers,
    get_kosdaq150_tickers,
    fetch_stock_5y_ohlcv
)

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
    except Exception as e:
        return None

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
    """
    Perform intelligent incremental update on data/stocks_350_real.json.
    - Synchronizes constituent stock universe with live KOSPI 200 & KOSDAQ 150.
    - Auto-downloads full 5-year history for newly added index constituents.
    - Prunes dropped stocks to maintain clean 350-stock target universe.
    - Incrementally updates recent trading days for existing constituents.
    """
    if not os.path.exists(STOCKS_350_REAL_PATH):
        print(f"[ERROR] Target dataset not found: {STOCKS_350_REAL_PATH}")
        return False

    print("[INFO] Loading existing backtest dataset...")
    with open(STOCKS_350_REAL_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    existing_stocks_meta = data.get("stocks", [])
    preloaded_data = data.get("preloaded_data", {})

    # 1. Fetch current live constituent universe (KOSPI 200 + KOSDAQ 150)
    print("[INFO] Checking live index constituents (KOSPI 200 + KOSDAQ 150)...")
    kospi_items = get_kospi200_tickers()
    kosdaq_items = get_kosdaq150_tickers()

    target_stocks_meta = []
    if len(kospi_items) >= 100 and len(kosdaq_items) >= 75:
        target_stocks_meta = kospi_items[:200] + kosdaq_items[:150]
        print(f" -> Live target constituents: KOSPI 200 ({len(kospi_items[:200])}), KOSDAQ 150 ({len(kosdaq_items[:150])}) = Total {len(target_stocks_meta)} stocks.")
    else:
        print("[WARN] Live constituent fetch returned incomplete list. Keeping existing metadata as fallback.")
        target_stocks_meta = existing_stocks_meta

    target_tickers = [s['ticker'] for s in target_stocks_meta]
    target_ticker_set = set(target_tickers)
    existing_ticker_set = set([k for k in preloaded_data.keys() if k not in ("KOSPI", "KOSDAQ")])

    # Detect rebalanced additions and removals
    new_tickers = target_ticker_set - existing_ticker_set
    removed_tickers = existing_ticker_set - target_ticker_set

    if new_tickers:
        print(f"[INFO] [NEW CONSTITUENTS] Detected {len(new_tickers)} NEW index constituent(s): {', '.join(sorted(list(new_tickers)))}")
        end_date = datetime.datetime.now().strftime("%Y%m%d")
        start_date = (datetime.datetime.now() - datetime.timedelta(days=365 * 5 + 30)).strftime("%Y%m%d")
        
        for new_t in new_tickers:
            name = next((s['name'] for s in target_stocks_meta if s['ticker'] == new_t), new_t)
            print(f"  -> Fetching full 5-year history for new constituent: {name} ({new_t})...")
            try:
                df_new = fetch_stock_5y_ohlcv(new_t, start_date, end_date)
                if df_new is not None and len(df_new) >= 1:
                    df_new = calculate_full_indicators(df_new)
                    df_new['Date'] = df_new.index if 'Date' not in df_new.columns else df_new['Date']
                    preloaded_data[new_t] = convert_df_to_array_rows(df_new)
                    print(f"     Successfully loaded {len(preloaded_data[new_t])} historical candles for {name}.")
                else:
                    preloaded_data[new_t] = []
            except Exception as err:
                print(f"     [WARN] Failed to fetch full 5Y data for {new_t}: {err}")
                preloaded_data[new_t] = []

    if removed_tickers:
        print(f"[INFO] [PRUNE DROPPED] Pruning {len(removed_tickers)} dropped constituent(s) to maintain clean 350-stock universe: {', '.join(sorted(list(removed_tickers)))}")
        for rem_t in removed_tickers:
            preloaded_data.pop(rem_t, None)

    # 2. Incremental update for all active targets + benchmarks
    all_active_symbols = list(set(target_tickers + ["KOSPI", "KOSDAQ"]))
    print(f"[INFO] Syncing daily candles across {len(all_active_symbols)} active symbols...")

    # Quick pre-check on leading ticker to avoid unnecessary full network calls
    sample_ticker = "005930" if "005930" in preloaded_data else all_active_symbols[0]
    sample_history = preloaded_data.get(sample_ticker, [])
    last_known_date = sample_history[-1][0] if sample_history else "2021-01-01"
    print(f"[INFO] Current dataset last trading date: {last_known_date}")

    sample_df = fetch_candles_and_indicators(sample_ticker, candle_count=30)
    if sample_df is not None and len(sample_df) > 0:
        latest_market_date = sample_df['Date'].iloc[-1]
        if latest_market_date <= last_known_date and not new_tickers:
            print(f"[INFO] Fast-Exit: Market data is already up-to-date ({last_known_date}) and no index changes. Skipping sync.")
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
        append_candidates = [r for r in new_array_rows if r[0] > sym_last_date]
        return symbol, sym_last_date, append_candidates

    print("[INFO] Fetching latest candles in parallel (16 threads)...")
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(process_symbol, all_active_symbols))

    for symbol, sym_last_date, new_rows in results:
        if new_rows:
            updated_count += 1
            for r in new_rows:
                new_dates_added.add(r[0])
            
            existing = preloaded_data.get(symbol, [])
            combined = existing + new_rows
            if len(combined) > MAX_WINDOW_DAYS:
                combined = combined[-MAX_WINDOW_DAYS:]
            preloaded_data[symbol] = combined

    if new_dates_added:
        sorted_new_dates = sorted(list(new_dates_added))
        print(f"[SUCCESS] Added {len(sorted_new_dates)} new trading day(s): {', '.join(sorted_new_dates)}")
        print(f"[INFO] Updated {updated_count} symbols successfully.")
    else:
        print("[INFO] No new dates added for existing symbols.")

    # Save to JSON
    payload = {
        "stocks": target_stocks_meta,
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
