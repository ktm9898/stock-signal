import os
import requests
import re
import json
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np

# Import unified indicator calculation formula from data_loader
from data_loader import calculate_full_indicators

def get_all_350_stocks():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # 1. KOSPI 200 (Top 200 by market cap: sosok=0, pages 1~4)
    kospi_stocks = []
    seen = set()
    for page in range(1, 5):
        url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page={page}"
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')
        for a in soup.select('a.tltle'):
            code_match = re.search(r'code=(\d+)', a['href'])
            if code_match:
                code = code_match.group(1).zfill(6)
                name = a.text.strip()
                if code not in seen and len(kospi_stocks) < 200:
                    seen.add(code)
                    kospi_stocks.append({"ticker": code, "name": name, "market": "KOSPI200"})

    # 2. KOSDAQ 150 (Top 150 by market cap: sosok=1, pages 1~3)
    kosdaq_stocks = []
    for page in range(1, 4):
        url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok=1&page={page}"
        res = requests.get(url, headers=headers, timeout=5)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')
        for a in soup.select('a.tltle'):
            code_match = re.search(r'code=(\d+)', a['href'])
            if code_match:
                code = code_match.group(1).zfill(6)
                name = a.text.strip()
                if code not in seen and len(kosdaq_stocks) < 150:
                    seen.add(code)
                    kosdaq_stocks.append({"ticker": code, "name": name, "market": "KOSDAQ150"})

    return kospi_stocks + kosdaq_stocks

def fetch_real_stock_ohlcv(ticker):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count=1250&requestType=0"
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
    if len(rows) > 30:
        df = pd.DataFrame(rows)
        # Use 100% unified KIS HTS calculation module matching screener.py
        df = calculate_full_indicators(df)
        
        result_rows = []
        for i in range(len(df)):
            result_rows.append({
                "date": df['Date'].iloc[i],
                "open": int(df['시가'].iloc[i]),
                "high": int(df['고가'].iloc[i]),
                "low": int(df['저가'].iloc[i]),
                "close": int(df['종가'].iloc[i]),
                "volume": int(df['거래량'].iloc[i]),
                "adx": round(float(df['adx'].iloc[i]), 1) if not np.isnan(df['adx'].iloc[i]) else 0.0,
                "minus_di": round(float(df['minus_di'].iloc[i]), 1) if not np.isnan(df['minus_di'].iloc[i]) else 0.0,
                "plus_di": round(float(df['plus_di'].iloc[i]), 1) if not np.isnan(df['plus_di'].iloc[i]) else 0.0,
                "rsi": round(float(df['rsi'].iloc[i]), 1) if not np.isnan(df['rsi'].iloc[i]) else 0.0,
                "bb_pct": round(float(df['b_band_pct'].iloc[i]), 2) if not np.isnan(df['b_band_pct'].iloc[i]) else 0.0,
                "macd": int(round(float(df['macd'].iloc[i]))) if not np.isnan(df['macd'].iloc[i]) else 0,
                "macd_osc": int(round(float(df['macd_osc'].iloc[i]))) if not np.isnan(df['macd_osc'].iloc[i]) else 0,
                "stoch_k": round(float(df['stoch_k'].iloc[i]), 1) if not np.isnan(df['stoch_k'].iloc[i]) else 0.0,
                "stoch_d": round(float(df['stoch_d'].iloc[i]), 1) if not np.isnan(df['stoch_d'].iloc[i]) else 0.0,
                "disparity20": round(float(df['disparity20'].iloc[i]), 1) if not np.isnan(df['disparity20'].iloc[i]) else 100.0,
                "volume_ratio": round(float(df['volume_ratio'].iloc[i]), 1) if not np.isnan(df['volume_ratio'].iloc[i]) else 100.0
            })
        return result_rows
    return []

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    stocks = get_all_350_stocks()
    print(f"Total stocks fetched: {len(stocks)}")

    representative_tickers = [
        "005930", "000660", "005935", "402340", "009150", "005380", "373220", "207940", "032830", "028260",
        "012450", "105560", "000270", "329180", "034020", "055550", "012330", "068270", "034730", "006400",
        "086790", "035420", "066570", "010120", "042660", "051910", "035720", "066970", "196170", "086520",
        "247540", "277810", "028300", "214150", "041510", "035900", "293490"
    ]

    real_data_store = {}
    for item in stocks:
        t = item['ticker']
        if t in representative_tickers or len(real_data_store) < 25:
            print(f"Fetching real 5Y data for {item['name']} ({t})...")
            rows = fetch_real_stock_ohlcv(t)
            if rows:
                real_data_store[t] = rows

    payload = {
        "stocks": stocks,
        "preloaded_data": real_data_store
    }

    with open("data/stocks_350_real.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print("Saved to data/stocks_350_real.json")
