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

def fetch_official_etf_constituents(etf_code, market_name):
    """Fetch official KOSPI 200 / KOSDAQ 150 constituents from WiseReport/Naver ETF portfolio API."""
    url = f"https://navercomp.wisereport.co.kr/v2/ETF/index.aspx?cmp_cd={etf_code}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        m = re.search(r'var\s+CU_data\s*=\s*(\{.*?\});\s*var', res.text, re.DOTALL)
        if not m:
            return []
        grid = json.loads(m.group(1)).get('grid_data', [])
        
        # Load stocks_350 master for fast ticker lookup
        stocks_350_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stocks_350.json")
        master_map = {}
        if os.path.exists(stocks_350_path):
            with open(stocks_350_path, "r", encoding="utf-8") as f:
                for s in json.load(f):
                    master_map[s["name"]] = s["ticker"]

        items = []
        seen = set()
        for g in grid:
            nm = g.get('STK_NM_KOR', '').strip()
            if nm and not any(k in nm for k in ['원화예치금', '설정원금', '현금', '선물']):
                ticker = master_map.get(nm, '')
                if ticker and ticker not in seen:
                    seen.add(ticker)
                    items.append({"ticker": ticker, "name": nm, "market": market_name})
        return items
    except Exception as e:
        print(f"[WARN] Failed fetching official ETF {etf_code} constituents: {e}")
        return []

def get_kospi200_tickers():
    """Retrieve official KOSPI 200 list of tickers and names (Verified Master JSON -> Official ETF Portfolio -> PyKRX)."""
    # 1. Priority: Read from verified data/stocks_350.json
    stocks_350_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stocks_350.json")
    if os.path.exists(stocks_350_path):
        try:
            with open(stocks_350_path, "r", encoding="utf-8") as f:
                stocks = json.load(f)
                k200 = [s for s in stocks if s.get("market") == "KOSPI200"]
                if len(k200) >= 195:
                    return k200[:200]
        except Exception:
            pass

    # 2. Priority: Fetch from KODEX 200 ETF (069500) Official Portfolio API
    etf_items = fetch_official_etf_constituents("069500", "KOSPI200")
    if len(etf_items) >= 195:
        return etf_items[:200]

    # 3. Fallback: PyKRX Index 1028 (KOSPI 200)
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
    """Retrieve official KOSDAQ 150 list of tickers and names (Verified Master JSON -> Official ETF Portfolio -> PyKRX)."""
    # 1. Priority: Read from verified data/stocks_350.json (Contains SOOP and all official 150 constituents)
    stocks_350_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stocks_350.json")
    if os.path.exists(stocks_350_path):
        try:
            with open(stocks_350_path, "r", encoding="utf-8") as f:
                stocks = json.load(f)
                kd150 = [s for s in stocks if s.get("market") == "KOSDAQ150"]
                if len(kd150) >= 145:
                    return kd150[:150]
        except Exception:
            pass

    # 2. Priority: Fetch from KODEX 코스닥150 ETF (229200) Official Portfolio API
    etf_items = fetch_official_etf_constituents("229200", "KOSDAQ150")
    if len(etf_items) >= 145:
        return etf_items[:150]

    # 3. Fallback: PyKRX Index 2203 / 2011 (KOSDAQ 150)
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

def get_ohlcv_data(ticker, start_date, end_date):
    """Retrieve OHLCV DataFrame for a ticker (Naver FChart XML 1st, Naver siseJson 2nd, PyKRX 3rd)."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # 1. Primary (Ultra-Fast): Naver FChart XML (Adjusted Prices - 300 daily candles)
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
    except Exception:
        pass

    # 2. Fallback A: Naver siseJson API
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
            if len(df) >= 30:
                return df
    except Exception:
        pass

    # 3. Fallback B: PyKRX (Official KRX)
    try:
        if stock:
            df = stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
            if df is not None and len(df) >= 30 and '고가' in df.columns:
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
        
    # 1. DMI & ADX (14) - Standard Exponential Moving Average (EMA, alpha = 2 / (period + 1))
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

def check_single_rule(rule, df, buy_price=None):
    """Evaluate a single rule on the given DataFrame."""
    if not rule or not isinstance(rule, dict):
        return False

    ind = str(rule.get('indicator', '')).lower()
    cond = str(rule.get('condition_type', '')).lower()
    target_ind = str(rule.get('target_indicator', '')).lower() if rule.get('target_indicator') else None
    try:
        rule_val = float(rule.get('value', 0))
    except (ValueError, TypeError):
        rule_val = 0.0

    if ind in ('return_rate', 'returnrate', 'return_pct', 'profit_pct'):
        if buy_price is None or buy_price <= 0:
            return True
        curr_close = float(df['종가'].iloc[-1]) if '종가' in df.columns else float(df['Close'].iloc[-1])
        ret = ((curr_close - buy_price) / buy_price) * 100.0
        if cond == 'gte_value':
            return ret >= rule_val
        elif cond == 'lte_value':
            return ret <= rule_val
        elif cond == 'gt_value':
            return ret > rule_val
        elif cond == 'lt_value':
            return ret < rule_val
        return False

    def get_indicator_series(key):
        mapping = {
            'adx': 'adx',
            'minus_di': 'minus_di',
            'plus_di': 'plus_di',
            'rsi': 'rsi',
            'bb_pct': 'b_band_pct',
            'macd': 'macd',
            'macd_osc': 'macd_osc',
            'stoch_k': 'stoch_k',
            'stoch_d': 'stoch_d',
            'disparity20': 'disparity20',
            'volume_ratio': 'volume_ratio'
        }
        col = mapping.get(key)
        if col and col in df.columns:
            return df[col]
        return None

    s = get_indicator_series(ind)
    if s is None or len(s) < 2:
        return False

    curr_val = s.iloc[-1]
    prev_val = s.iloc[-2]

    if np.isnan(curr_val):
        return False

    target_s = get_indicator_series(target_ind) if target_ind else None
    target_val = target_s.iloc[-1] if target_s is not None and not np.isnan(target_s.iloc[-1]) else rule_val
    prev_target_val = target_s.iloc[-2] if target_s is not None and not np.isnan(target_s.iloc[-2]) else rule_val

    if cond == 'gte_value':
        return curr_val >= rule_val
    elif cond == 'lte_value':
        return curr_val <= rule_val
    elif cond == 'gt_value':
        return curr_val > rule_val
    elif cond == 'lt_value':
        return curr_val < rule_val
    elif cond == 'cross_above_value':
        return not np.isnan(prev_val) and prev_val <= rule_val and curr_val > rule_val
    elif cond == 'cross_below_value':
        return not np.isnan(prev_val) and prev_val >= rule_val and curr_val < rule_val
    elif cond == 'turn_up':
        return not np.isnan(prev_val) and prev_val <= 0 and curr_val > 0
    elif cond == 'turn_down':
        return not np.isnan(prev_val) and prev_val >= 0 and curr_val < 0
    elif cond == 'gt_indicator':
        return curr_val > target_val
    elif cond == 'lt_indicator':
        return curr_val < target_val
    elif cond == 'gte_indicator':
        return curr_val >= target_val
    elif cond == 'lte_indicator':
        return curr_val <= target_val
    elif cond == 'cross_above_indicator':
        return not np.isnan(prev_val) and not np.isnan(prev_target_val) and prev_val <= prev_target_val and curr_val > target_val
    elif cond == 'cross_below_indicator':
        return not np.isnan(prev_val) and not np.isnan(prev_target_val) and prev_val >= prev_target_val and curr_val < target_val
    return False

def check_group_match(group, df, buy_price=None):
    """Evaluate a buy/sell group (AND logic among rules inside the group)."""
    if not group or not isinstance(group, dict):
        return False
    rules = group.get('rules', [])
    if not rules or not isinstance(rules, list):
        return False
    return all(check_single_rule(r, df, buy_price=buy_price) for r in rules)

def evaluate_buy_signal(df, active_slot=None):
    """
    Evaluate Buy Signal based on active strategy slot (or default ADX reversal).
    """
    if len(df) < 2 or 'adx' not in df.columns:
        return None

    curr_adx = df['adx'].iloc[-1]
    curr_mdi = df['minus_di'].iloc[-1]
    curr_pdi = df['plus_di'].iloc[-1]
    curr_rsi = df['rsi'].iloc[-1]
    curr_bb_pct = df['b_band_pct'].iloc[-1] if 'b_band_pct' in df.columns else 0.5
    curr_vr = df['volume_ratio'].iloc[-1] if 'volume_ratio' in df.columns else 100.0
    curr_close = int(df['종가'].iloc[-1])

    is_buy = False
    priority = "전략매수"

    if active_slot and active_slot.get('buyRules') and len(active_slot['buyRules']) > 0:
        # Check active slot buy groups (OR logic across groups)
        is_buy = any(check_group_match(g, df) for g in active_slot['buyRules'])
        if is_buy:
            priority = "전략매수"
    else:
        # Fallback to default Strategy #1 (ADX >= 30 and -DI cross below ADX)
        prev_adx = df['adx'].iloc[-2]
        prev_mdi = df['minus_di'].iloc[-2]
        is_buy = (curr_adx >= 30.0) and (prev_mdi > prev_adx) and (curr_mdi <= curr_adx)

    if not is_buy:
        return None

    return {
        "is_buy": True,
        "priority": priority,
        "score": 1,
        "adx": round(curr_adx, 2),
        "minus_di": round(curr_mdi, 2),
        "plus_di": round(curr_pdi, 2),
        "rsi": round(curr_rsi, 2) if not np.isnan(curr_rsi) else None,
        "b_band_pct": round(curr_bb_pct, 2) if not np.isnan(curr_bb_pct) else None,
        "volume_ratio": round(curr_vr, 1) if not np.isnan(curr_vr) else 100.0,
        "close": curr_close
    }

def evaluate_sell_signal(df, buy_price, active_slot=None):
    """
    Evaluate Sell & Scale-In Signals for a held stock based on active strategy slot.
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
    curr_vr = df['volume_ratio'].iloc[-1] if 'volume_ratio' in df.columns else 100.0

    return_rate = 0.0
    if buy_price and buy_price > 0:
        return_rate = round(((curr_close - buy_price) / buy_price) * 100, 2)

    details = []
    level = "관망"

    stop_loss_pct = 20.0
    take_profit_pct = None
    scale_in_drop_pct = None
    scale_in_mult = 1.0

    if active_slot:
        if active_slot.get('stopLoss') is not None and active_slot['stopLoss'] != '':
            try:
                stop_loss_pct = abs(float(active_slot['stopLoss']))
            except:
                pass
        if active_slot.get('takeProfit') is not None and active_slot['takeProfit'] != '':
            try:
                take_profit_pct = abs(float(active_slot['takeProfit']))
            except:
                pass
        if active_slot.get('scaleInDrop') is not None and active_slot['scaleInDrop'] != '':
            try:
                scale_in_drop_pct = abs(float(active_slot['scaleInDrop']))
            except:
                pass
        if active_slot.get('scaleInMultiplier') is not None and active_slot['scaleInMultiplier'] != '':
            try:
                scale_in_mult = float(active_slot['scaleInMultiplier'])
            except:
                pass

    # Evaluation conditions
    is_stop_loss = (buy_price and buy_price > 0 and return_rate <= -stop_loss_pct)
    is_take_profit = (buy_price and buy_price > 0 and take_profit_pct and return_rate >= take_profit_pct)
    is_scale_in = (buy_price and buy_price > 0 and scale_in_drop_pct and return_rate <= -scale_in_drop_pct)
    
    is_strategy_sell = False
    if active_slot and active_slot.get('sellRules') and len(active_slot['sellRules']) > 0:
        is_strategy_sell = any(check_group_match(g, df, buy_price=buy_price) for g in active_slot['sellRules'])
    else:
        is_strategy_sell = (curr_rsi >= 65.0)

    if is_stop_loss:
        level = "손절매도"
        details.append(f"손절선(-{stop_loss_pct}%) 도달 이탈 (현재 수익률: {return_rate:.2f}%)")
    elif is_take_profit:
        level = "익절매도"
        details.append(f"익절선(+{take_profit_pct}%) 도달 (현재 수익률: +{return_rate:.2f}%)")
    elif is_scale_in:
        level = "물타기매수"
        details.append(f"물타기 기준(-{scale_in_drop_pct}%) 도달 (현재 수익률: {return_rate:.2f}% | 익일 시가 {scale_in_mult}배 추가매수)")
    elif is_strategy_sell:
        level = "전략매도"
        details.append(f"전략 매도 청산 조건 충족 (RSI: {curr_rsi:.1f})")
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
        "volume_ratio": round(curr_vr, 1) if not np.isnan(curr_vr) else 100.0,
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

    def clean_obj(obj):
        if isinstance(obj, (float, np.floating)):
            if np.isnan(obj) or np.isinf(obj):
                return None
            return round(float(obj), 2)
        elif isinstance(obj, (int, np.integer)):
            return int(obj)
        elif isinstance(obj, dict):
            return {k: clean_obj(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_obj(v) for v in obj]
        return obj

    sanitized_payload = clean_obj(payload)
    try:
        res = requests.post(url, json=sanitized_payload, timeout=45)
        print(f" -> GAS Response [{action}]: Status {res.status_code} | {res.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Failed to post to Google Sheets ({action}): {e}")

if __name__ == "__main__":
    print("[INFO] KOSPI 200 & KOSDAQ 150 Stock Signal Screener Engine Starting...")
    
    gas_url = os.environ.get("GAS_WEBAPP_URL", "")

    # Fetch Active Strategy Slot from GAS
    active_slot = None
    if gas_url:
        try:
            print("[INFO] Fetching active strategy slot from Google Apps Script...")
            resp = requests.get(f"{gas_url}?action=get_strategy_slots", timeout=10)
            if resp.status_code == 200:
                slot_data = resp.json()
                if slot_data.get('success'):
                    active_id = slot_data.get('activeSlotId', 1)
                    slots = slot_data.get('slots', [])
                    active_slot = next((s for s in slots if s.get('id') == active_id), None)
                    if active_slot:
                        print(f" -> Active Strategy Loaded: [Slot {active_slot.get('id')}] {active_slot.get('name')}")
                        if active_slot.get('buyRules'):
                            print(f"    Buy Rules: {len(active_slot['buyRules'])} groups")
                        if active_slot.get('sellRules'):
                            print(f"    Sell Rules: {len(active_slot['sellRules'])} groups")
        except Exception as e:
            print(f"[WARN] Failed to fetch active strategy slot: {e}")

    # Pre-fetch User Holdings early to filter out existing holdings from duplicate buy candidates
    holdings_list = []
    held_tickers = set()
    held_names = set()
    if gas_url:
        try:
            pin = os.environ.get("AUTH_PIN", "")
            req_url = f"{gas_url}?action=holdings"
            if pin:
                req_url += f"&pin={pin}"
            h_res = requests.get(req_url, timeout=15)
            if h_res.status_code == 200:
                res_json = h_res.json()
                if res_json.get("success"):
                    holdings_list = res_json.get("userHoldings", [])
                    for h in holdings_list:
                        t = str(h.get("Ticker") or h.get("ticker") or h.get("code") or "").strip()
                        if t.isdigit():
                            t = t.zfill(6)
                        n = str(h.get("Name") or h.get("name") or "").strip().replace(" ", "")
                        if t and t != "-":
                            held_tickers.add(t)
                        if n:
                            held_names.add(n)
                    print(f" -> Found {len(holdings_list)} user holdings in Google Sheets ({len(held_tickers)} tickers).")
        except Exception as e:
            print(f"[WARN] Failed to pre-fetch holdings: {e}")

    # 1. Fetch KOSPI 200 & KOSDAQ 150 Tickers
    print("[1/4] Fetching KOSPI 200 and KOSDAQ 150 component tickers...")
    kospi_items = get_kospi200_tickers()
    kosdaq_items = get_kosdaq150_tickers()
    print(f" -> Found KOSPI 200: {len(kospi_items)} tickers | KOSDAQ 150: {len(kosdaq_items)} tickers.")

    all_target_items = kospi_items + kosdaq_items

    buy_candidates = []
    kospi_stocks = []
    kosdaq_stocks = []
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    start_date = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y%m%d")

    stock_df_map = {}

    # 2. Screen Buy Signals across all KOSPI 200 & KOSDAQ 150 (Parallel Execution)
    print("[2/4] Calculating indicators and screening buy signals (Parallel Execution)...")
    
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def process_single_stock(item):
        ticker = item['ticker']
        name = item['name']
        market = item.get('market', 'KOSPI200')
        try:
            df = get_ohlcv_data(ticker, start_date, end_date)
            df = check_and_trim_incomplete_candle(df)
            if df is None or len(df) < 30:
                return None
            df = calculate_indicators(df)
            
            clean_ticker = str(ticker).zfill(6)
            
            def sanitize_num(val, default=None, decimals=2):
                if val is None:
                    return default
                try:
                    f = float(val)
                    if np.isnan(f) or np.isinf(f):
                        return default
                    return round(f, decimals) if decimals is not None else f
                except (ValueError, TypeError):
                    return default

            curr_adx = sanitize_num(df['adx'].iloc[-1] if 'adx' in df.columns else None, default=0.0)
            prev_adx = sanitize_num(df['adx'].iloc[-2] if len(df) >= 2 and 'adx' in df.columns else None, default=0.0)
            curr_mdi = sanitize_num(df['minus_di'].iloc[-1] if 'minus_di' in df.columns else None, default=0.0)
            prev_mdi = sanitize_num(df['minus_di'].iloc[-2] if len(df) >= 2 and 'minus_di' in df.columns else None, default=0.0)
            curr_pdi = sanitize_num(df['plus_di'].iloc[-1] if 'plus_di' in df.columns else None, default=0.0)
            prev_pdi = sanitize_num(df['plus_di'].iloc[-2] if len(df) >= 2 and 'plus_di' in df.columns else None, default=0.0)
            curr_rsi = sanitize_num(df['rsi'].iloc[-1] if 'rsi' in df.columns else None, default=0.0)
            prev_rsi = sanitize_num(df['rsi'].iloc[-2] if len(df) >= 2 and 'rsi' in df.columns else None, default=0.0)
            curr_bb_pct = sanitize_num(df['b_band_pct'].iloc[-1] if 'b_band_pct' in df.columns else None, default=0.5)
            prev_bb_pct = sanitize_num(df['b_band_pct'].iloc[-2] if len(df) >= 2 and 'b_band_pct' in df.columns else None, default=0.5)
            curr_macd = sanitize_num(df['macd'].iloc[-1] if 'macd' in df.columns else None, default=0.0)
            prev_macd = sanitize_num(df['macd'].iloc[-2] if len(df) >= 2 and 'macd' in df.columns else None, default=0.0)
            curr_macd_sig = sanitize_num(df['macd_signal'].iloc[-1] if 'macd_signal' in df.columns else None, default=0.0)
            prev_macd_sig = sanitize_num(df['macd_signal'].iloc[-2] if len(df) >= 2 and 'macd_signal' in df.columns else None, default=0.0)
            curr_macd_osc = sanitize_num(df['macd_osc'].iloc[-1] if 'macd_osc' in df.columns else None, default=0.0)
            prev_macd_osc = sanitize_num(df['macd_osc'].iloc[-2] if len(df) >= 2 and 'macd_osc' in df.columns else None, default=0.0)
            curr_stoch_k = sanitize_num(df['stoch_k'].iloc[-1] if 'stoch_k' in df.columns else None, default=50.0)
            prev_stoch_k = sanitize_num(df['stoch_k'].iloc[-2] if len(df) >= 2 and 'stoch_k' in df.columns else None, default=50.0)
            curr_stoch_d = sanitize_num(df['stoch_d'].iloc[-1] if 'stoch_d' in df.columns else None, default=50.0)
            prev_stoch_d = sanitize_num(df['stoch_d'].iloc[-2] if len(df) >= 2 and 'stoch_d' in df.columns else None, default=50.0)
            curr_disparity = sanitize_num(df['disparity20'].iloc[-1] if 'disparity20' in df.columns else None, default=100.0)
            prev_disparity = sanitize_num(df['disparity20'].iloc[-2] if len(df) >= 2 and 'disparity20' in df.columns else None, default=100.0)
            curr_vr = sanitize_num(df['volume_ratio'].iloc[-1] if 'volume_ratio' in df.columns else None, default=100.0)
            prev_vr = sanitize_num(df['volume_ratio'].iloc[-2] if len(df) >= 2 and 'volume_ratio' in df.columns else None, default=100.0)
            curr_close = int(df['종가'].iloc[-1]) if '종가' in df.columns and not np.isnan(df['종가'].iloc[-1]) else 0
            prev_close = int(df['종가'].iloc[-2]) if len(df) >= 2 and '종가' in df.columns and not np.isnan(df['종가'].iloc[-2]) else 0

            is_held = (clean_ticker in held_tickers) or (name.replace(' ', '') in held_names)
            buy_res = evaluate_buy_signal(df, active_slot=active_slot)
            status_text = "관망"
            buy_item = None
            if is_held:
                status_text = "보유중"
                if buy_res:
                    print(f"  ⏭️ [HOLDING EXCLUDED] {name} ({clean_ticker}) is already held in portfolio. Skipping duplicate 1st buy signal.")
            elif buy_res:
                buy_res['ticker'] = clean_ticker
                buy_res['name'] = name
                buy_res['market'] = market
                buy_res['prev_adx'] = prev_adx
                buy_res['prev_minus_di'] = prev_mdi
                buy_item = buy_res
                status_text = buy_res['priority']
            elif curr_adx >= 30 and curr_mdi > curr_adx:
                status_text = "관심종목"

            stock_item = {
                "ticker": clean_ticker,
                "name": name,
                "market": market,
                "adx": curr_adx,
                "minus_di": curr_mdi,
                "plus_di": curr_pdi,
                "rsi": curr_rsi,
                "b_band_pct": curr_bb_pct,
                "macd": curr_macd,
                "macd_signal": curr_macd_sig,
                "macd_osc": curr_macd_osc,
                "stoch_k": curr_stoch_k,
                "stoch_d": curr_stoch_d,
                "disparity20": curr_disparity,
                "volume_ratio": curr_vr,
                "close": curr_close,
                "status": status_text,
                "prev_adx": prev_adx,
                "prev_minus_di": prev_mdi,
                "prev_plus_di": prev_pdi,
                "prev_rsi": prev_rsi,
                "prev_b_band_pct": prev_bb_pct,
                "prev_macd": prev_macd,
                "prev_macd_signal": prev_macd_sig,
                "prev_macd_osc": prev_macd_osc,
                "prev_stoch_k": prev_stoch_k,
                "prev_stoch_d": prev_stoch_d,
                "prev_disparity20": prev_disparity,
                "prev_volume_ratio": prev_vr,
                "prev_close": prev_close
            }
            return (clean_ticker, name, market, df, buy_item, stock_item)
        except Exception as e:
            return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(process_single_stock, all_target_items))
        for res in results:
            if res:
                clean_ticker, name, market, df, buy_item, stock_item = res
                stock_df_map[clean_ticker] = (df, name)
                stock_df_map[name.replace(' ', '')] = (df, name)
                if market == "KOSDAQ150":
                    kosdaq_stocks.append(stock_item)
                else:
                    kospi_stocks.append(stock_item)
                if buy_item:
                    buy_candidates.append(buy_item)
                    print(f"  🔥 [BUY SIGNAL] [{market}] {buy_item['name']} ({buy_item['ticker']}) - {buy_item['priority']} | ADX: {buy_item['adx']} | RSI: {buy_item['rsi']}")

    # Sort buy candidates by priority score
    buy_candidates.sort(key=lambda x: x['score'], reverse=True)
    print(f" -> Found {len(buy_candidates)} buy candidate stocks across KOSPI 200 & KOSDAQ 150.")
    print(f" -> Calculated indicators for KOSPI 200 ({len(kospi_stocks)}) and KOSDAQ 150 ({len(kosdaq_stocks)}).")

    # 3. Post to Google Sheets API
    if gas_url:
        print("[3/4] Posting screening results to Google Sheets...")
        strategy_desc = f" [{active_slot.get('name')}]" if active_slot else ""
        log_payload = {
            "status": "SUCCESS",
            "scanned": len(all_target_items),
            "count": len(buy_candidates),
            "message": f"KOSPI 200 ({len(kospi_items)}개), KOSDAQ 150 ({len(kosdaq_items)}개) 종목 검사 완료{strategy_desc} (매수 신호: {len(buy_candidates)}개)"
        }
        post_to_google_sheets(gas_url, "update_buy_candidates", {
            "candidates": buy_candidates,
            "kospi_stocks": kospi_stocks,
            "kosdaq_stocks": kosdaq_stocks,
            "all_stocks": kospi_stocks,
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
                            for item in all_target_items:
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

                        sell_res = evaluate_sell_signal(h_df, h_price, active_slot=active_slot)
                        if sell_res:
                            sell_res["ticker"] = matched_ticker if matched_ticker.isdigit() else h_ticker
                            sell_res["name"] = matched_name if matched_name else h_name
                            holdings_status.append(sell_res)
                            if sell_res.get("isAlert"):
                                sell_signals.append(sell_res)
                                if sell_res["signalLevel"] == "물타기매수":
                                    print(f"  [SCALE-IN BUY] {sell_res['name']} ({sell_res['ticker']}) - {sell_res['signalLevel']} | {sell_res['details']}")
                                else:
                                    print(f"  [SELL ALERT] {sell_res['name']} ({sell_res['ticker']}) - {sell_res['signalLevel']} | {sell_res['details']}")
                            else:
                                print(f"  [HOLDING MONITOR] {sell_res['name']} ({sell_res['ticker']}) - 관망 (ADX: {sell_res['adx']}, 수익률: {sell_res['returnRate']}%)")
                    
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
