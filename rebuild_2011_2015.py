"""
2011~2015 백테스트 데이터 정밀 복원 스크립트
- 야후 파이낸스 개별 루프 다운로드 (배치 병합 버그 방지)
- 종목별 단독 다운로드 후 수동 병합
- 지표 계산 후 2011-01-01~2015-12-31 필터링 저장
"""
import os
import sys
import json
import time
import pandas as pd
import numpy as np
import yfinance as yf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from data_loader import calculate_full_indicators, get_kospi200_tickers, get_kosdaq150_tickers
from update_backtest_data import convert_df_to_array_rows

DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "history_2011_2015.json")

# 데이터 범위: 지표 warm-up을 위해 2010-06-01부터 다운로드, 저장은 2011-01-01부터
DOWNLOAD_START = "2010-06-01"
DOWNLOAD_END   = "2015-12-31"
SAVE_START     = "2011-01-01"
SAVE_END       = "2015-12-31"

BENCHMARK_MAP = {
    "^KS11": "KOSPI",
    "^KQ11": "KOSDAQ",
}

def fetch_single_ticker_yf(yf_symbol, clean_sym, download_start, download_end):
    """야후 파이낸스에서 단일 종목 개별 다운로드 (배치 병합 버그 없음)"""
    try:
        df = yf.download(
            yf_symbol,
            start=download_start,
            end=download_end,
            progress=False,
            auto_adjust=True,
        )
        if df is None or len(df) < 30:
            return None

        # 멀티인덱스 컬럼 처리 (yfinance 버전에 따라 다름)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(columns={
            'Open': '시가', 'High': '고가', 'Low': '저가',
            'Close': '종가', 'Volume': '거래량'
        })

        # 필요한 컬럼만 유지
        needed = ['시가', '고가', '저가', '종가', '거래량']
        df = df[[c for c in needed if c in df.columns]].copy()
        df = df.dropna(subset=['시가', '고가', '저가', '종가'])

        if len(df) < 30:
            return None

        # 기술지표 계산
        df = calculate_full_indicators(df)
        df['Date'] = df.index.strftime('%Y-%m-%d')
        return df
    except Exception as e:
        return None

def main():
    print("=" * 60)
    print("2011~2015 백테스트 데이터 복원 시작")
    print(f"다운로드 범위: {DOWNLOAD_START} ~ {DOWNLOAD_END}")
    print(f"저장 범위: {SAVE_START} ~ {SAVE_END}")
    print("=" * 60)

    # 종목 리스트 로드
    kospi_items = get_kospi200_tickers()[:200]
    kosdaq_items = get_kosdaq150_tickers()[:150]
    all_stocks = kospi_items + kosdaq_items
    print(f"\n대상 종목 수: {len(all_stocks)}개 + 벤치마크 2개\n")

    data_2011_2015 = {}
    success_count = 0
    fail_count = 0
    no_data_count = 0

    # ── 개별 종목 루프 다운로드 ──
    for idx, item in enumerate(all_stocks):
        ticker = item['ticker']
        name = item.get('name', ticker)
        market = item.get('market', '')
        suffix = ".KQ" if market == "KOSDAQ150" else ".KS"
        yf_sym = f"{ticker}{suffix}"

        df = fetch_single_ticker_yf(yf_sym, ticker, DOWNLOAD_START, DOWNLOAD_END)
        if df is None or len(df) == 0:
            no_data_count += 1
            status = "NO DATA"
        else:
            # 저장 범위로 필터링
            df_filtered = df[(df['Date'] >= SAVE_START) & (df['Date'] <= SAVE_END)].copy()
            if len(df_filtered) > 0:
                rows = convert_df_to_array_rows(df_filtered)
                data_2011_2015[ticker] = rows
                success_count += 1
                status = f"OK ({df_filtered['Date'].iloc[0]} ~ {df_filtered['Date'].iloc[-1]}, {len(df_filtered)}일)"
            else:
                no_data_count += 1
                status = "FILTERED EMPTY"

        if (idx + 1) % 10 == 0 or idx == 0:
            print(f"[{idx+1:3d}/{len(all_stocks)}] {name}({ticker}) → {status}")

        # 야후 파이낸스 서버 부하 방지 (너무 빠르면 차단 가능)
        time.sleep(0.15)

    # ── 벤치마크 (KOSPI, KOSDAQ 지수) ──
    print("\n[벤치마크 다운로드]")
    for yf_sym, clean_sym in BENCHMARK_MAP.items():
        df = fetch_single_ticker_yf(yf_sym, clean_sym, DOWNLOAD_START, DOWNLOAD_END)
        if df is not None and len(df) > 0:
            df_filtered = df[(df['Date'] >= SAVE_START) & (df['Date'] <= SAVE_END)].copy()
            if len(df_filtered) > 0:
                rows = convert_df_to_array_rows(df_filtered)
                data_2011_2015[clean_sym] = rows
                print(f"  {clean_sym}: OK ({len(df_filtered)}일)")
            else:
                print(f"  {clean_sym}: 필터 후 데이터 없음")
        else:
            print(f"  {clean_sym}: 다운로드 실패")
        time.sleep(0.3)

    # ── 결과 저장 ──
    print(f"\n[저장 중] {OUTPUT_PATH}")
    payload = {
        "stocks": all_stocks,
        "preloaded_data": data_2011_2015
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))

    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)

    # 날짜 범위 요약
    min_d, max_d = '9999-99-99', '0000-00-00'
    for sym, r_list in data_2011_2015.items():
        if r_list:
            if r_list[0][0] < min_d: min_d = r_list[0][0]
            if r_list[-1][0] > max_d: max_d = r_list[-1][0]

    print("\n" + "=" * 60)
    print("복원 완료!")
    print(f"  저장 종목 수: {len(data_2011_2015)}개")
    print(f"  성공: {success_count}건 / 데이터없음: {no_data_count}건 / 실패: {fail_count}건")
    print(f"  날짜 범위: {min_d} ~ {max_d}")
    print(f"  파일 크기: {size_mb:.2f} MB")
    print("=" * 60)

if __name__ == "__main__":
    main()
