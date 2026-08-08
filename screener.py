"""
KOSPI 200 Stock Screener & Technical Indicator Engine
Calculates ADX, +DI, -DI, RSI, and Moving Averages for KOSPI 200 components.
"""

import sys
import datetime
import pandas as pd
import numpy as np

try:
    from pykrx import stock
    import ta
except ImportError:
    print("[WARN] Required packages ('pykrx', 'ta', 'pandas') missing. Install via pip.")

def get_kospi200_tickers():
    """Retrieve KOSPI 200 list of tickers and names using PyKRX."""
    today = datetime.datetime.now().strftime("%Y%m%d")
    try:
        # 1028 is KOSPI 200 index code
        tickers = stock.get_index_portfolio_deposit_file("1028")
        items = []
        for ticker in tickers:
            name = stock.get_market_ticker_name(ticker)
            items.append({"ticker": ticker, "name": name})
        return items
    except Exception as e:
        print(f"[ERROR] Failed to fetch KOSPI 200 list: {e}")
        return []

def calculate_indicators(df):
    """
    Calculate ADX(14), +DI, -DI, RSI(14), 5MA, 20MA for OHLCV dataframe.
    Columns expected: ['고가', '저가', '종가', '거래량']
    """
    if len(df) < 30:
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

def evaluate_sell_signal(df):
    """
    Evaluate Sensitive 3-Stage Sell Signals for registered holdings.
    Stage 1 (Warning): +DI peak downturn OR RSI >= 70 breakdown
    Stage 2 (Execution): Close < 5MA OR +DI cross down ADX
    Stage 3 (Exit/StopLoss): Close < 20MA OR -DI cross up +DI
    """
    if len(df) < 3 or 'adx' not in df.columns:
        return None

    curr_adx = df['adx'].iloc[-1]
    curr_pdi, prev_pdi = df['plus_di'].iloc[-1], df['plus_di'].iloc[-2]
    curr_mdi = df['minus_di'].iloc[-1]
    curr_rsi, prev_rsi = df['rsi'].iloc[-1], df['rsi'].iloc[-2]
    curr_close = df['종가'].iloc[-1]
    curr_ma5 = df['ma5'].iloc[-1]
    curr_ma20 = df['ma20'].iloc[-1]

    signals = []

    # Stage 1: +DI peak downturn or RSI 70 exit
    if (curr_pdi > curr_adx) and (curr_pdi < prev_pdi):
        signals.append("1단계 경고 (+DI 고점 꺾임)")
    if (prev_rsi >= 70) and (curr_rsi < 70):
        signals.append("1단계 경고 (RSI 70 과열 탈출)")

    # Stage 2: Close < 5MA or +DI cross down ADX
    if curr_close < curr_ma5:
        signals.append("2단계 익절 (5일선 하향 이탈)")
    if (prev_pdi > prev_adx) and (curr_pdi <= curr_adx):
        signals.append("2단계 익절 (+DI ADX 하향 돌파)")

    # Stage 3: Close < 20MA or Dead Cross (-DI > +DI)
    if curr_close < curr_ma20:
        signals.append("3단계 청산 (20일선 하향 이탈)")
    if curr_mdi > curr_pdi:
        signals.append("3단계 청산 (-DI/+DI 데드크로스)")

    return {
        "has_sell_signal": len(signals) > 0,
        "signal_level": f"{len(signals)}개 경고/매도 조건 포착" if signals else "안정",
        "details": signals,
        "adx": round(curr_adx, 2),
        "rsi": round(curr_rsi, 2) if not np.isnan(curr_rsi) else None,
        "close": int(curr_close)
    }

if __name__ == "__main__":
    print("[INFO] KOSPI 200 Engine Module Initialized.")
