import urllib.request
import xml.etree.ElementTree as ET
import pandas as pd
import numpy as np
import json
import os

def fetch_all_candles(ticker, count=3000):
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count={count}&requestType=0"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    content = urllib.request.urlopen(req, timeout=15).read().decode('euc-kr', errors='ignore')
    root = ET.fromstring(content)
    rows = []
    for item in root.findall('.//item'):
        data = item.attrib.get('data', '')
        if data:
            parts = data.split('|')
            if len(parts) >= 6:
                d_str, op, hp, lp, cp, vol = parts[:6]
                date_formatted = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
                rows.append({
                    "date": date_formatted,
                    "open": float(op), "high": float(hp), "low": float(lp), "close": float(cp), "volume": float(vol)
                })
    df = pd.DataFrame(rows)
    df = calculate_full_indicators(df)
    return df

def calculate_full_indicators(df):
    close = df['close']
    high = df['high']
    low = df['low']
    vol = df['volume']

    # RSI (14)
    diff = close.diff()
    up = diff.clip(lower=0)
    down = -diff.clip(upper=0)
    ema_up = up.ewm(com=13, adjust=False).mean()
    ema_down = down.ewm(com=13, adjust=False).mean()
    rs = ema_up / ema_down.replace(0, np.nan)
    df['rsi'] = (100 - (100 / (1 + rs))).fillna(50.0)

    # BB (20, 2)
    ma20 = close.rolling(20, min_periods=5).mean()
    std20 = close.rolling(20, min_periods=5).std().fillna(0)
    df['disparity20'] = ((close / ma20) * 100).fillna(100.0)
    upper = ma20 + (std20 * 2)
    lower = ma20 - (std20 * 2)
    denom = (upper - lower).replace(0, np.nan)
    df['b_band_pct'] = (((close - lower) / denom)).fillna(0.5)

    # MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['macd'] = (ema12 - ema26).fillna(0.0)

    # Stochastic (12, 5, 5)
    lowest_l = low.rolling(12, min_periods=5).min()
    highest_h = high.rolling(12, min_periods=5).max()
    denom_stoch = (highest_h - lowest_l).replace(0, np.nan)
    fast_k = (((close - lowest_l) / denom_stoch) * 100).fillna(50.0)
    df['stoch_k'] = fast_k.rolling(5, min_periods=1).mean().fillna(50.0)

    # Volume Ratio (20)
    vol_ma5 = vol.rolling(5, min_periods=1).mean()
    vol_ma20 = vol.rolling(20, min_periods=1).mean().replace(0, np.nan)
    df['volume_ratio'] = ((vol_ma5 / vol_ma20) * 100).fillna(100.0)

    # ADX (14)
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(com=13, adjust=False).mean().replace(0, np.nan)

    up_move = high - high.shift()
    down_move = low.shift() - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_di = (100 * (pd.Series(plus_dm).ewm(com=13, adjust=False).mean() / atr)).fillna(20.0)
    minus_di = (100 * (pd.Series(minus_dm).ewm(com=13, adjust=False).mean() / atr)).fillna(20.0)
    denom_di = (plus_di + minus_di).replace(0, np.nan)
    dx = (100 * ((plus_di - minus_di).abs() / denom_di)).fillna(20.0)
    df['adx'] = dx.ewm(com=13, adjust=False).mean().fillna(20.0)
    df['plus_di'] = plus_di
    df['minus_di'] = minus_di

    return df

def df_to_array(df):
    arr = []
    for _, r in df.iterrows():
        arr.append([
            r['date'],
            round(float(r['open']), 2),
            round(float(r['high']), 2),
            round(float(r['low']), 2),
            round(float(r['close']), 2),
            round(float(r['volume']), 0),
            round(float(r['adx']), 2),
            round(float(r['plus_di']), 2),
            round(float(r['minus_di']), 2),
            round(float(r['rsi']), 2),
            round(float(r['b_band_pct']), 4),
            round(float(r['macd']), 2),
            round(float(r['stoch_k']), 2),
            round(float(r['disparity20']), 2),
            round(float(r['volume_ratio']), 2)
        ])
    return arr

print("[1/4] Fetching 10-year candles for 069500 (KODEX 200) and 229200 (KODEX 코스닥150)...")
df_k = fetch_all_candles("069500", count=3000)
df_kq = fetch_all_candles("229200", count=3000)

rows_k = df_to_array(df_k)
rows_kq = df_to_array(df_kq)

print(f" -> 069500: {len(rows_k)} candles ({rows_k[0][0]} ~ {rows_k[-1][0]})")
print(f" -> 229200: {len(rows_kq)} candles ({rows_kq[0][0]} ~ {rows_kq[-1][0]})")

chunks = [
    ('data/history_2016_2020.json', '2016-01-01', '2020-12-31'),
    ('data/history_2021_2025.json', '2021-01-01', '2025-12-31'),
    ('data/history_2026_current.json', '2026-01-01', '2099-12-31')
]

for file_path, start_d, end_d in chunks:
    if not os.path.exists(file_path):
        print(f"[WARN] {file_path} does not exist, skipping.")
        continue
    print(f"[INFO] Updating {file_path} for range {start_d} ~ {end_d}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    sub_k = [r for r in rows_k if start_d <= r[0] <= end_d]
    sub_kq = [r for r in rows_kq if start_d <= r[0] <= end_d]
    
    data['preloaded_data']['069500'] = sub_k
    data['preloaded_data']['229200'] = sub_kq
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    print(f" -> Successfully updated {file_path}: 069500({len(sub_k)}), 229200({len(sub_kq)})")

print("\n[DONE] 10-year benchmark ETF dataset synchronization completed!")
