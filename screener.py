"""
KOSPI 200 Stock Screener & Technical Indicator Engine
Calculates ADX, +DI, -DI, RSI, and Moving Averages for KOSPI 200 components.
"""

import sys
import datetime
import os
import re
import json
import pandas as pd
import numpy as np
import requests

try:
    from pykrx import stock
    import ta
except ImportError:
    print("[WARN] Required packages ('pykrx', 'ta', 'pandas') missing. Install via pip.")

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

def get_kospi200_tickers():
    """Retrieve KOSPI 200 list of tickers and names (PyKRX with Naver Finance fallback)."""
    items = []
    
    # 1. Try PyKRX
    try:
        tickers = stock.get_index_portfolio_deposit_file("1028")
        if tickers and len(tickers) > 0:
            for ticker in tickers:
                name = stock.get_market_ticker_name(ticker)
                items.append({"ticker": ticker, "name": name})
            if len(items) >= 100:
                return items
    except Exception as e:
        print(f"[WARN] PyKRX get_index_portfolio_deposit_file failed: {e}")

    # 2. Fallback: Naver Finance KOSPI 200 Scraping
    print("[INFO] Using Naver Finance fallback to fetch KOSPI 200 list...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        for page in range(1, 21):
            url = f"https://finance.naver.com/sise/entryJongmok.naver?page={page}"
            res = requests.get(url, headers=headers, timeout=5)
            if BeautifulSoup:
                soup = BeautifulSoup(res.text, "html.parser")
                tds = soup.find_all("td", class_="ctg")
                for td in tds:
                    a = td.find("a")
                    if a and 'code=' in a.get('href', ''):
                        match = re.search(r'code=(\d+)', a['href'])
                        if match:
                            items.append({"ticker": match.group(1), "name": a.text.strip()})
            else:
                matches = re.findall(r'href="/item/main\.naver\?code=(\d+)">(.*?)</a>', res.text)
                for code, name in matches:
                    items.append({"ticker": code, "name": name.strip()})
    except Exception as e:
        print(f"[ERROR] Naver Finance KOSPI 200 fallback failed: {e}")

    return items

def get_ohlcv_data(ticker, start_date, end_date):
    """Retrieve OHLCV DataFrame for a ticker (PyKRX with Naver Finance fallback)."""
    # 1. Try PyKRX
    try:
        df = stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
        if df is not None and len(df) >= 30 and '고가' in df.columns:
            return df
    except Exception:
        pass

    # 2. Fallback: Naver Finance API
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        url = f"https://api.finance.naver.com/siseJson.naver?symbol={ticker}&requestType=1&startTime={start_date}&endTime={end_date}&timeframe=day"
        res = requests.get(url, headers=headers, timeout=5)
        clean_text = res.text.strip().replace("'", '"')
        data = json.loads(clean_text)
        if len(data) > 1:
            headers_row = [c.strip() for c in data[0]]
            df = pd.DataFrame(data[1:], columns=headers_row)
            df.rename(columns={'날짜': 'Date'}, inplace=True)
            for col in ['시가', '고가', '저가', '종가', '거래량']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
    except Exception:
        pass

    return pd.DataFrame()

def calculate_indicators(df):
    """
    Calculate ADX(14), +DI, -DI, RSI(14), 5MA, 20MA for OHLCV dataframe.
    Columns expected: ['고가', '저가', '종가', '거래량']
    """
    if len(df) < 30 or not {'고가', '저가', '종가', '거래량'}.issubset(df.columns):
        return df

    # ADX & DI
    adx_ind = ta.trend.ADXIndicator(high=df['고가'], low=df['저가'], close=df['종가'], window=14)
    df['adx'] = adx_ind.adx()
    df['plus_di'] = adx_ind.adx_pos()
    df['minus_di'] = adx_ind.adx_neg()

    # RSI
    rsi_ind = ta.momentum.RSIIndicator(close=df['종가'], window=14)
    df['rsi'] = rsi_ind.rsi()

    # Moving Averages
    df['ma5'] = df['종가'].rolling(window=5).mean()
    df['ma20'] = df['종가'].rolling(window=20).mean()

    return df

def evaluate_buy_signal(df):
    """
    Evaluate ADX Reversal Buy Signal.
    Condition: ADX >= 30 AND Prev(-DI) > Prev(ADX) AND Curr(-DI) <= Curr(ADX)
    Priority Rating:
      - Tier 1: Buy Signal + RSI <= 35
      - Tier 2: Buy Signal + Volume >= 1.5x 5-day avg volume
      - Tier 3: General Buy Signal
    """
    if len(df) < 2 or 'adx' not in df.columns:
        return None

    prev_adx, curr_adx = df['adx'].iloc[-2], df['adx'].iloc[-1]
    prev_mdi, curr_mdi = df['minus_di'].iloc[-2], df['minus_di'].iloc[-1]
    curr_rsi = df['rsi'].iloc[-1]
    curr_vol = df['거래량'].iloc[-1]
    avg_vol5 = df['거래량'].iloc[-6:-1].mean() if len(df) >= 6 else curr_vol

    # Base Buy Signal
    is_buy = (curr_adx >= 30) and (prev_mdi > prev_adx) and (curr_mdi <= curr_adx)

    if not is_buy:
        return None

    priority = "Tier 3 (일반)"
    score = 3
    if curr_rsi <= 35:
        priority = "Tier 1 (최우선 과매도)"
        score = 1
    elif avg_vol5 > 0 and (curr_vol >= avg_vol5 * 1.5):
        priority = "Tier 2 (거래량 급증)"
        score = 2

    return {
        "is_buy": True,
        "priority": priority,
        "score": score,
        "adx": round(curr_adx, 2),
        "minus_di": round(curr_mdi, 2),
        "plus_di": round(df['plus_di'].iloc[-1], 2),
        "rsi": round(curr_rsi, 2) if not np.isnan(curr_rsi) else None,
        "close": int(df['종가'].iloc[-1])
    }

def post_to_google_sheets(url, action, data):
    """Post screening results to Google Apps Script Web App."""
    payload = {"action": action, **data}
    try:
        res = requests.post(url, json=payload, timeout=15)
        print(f" -> GAS Response: Status {res.status_code} | {res.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Failed to post to Google Sheets: {e}")

if __name__ == "__main__":
    print("[INFO] KOSPI 200 Stock Signal Screener Engine Starting...")
    
    gas_url = os.environ.get("GAS_WEBAPP_URL", "")

    # 1. Fetch KOSPI 200 Tickers
    print("[1/3] Fetching KOSPI 200 component tickers...")
    items = get_kospi200_tickers()
    print(f" -> Found {len(items)} tickers.")

    buy_candidates = []
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime("%Y%m%d")

    # 2. Screen Buy Signals across all KOSPI 200
    print("[2/3] Calculating indicators and screening buy signals...")
    for idx, item in enumerate(items):
        ticker = item['ticker']
        name = item['name']
        try:
            df = get_ohlcv_data(ticker, start_date, end_date)
            if len(df) < 30:
                continue
            df = calculate_indicators(df)
            buy_res = evaluate_buy_signal(df)
            if buy_res:
                buy_res['ticker'] = ticker
                buy_res['name'] = name
                buy_candidates.append(buy_res)
                print(f"  🔥 [BUY SIGNAL] {name} ({ticker}) - {buy_res['priority']} | ADX: {buy_res['adx']} | RSI: {buy_res['rsi']}")
        except Exception as e:
            continue

    # Sort buy candidates by priority score (Tier 1 -> Tier 2 -> Tier 3)
    buy_candidates.sort(key=lambda x: x['score'])
    print(f" -> Found {len(buy_candidates)} buy candidate stocks.")

    # 3. Post to Google Sheets API
    if gas_url:
        print("[3/3] Posting screening results to Google Sheets...")
        post_to_google_sheets(gas_url, "update_buy_candidates", {"candidates": buy_candidates})
    else:
        print("[WARN] GAS_WEBAPP_URL environment variable is not set. Results printed above.")

    print("[INFO] Screener Execution Completed.")
