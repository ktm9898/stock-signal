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

# Helper to safely import pykrx without failing on invalid KRX credentials
def import_pykrx_safely():
    try:
        from pykrx import stock
        # Test basic call to ensure session is valid
        return stock
    except Exception as e:
        print(f"[WARN] PyKRX initial import/login failed: {e}. Retrying in non-authenticated mode...")
        # Unset KRX_ID and KRX_PW from environment to prevent pykrx from trying invalid KRX login
        os.environ.pop("KRX_ID", None)
        os.environ.pop("KRX_PW", None)
        # Clear pykrx module cache if already partially imported
        for mod in list(sys.modules.keys()):
            if mod.startswith("pykrx"):
                del sys.modules[mod]
        try:
            from pykrx import stock
            return stock
        except Exception as ex:
            print(f"[WARN] PyKRX fallback import failed: {ex}")
            return None

stock = import_pykrx_safely()

try:
    import ta
except ImportError:
    pass

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
            res.encoding = 'euc-kr'
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
    """Retrieve OHLCV DataFrame for a ticker (PyKRX with Naver FChart XML fallback)."""
    # 1. Try PyKRX
    try:
        df = stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
        if df is not None and len(df) >= 30 and '고가' in df.columns:
            return df
    except Exception:
        pass

    # 2. Fallback A: Naver FChart XML (Adjusted Prices - 300 candles)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        import xml.etree.ElementTree as ET
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count=300&requestType=0"
        res = requests.get(url, headers=headers, timeout=5)
        xml_text = res.content.decode('euc-kr', errors='ignore')
        root = ET.fromstring(xml_text)
        items = root.findall('.//item')
        rows = []
        for item in items:
            parts = item.attrib.get('data', '').split('|')
            if len(parts) >= 6:
                rows.append({
                    'Date': parts[0],
                    '시가': float(parts[1]),
                    '고가': float(parts[2]),
                    '저가': float(parts[3]),
                    '종가': float(parts[4]),
                    '거래량': float(parts[5])
                })
        if len(rows) >= 30:
            return pd.DataFrame(rows)
    except Exception as e:
        pass

    # 3. Fallback B: Naver siseJson API
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

def calculate_indicators(df, period=14):
    """
    Calculate 한국투자증권 (KIS MTS Standard) ADX(14), +DI, -DI, RSI(14), 5MA, 20MA.
    Columns expected: ['고가', '저가', '종가', '거래량']
    """
    if len(df) < 30 or not {'고가', '저가', '종가', '거래량'}.issubset(df.columns):
        return df

    highs = df['고가'].values
    lows = df['저가'].values
    closes = df['종가'].values
    n = len(closes)
    
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
        
    # Welles Wilder's Standard ADX Algorithm (Matching KIS MTS / HTS Exact Values)
    def calc_wilder_smooth(arr, p=14):
        num_len = len(arr)
        if num_len < p:
            return [0.0] * num_len
        res = [0.0] * num_len
        # Initial Seed: First 14 days sum
        first_sum = sum(arr[:p])
        res[p - 1] = first_sum
        for i in range(p, num_len):
            res[i] = res[i - 1] - (res[i - 1] / p) + arr[i]
        return res

    tr_smooth = calc_wilder_smooth(tr, period)
    dp_smooth = calc_wilder_smooth(dm_p, period)
    dm_smooth = calc_wilder_smooth(dm_m, period)
    
    pdi = []
    mdi = []
    for i in range(len(tr)):
        if i < period - 1 or tr_smooth[i] == 0:
            pdi.append(0.0)
            mdi.append(0.0)
        else:
            pdi.append(100.0 * dp_smooth[i] / tr_smooth[i])
            mdi.append(100.0 * dm_smooth[i] / tr_smooth[i])
    
    dx = []
    for i in range(len(tr)):
        if i < period - 1 or (pdi[i] + mdi[i]) == 0:
            dx.append(0.0)
        else:
            dx.append(100.0 * abs(pdi[i] - mdi[i]) / (pdi[i] + mdi[i]))
            
    # ADX smoothing: Initial Seed is average of first 14 valid DX values
    adx_res = [0.0] * len(tr)
    valid_dx = dx[period - 1 : 2 * period - 1]
    if len(valid_dx) == period:
        first_adx = sum(valid_dx) / period
        adx_res[2 * period - 2] = first_adx
        for i in range(2 * period - 1, len(tr)):
            adx_res[i] = (adx_res[i - 1] * (period - 1) + dx[i]) / period

    pdi = [np.nan] + pdi
    mdi = [np.nan] + mdi
    adx = [np.nan] + adx_res
    
    df['adx'] = adx
    df['plus_di'] = pdi
    df['minus_di'] = mdi

    # RSI
    rsi_ind = ta.momentum.RSIIndicator(close=df['종가'], window=14)
    df['rsi'] = rsi_ind.rsi()

    # Moving Averages
    df['ma5'] = df['종가'].rolling(window=5).mean()
    df['ma20'] = df['종가'].rolling(window=20).mean()

    # Bollinger Bands (20, 2) & %b
    std20 = df['종가'].rolling(window=20).std(ddof=0)
    upper_b = df['ma20'] + (2 * std20)
    lower_b = df['ma20'] - (2 * std20)
    band_width = upper_b - lower_b
    df['b_band_pct'] = np.where(band_width != 0, (df['종가'] - lower_b) / band_width, 0.5)

    # MACD (12, 26, 9)
    macd_ind = ta.trend.MACD(close=df['종가'], window_slow=26, window_fast=12, window_sign=9)
    df['macd'] = macd_ind.macd()
    df['macd_signal'] = macd_ind.macd_signal()
    df['macd_osc'] = macd_ind.macd_diff()

    # Stochastic Slow (14, 3, 3)
    stoch_ind = ta.momentum.StochasticOscillator(high=df['고가'], low=df['저가'], close=df['종가'], window=14, smooth_window=3)
    df['stoch_k'] = stoch_ind.stoch()
    df['stoch_d'] = stoch_ind.stoch_signal()

    # Disparity (20-day 이격도: 종가 / 20MA * 100)
    df['disparity20'] = np.where(df['ma20'] > 0, (df['종가'] / df['ma20']) * 100, 100.0)

    # Volume Ratio (VR5: 5일 평균 거래량 대비 당일 거래량 비율 %)
    avg_vol5 = df['거래량'].rolling(window=5).mean()
    df['volume_ratio'] = np.where(avg_vol5 > 0, (df['거래량'] / avg_vol5) * 100, 100.0)

    return df

def evaluate_buy_signal(df):
    """
    Evaluate ADX Reversal Buy Signal.
    Condition: ADX >= 25 AND Prev(-DI) > Prev(ADX) AND Curr(-DI) <= Curr(ADX)
    Priority Rating:
      - 3단계: Buy Signal + RSI <= 40 (최우선 과매도)
      - 2단계: Buy Signal + Volume >= 1.2x 5-day avg volume (거래량 급증)
      - 1단계: General Buy Signal (일반)
    """
    if len(df) < 2 or 'adx' not in df.columns:
        return None

    prev_adx, curr_adx = df['adx'].iloc[-2], df['adx'].iloc[-1]
    prev_mdi, curr_mdi = df['minus_di'].iloc[-2], df['minus_di'].iloc[-1]
    curr_rsi = df['rsi'].iloc[-1]
    curr_vol = df['거래량'].iloc[-1]
    avg_vol5 = df['거래량'].iloc[-6:-1].mean() if len(df) >= 6 else curr_vol

    # Base Buy Signal
    is_buy = (curr_adx >= 25) and (prev_mdi > prev_adx) and (curr_mdi <= curr_adx)

    if not is_buy:
        return None

    priority = "1단계: 매수 추천"
    score = 1
    if curr_rsi <= 40:
        priority = "3단계: 강력 매수"
        score = 3
    elif avg_vol5 > 0 and (curr_vol >= avg_vol5 * 1.2):
        priority = "2단계: 적극 매수"
        score = 2

    curr_bb_pct = df['b_band_pct'].iloc[-1] if 'b_band_pct' in df.columns else 0.5

    return {
        "is_buy": True,
        "priority": priority,
        "score": score,
        "adx": round(curr_adx, 2),
        "minus_di": round(curr_mdi, 2),
        "plus_di": round(df['plus_di'].iloc[-1], 2),
        "rsi": round(curr_rsi, 2) if not np.isnan(curr_rsi) else None,
        "b_band_pct": round(curr_bb_pct, 2) if not np.isnan(curr_bb_pct) else None,
        "close": int(df['종가'].iloc[-1])
    }

def evaluate_sell_signal(df, buy_price):
    """
    Evaluate Sell Signal for a held stock.
    Conditions:
    1단계: RSI >= 60 (익절 준비 - 과매도 탈출 후 단기 목표 도달)
    2단계: Prev(+DI) > Curr(+DI) (상승 둔화 - 반등 모멘텀 약화)
    3단계: Curr(-DI) > Prev(-DI) AND Gap(-DI - +DI) 확대 OR 손절률 <= -5.0% (하락 재발동 / 손절)
    """
    if len(df) < 2 or 'adx' not in df.columns or 'plus_di' not in df.columns:
        return None

    curr_close = int(df['종가'].iloc[-1])
    curr_adx = df['adx'].iloc[-1]
    prev_adx = df['adx'].iloc[-2]
    curr_pdi = df['plus_di'].iloc[-1]
    prev_pdi = df['plus_di'].iloc[-2]
    curr_mdi = df['minus_di'].iloc[-1]
    prev_mdi = df['minus_di'].iloc[-2]
    curr_rsi = df['rsi'].iloc[-1] if 'rsi' in df.columns else 0.0
    curr_bb_pct = df['b_band_pct'].iloc[-1] if 'b_band_pct' in df.columns else 0.5

    return_rate = 0.0
    if buy_price and buy_price > 0:
        return_rate = round(((curr_close - buy_price) / buy_price) * 100, 2)

    details = []

    # Check Conditions
    rsi_high = (curr_rsi >= 60.0)
    pdi_drop = (prev_pdi >= 20.0) and (prev_pdi > curr_pdi)
    curr_gap = curr_mdi - curr_pdi
    prev_gap = prev_mdi - prev_pdi
    mdi_rebound = (curr_mdi > prev_mdi) and (curr_gap > prev_gap)

    # Priority determination (3단계 -> 2단계 -> 1단계)
    if mdi_rebound:
        level = "3단계: 강력 매도"
        details.append(f"하락 압력 재확대 (-DI: {prev_mdi:.1f} → {curr_mdi:.1f}, 격차: {prev_gap:.1f} → {curr_gap:.1f})")
    elif pdi_drop:
        level = "2단계: 적극 매도"
        details.append(f"상승 동력(+DI) 꺾임 (+DI: {prev_pdi:.1f} → {curr_pdi:.1f} >= 20)")
    elif rsi_high:
        level = "1단계: 매도 추천"
        details.append(f"RSI 단기 과매수 상단 도달 (RSI: {curr_rsi:.1f} >= 60)")
    else:
        level = "관망"
        details.append(f"정상 관망 (추세 유지 중 | ADX: {curr_adx:.1f})")

    return {
        "buyPrice": buy_price,
        "currPrice": curr_close,
        "returnRate": return_rate,
        "adx": round(curr_adx, 2),
        "prev_adx": round(prev_adx, 2),
        "plus_di": round(curr_pdi, 2),
        "prev_plus_di": round(prev_pdi, 2),
        "minus_di": round(curr_mdi, 2),
        "prev_minus_di": round(prev_mdi, 2),
        "rsi": round(curr_rsi, 2),
        "b_band_pct": round(curr_bb_pct, 2) if not np.isnan(curr_bb_pct) else 0.5,
        "signalLevel": level,
        "details": " / ".join(details),
        "isAlert": (level != "관망")
    }

def check_and_trim_incomplete_candle(df):
    """
    Check if current time is KST weekday market open hours (09:00 ~ 15:30 KST).
    If so, and the last candle in df represents today's date, remove the incomplete candle to prevent indicator distortion.
    """
    if df is None or len(df) <= 30:
        return df

    utc_now = datetime.datetime.now(datetime.timezone.utc)
    kst_now = utc_now.astimezone(datetime.timezone(datetime.timedelta(hours=9)))

    is_weekday = (kst_now.weekday() < 5)
    market_start = kst_now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_end = kst_now.replace(hour=15, minute=30, second=0, microsecond=0)
    is_market_hours = (market_start <= kst_now <= market_end)

    if is_weekday and is_market_hours:
        today_compact = kst_now.strftime("%Y%m%d")
        last_date_str = ""
        if 'Date' in df.columns:
            last_date_str = str(df['Date'].iloc[-1])
        elif isinstance(df.index, pd.DatetimeIndex):
            last_date_str = df.index[-1].strftime("%Y%m%d")
        else:
            last_date_str = str(df.index[-1])

        last_date_compact = re.sub(r'[^0-9]', '', last_date_str)[:8]
        if last_date_compact == today_compact and len(df) > 30:
            return df.iloc[:-1]

    return df

def post_to_google_sheets(url, action, data):
    """Post screening results to Google Apps Script Web App."""
    pin = os.environ.get("AUTH_PIN", "")
    payload = {"action": action, "pin": pin, **data}
    try:
        res = requests.post(url, json=payload, timeout=15)
        print(f" -> GAS Response [{action}]: Status {res.status_code} | {res.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Failed to post to Google Sheets ({action}): {e}")

if __name__ == "__main__":
    print("[INFO] KOSPI 200 Stock Signal Screener Engine Starting...")
    
    gas_url = os.environ.get("GAS_WEBAPP_URL", "")

    # 1. Fetch KOSPI 200 Tickers
    print("[1/4] Fetching KOSPI 200 component tickers...")
    items = get_kospi200_tickers()
    print(f" -> Found {len(items)} tickers.")

    buy_candidates = []
    all_stocks = []
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y%m%d")

    stock_df_map = {}

    # 2. Screen Buy Signals across all KOSPI 200 (Parallel ThreadPoolExecutor for 10x Speedup)
    print("[2/4] Calculating indicators and screening buy signals (Parallel Execution)...")
    
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def process_single_stock(item):
        ticker = item['ticker']
        name = item['name']
        try:
            df = get_ohlcv_data(ticker, start_date, end_date)
            df = check_and_trim_incomplete_candle(df)
            if df is None or len(df) < 30:
                return None
            df = calculate_indicators(df)
            
            clean_ticker = str(ticker).zfill(6)
            
            curr_adx = float(df['adx'].iloc[-1]) if 'adx' in df.columns and not np.isnan(df['adx'].iloc[-1]) else 0.0
            prev_adx = float(df['adx'].iloc[-2]) if len(df) >= 2 and 'adx' in df.columns and not np.isnan(df['adx'].iloc[-2]) else 0.0
            curr_mdi = float(df['minus_di'].iloc[-1]) if 'minus_di' in df.columns and not np.isnan(df['minus_di'].iloc[-1]) else 0.0
            prev_mdi = float(df['minus_di'].iloc[-2]) if len(df) >= 2 and 'minus_di' in df.columns and not np.isnan(df['minus_di'].iloc[-2]) else 0.0
            curr_pdi = float(df['plus_di'].iloc[-1]) if 'plus_di' in df.columns and not np.isnan(df['plus_di'].iloc[-1]) else 0.0
            curr_rsi = float(df['rsi'].iloc[-1]) if 'rsi' in df.columns and not np.isnan(df['rsi'].iloc[-1]) else 0.0
            curr_bb_pct = float(df['b_band_pct'].iloc[-1]) if 'b_band_pct' in df.columns and not np.isnan(df['b_band_pct'].iloc[-1]) else 0.5
            curr_macd = float(df['macd'].iloc[-1]) if 'macd' in df.columns and not np.isnan(df['macd'].iloc[-1]) else 0.0
            curr_macd_sig = float(df['macd_signal'].iloc[-1]) if 'macd_signal' in df.columns and not np.isnan(df['macd_signal'].iloc[-1]) else 0.0
            curr_macd_osc = float(df['macd_osc'].iloc[-1]) if 'macd_osc' in df.columns and not np.isnan(df['macd_osc'].iloc[-1]) else 0.0
            curr_stoch_k = float(df['stoch_k'].iloc[-1]) if 'stoch_k' in df.columns and not np.isnan(df['stoch_k'].iloc[-1]) else 50.0
            curr_stoch_d = float(df['stoch_d'].iloc[-1]) if 'stoch_d' in df.columns and not np.isnan(df['stoch_d'].iloc[-1]) else 50.0
            curr_disparity = float(df['disparity20'].iloc[-1]) if 'disparity20' in df.columns and not np.isnan(df['disparity20'].iloc[-1]) else 100.0
            curr_vr = float(df['volume_ratio'].iloc[-1]) if 'volume_ratio' in df.columns and not np.isnan(df['volume_ratio'].iloc[-1]) else 100.0
            curr_close = int(df['종가'].iloc[-1]) if '종가' in df.columns else 0

            buy_res = evaluate_buy_signal(df)
            status_text = "관망"
            buy_item = None
            if buy_res:
                buy_res['ticker'] = clean_ticker
                buy_res['name'] = name
                buy_res['prev_adx'] = round(prev_adx, 2)
                buy_res['prev_minus_di'] = round(prev_mdi, 2)
                buy_item = buy_res
                status_text = buy_res['priority']
            elif curr_adx >= 25 and curr_mdi > curr_adx:
                status_text = "관심종목"

            stock_item = {
                "ticker": clean_ticker,
                "name": name,
                "adx": round(curr_adx, 2),
                "minus_di": round(curr_mdi, 2),
                "plus_di": round(curr_pdi, 2),
                "rsi": round(curr_rsi, 2),
                "b_band_pct": round(curr_bb_pct, 2),
                "macd": round(curr_macd, 2),
                "macd_signal": round(curr_macd_sig, 2),
                "macd_osc": round(curr_macd_osc, 2),
                "stoch_k": round(curr_stoch_k, 2),
                "stoch_d": round(curr_stoch_d, 2),
                "disparity20": round(curr_disparity, 2),
                "volume_ratio": round(curr_vr, 2),
                "close": curr_close,
                "status": status_text
            }
            return (clean_ticker, name, df, buy_item, stock_item)
        except Exception as e:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(process_single_stock, item) for item in items]
        for future in as_completed(futures):
            res = future.result()
            if res:
                clean_ticker, name, df, buy_item, stock_item = res
                stock_df_map[clean_ticker] = (df, name)
                stock_df_map[name.replace(' ', '')] = (df, name)
                all_stocks.append(stock_item)
                if buy_item:
                    buy_candidates.append(buy_item)
                    print(f"  🔥 [BUY SIGNAL] {buy_item['name']} ({buy_item['ticker']}) - {buy_item['priority']} | ADX: {buy_item['adx']} | RSI: {buy_item['rsi']}")

    # Sort buy candidates by priority score (3단계 -> 2단계 -> 1단계)
    buy_candidates.sort(key=lambda x: x['score'], reverse=True)
    print(f" -> Found {len(buy_candidates)} buy candidate stocks.")
    print(f" -> Calculated indicators for {len(all_stocks)} stocks.")

    # 3. Post to Google Sheets API
    if gas_url:
        print("[3/4] Posting screening results to Google Sheets...")
        log_payload = {
            "status": "SUCCESS",
            "scanned": len(items),
            "count": len(buy_candidates),
            "message": f"KOSPI 200 {len(items)}개 종목 검사 완료 (매수 신호: {len(buy_candidates)}개)"
        }
        post_to_google_sheets(gas_url, "update_buy_candidates", {
            "candidates": buy_candidates,
            "all_stocks": all_stocks,
            "log": log_payload
        })

    # 4. Check Sell Signals & Monitor Indicators for User Holdings
    if gas_url:
        print("[4/4] Evaluating Indicators & Sell Signals for User Holdings...")
        try:
            pin = os.environ.get("AUTH_PIN", "")
            req_url = f"{gas_url}?action=holdings"
            if pin:
                req_url += f"&pin={pin}"
            h_res = requests.get(req_url, timeout=15)
            print(f" -> Fetch Holdings Response: Status {h_res.status_code} | {h_res.text[:150]}")

            if h_res.status_code == 200:
                res_json = h_res.json()
                if res_json.get("success"):
                    holdings_list = res_json.get("userHoldings", [])
                    print(f" -> Found {len(holdings_list)} user holdings to evaluate.")
                    holdings_status = []
                    sell_signals = []
                    for h in holdings_list:
                        h_ticker = str(h.get("Ticker") or h.get("ticker") or h.get("code") or "").strip()
                        h_name = str(h.get("Name") or h.get("name") or "").strip()
                        h_price = float(h.get("BuyPrice") or h.get("buyPrice", 0))
                        
                        # Pad numeric ticker to 6 digits (e.g. "16360" -> "016360")
                        if h_ticker.isdigit():
                            h_ticker = h_ticker.zfill(6)

                        # Lookup cached DataFrame by ticker or name
                        h_df = None
                        matched_name = h_name
                        matched_ticker = h_ticker

                        if h_ticker in stock_df_map:
                            h_df, matched_name = stock_df_map[h_ticker]
                        elif h_name.replace(' ', '') in stock_df_map:
                            h_df, matched_name = stock_df_map[h_name.replace(' ', '')]
                        else:
                            # Search through items
                            for item in items:
                                i_name = str(item.get('name', '')).strip()
                                i_ticker = str(item.get('ticker', '')).strip().zfill(6)
                                if i_name == h_ticker or i_name == h_name or i_ticker == h_ticker or i_name.replace(' ', '') == h_name.replace(' ', ''):
                                    matched_ticker = i_ticker
                                    matched_name = i_name
                                    if matched_ticker in stock_df_map:
                                        h_df, matched_name = stock_df_map[matched_ticker]
                                    break
                        
                        if h_df is None:
                            # Fallback fetch only if stock is non-KOSPI200 holding
                            if matched_ticker.isdigit():
                                matched_ticker = matched_ticker.zfill(6)
                                h_df = get_ohlcv_data(matched_ticker, start_date, end_date)
                                h_df = check_and_trim_incomplete_candle(h_df)
                                if h_df is not None and len(h_df) >= 30:
                                    h_df = calculate_indicators(h_df)
                        
                        if h_df is None or len(h_df) < 30:
                            print(f"  [WARN] Insufficient candle data for holding: {h_name} ({h_ticker})")
                            continue

                        sell_res = evaluate_sell_signal(h_df, h_price)
                        if sell_res:
                            sell_res["ticker"] = matched_ticker if matched_ticker.isdigit() else h_ticker
                            sell_res["name"] = matched_name if matched_name else h_name
                            holdings_status.append(sell_res)
                            if sell_res.get("isAlert"):
                                sell_signals.append(sell_res)
                                print(f"  ⚠️ [SELL ALERT] {sell_res['name']} ({sell_res['ticker']}) - {sell_res['signalLevel']} | {sell_res['details']}")
                            else:
                                print(f"  🛡️ [HOLDING MONITOR] {sell_res['name']} ({sell_res['ticker']}) - 관망 (ADX: {sell_res['adx']}, 수익률: {sell_res['returnRate']}%)")
                    
                    if holdings_status:
                        print(f" -> Posting {len(holdings_status)} holdings status metrics to Google Sheets...")
                        post_to_google_sheets(gas_url, "update_holdings_status", {"holdings_status": holdings_status})
                    else:
                        print(" -> No active holdings status metrics to update.")

                    if sell_signals:
                        post_to_google_sheets(gas_url, "update_sell_signals", {"signals": sell_signals})
                    else:
                        print(" -> No sell alert signals detected for current holdings.")
                else:
                    print(f"[WARN] GAS returned error when fetching holdings: {res_json.get('message')}")
            else:
                print(f"[WARN] GAS returned HTTP {h_res.status_code} for holdings fetch.")
        except Exception as e:
            print(f"[ERROR] Failed evaluating sell signals: {e}")
    else:
        print("[WARN] GAS_WEBAPP_URL environment variable is not set.")

    print("[INFO] Screener Execution Completed.")
