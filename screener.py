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
        
    alpha = 2.0 / (period + 1)
    
    def calc_ema(arr):
        res = [arr[0]]
        for val in arr[1:]:
            res.append(val * alpha + res[-1] * (1 - alpha))
        return res

    tr_ema = calc_ema(tr)
    dp_ema = calc_ema(dm_p)
    dm_ema = calc_ema(dm_m)
    
    pdi = [100 * p / t if t != 0 else 0 for p, t in zip(dp_ema, tr_ema)]
    mdi = [100 * m / t if t != 0 else 0 for m, t in zip(dm_ema, tr_ema)]
    
    dx = [100 * abs(p - m) / (p + m) if (p + m) != 0 else 0 for p, m in zip(pdi, mdi)]
    adx = calc_ema(dx)
    
    pdi = [np.nan] + pdi
    mdi = [np.nan] + mdi
    adx = [np.nan] + adx
    
    df['adx'] = adx
    df['plus_di'] = pdi
    df['minus_di'] = mdi

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
    is_buy = (curr_adx >= 30) and (prev_mdi > prev_adx) and (curr_mdi <= curr_adx)

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
        "signalLevel": level,
        "details": " / ".join(details),
        "isAlert": (level != "관망")
    }

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

    # 2. Screen Buy Signals across all KOSPI 200
    print("[2/4] Calculating indicators and screening buy signals...")
    for idx, item in enumerate(items):
        ticker = item['ticker']
        name = item['name']
        try:
            df = get_ohlcv_data(ticker, start_date, end_date)
            if len(df) < 30:
                continue
            df = calculate_indicators(df)
            
            # Record current and previous indicators for all stocks
            curr_adx = float(df['adx'].iloc[-1]) if 'adx' in df.columns and not np.isnan(df['adx'].iloc[-1]) else 0.0
            prev_adx = float(df['adx'].iloc[-2]) if len(df) >= 2 and 'adx' in df.columns and not np.isnan(df['adx'].iloc[-2]) else 0.0
            curr_mdi = float(df['minus_di'].iloc[-1]) if 'minus_di' in df.columns and not np.isnan(df['minus_di'].iloc[-1]) else 0.0
            prev_mdi = float(df['minus_di'].iloc[-2]) if len(df) >= 2 and 'minus_di' in df.columns and not np.isnan(df['minus_di'].iloc[-2]) else 0.0
            curr_pdi = float(df['plus_di'].iloc[-1]) if 'plus_di' in df.columns and not np.isnan(df['plus_di'].iloc[-1]) else 0.0
            curr_rsi = float(df['rsi'].iloc[-1]) if 'rsi' in df.columns and not np.isnan(df['rsi'].iloc[-1]) else 0.0
            curr_close = int(df['종가'].iloc[-1]) if '종가' in df.columns else 0

            buy_res = evaluate_buy_signal(df)
            status_text = "관망"
            if buy_res:
                buy_res['ticker'] = ticker
                buy_res['name'] = name
                buy_res['prev_adx'] = round(prev_adx, 2)
                buy_res['prev_minus_di'] = round(prev_mdi, 2)
                buy_candidates.append(buy_res)
                status_text = buy_res['priority']
                print(f"  🔥 [BUY SIGNAL] {name} ({ticker}) - {buy_res['priority']} | ADX: {buy_res['adx']} | RSI: {buy_res['rsi']}")
            elif curr_adx >= 30:
                status_text = "추세강함 (조건미달)"

            all_stocks.append({
                "ticker": ticker,
                "name": name,
                "adx": round(curr_adx, 2),
                "prev_adx": round(prev_adx, 2),
                "minus_di": round(curr_mdi, 2),
                "prev_minus_di": round(prev_mdi, 2),
                "plus_di": round(curr_pdi, 2),
                "prev_plus_di": round(prev_pdi, 2),
                "rsi": round(curr_rsi, 2),
                "close": curr_close,
                "status": status_text
            })
        except Exception as e:
            if idx < 5:
                print(f"[ERROR] Screening failed for {name} ({ticker}): {e}")
            continue

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

                        # Resolve stock ticker code if h_ticker is stock name (e.g. "삼성전자")
                        if not h_ticker.isdigit() or not h_name:
                            for item in items:
                                i_name = str(item.get('name', '')).strip()
                                i_ticker = str(item.get('ticker', '')).strip().zfill(6)
                                if i_name == h_ticker or i_name == h_name or i_ticker == h_ticker or i_name.replace(' ', '') == h_name.replace(' ', ''):
                                    h_ticker = i_ticker
                                    h_name = i_name
                                    break
                        
                        if h_ticker.isdigit():
                            h_ticker = h_ticker.zfill(6)
                        
                        if not h_ticker or not h_ticker.isdigit():
                            print(f"  [WARN] Skipping invalid holding entry: Ticker={h_ticker}, Name={h_name}")
                            continue
                        
                        h_df = get_ohlcv_data(h_ticker, start_date, end_date)
                        if len(h_df) < 30:
                            print(f"  [WARN] Insufficient candle data for holding: {h_name} ({h_ticker})")
                            continue
                        h_df = calculate_indicators(h_df)
                        sell_res = evaluate_sell_signal(h_df, h_price)
                        if sell_res:
                            sell_res["ticker"] = h_ticker
                            sell_res["name"] = h_name
                            holdings_status.append(sell_res)
                            if sell_res.get("isAlert"):
                                sell_signals.append(sell_res)
                                print(f"  ⚠️ [SELL ALERT] {h_name} ({h_ticker}) - {sell_res['signalLevel']} | {', '.join(sell_res['details'])}")
                            else:
                                print(f"  🛡️ [HOLDING MONITOR] {h_name} ({h_ticker}) - 관망 (ADX: {sell_res['adx']}, 수익률: {sell_res['returnRate']}%)")
                    
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
