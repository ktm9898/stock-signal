import json
import numpy as np
from datetime import datetime

with open('data/stocks_350_real.json', encoding='utf-8') as f:
    d = json.load(f)

raw_data = d['preloaded_data']
START_DATE = '2021-01-04'
END_DATE = '2026-08-20'
FEE_RATE = 0.0025

stock_arrays = []
stock_dates = []
all_dates_set = set()

for ticker, rows in raw_data.items():
    if ticker in ['069500', 'KOSPI', 'KOSDAQ']:
        continue
    
    sub = [r for r in rows if START_DATE <= r[0] <= END_DATE]
    if len(sub) < 10:
        continue
        
    dates = [r[0] for r in sub]
    for dt in dates:
        all_dates_set.add(dt)
        
    arr = np.zeros((len(sub), 12), dtype=np.float32)
    for i, r in enumerate(sub):
        arr[i, 0] = r[1] or 0 # open
        arr[i, 1] = r[2] or 0 # high
        arr[i, 2] = r[3] or 0 # low
        arr[i, 3] = r[4] or 0 # close
        arr[i, 4] = r[9] if r[9] is not None else 50 # rsi
        arr[i, 5] = r[10] if r[10] is not None else 0.5 # bb_pct
        arr[i, 6] = r[12] if r[12] is not None else 50 # stoch_k
        arr[i, 7] = r[13] if r[13] is not None else 100 # disparity20
        arr[i, 8] = r[14] if r[14] is not None else 100 # volume_ratio
        arr[i, 9] = r[6] if r[6] is not None else 0 # adx
        arr[i, 10] = r[7] if r[7] is not None else 0 # plus_di
        arr[i, 11] = r[8] if r[8] is not None else 0 # minus_di
        
    stock_arrays.append(arr)
    stock_dates.append(dates)

sorted_sim_dates = sorted(list(all_dates_set))
num_sim_dates = len(sorted_sim_dates)
date_to_idx = {dt: i for i, dt in enumerate(sorted_sim_dates)}

def run_eval(name, buy_fn, sell_fn, stop_loss=15, take_profit=None, cooldown=10):
    total_trades = 0
    win_trades = 0
    total_profit_krw = 0.0
    total_loss_krw = 0.0
    total_return_pct_sum = 0.0
    total_holding_days = 0
    trade_amount = 1000000
    
    active_daily = np.zeros(num_sim_dates, dtype=np.int32)
    
    for s_idx in range(len(stock_arrays)):
        arr = stock_arrays[s_idx]
        dates = stock_dates[s_idx]
        n_rows = len(arr)
        
        in_pos = False
        entry_price = 0.0
        entry_bar_idx = 0
        last_stop_loss_bar = -9999
        
        for i in range(n_rows - 1):
            if not in_pos:
                if (i - last_stop_loss_bar) < cooldown:
                    continue
                if buy_fn(arr, i) and arr[i + 1, 0] > 0:
                    in_pos = True
                    entry_price = arr[i + 1, 0] * (1.0 + FEE_RATE)
                    entry_bar_idx = i + 1
            else:
                curr_close = arr[i, 3]
                paper_return = ((curr_close - entry_price) / entry_price) * 100.0
                is_exit = False
                is_stop = False
                
                if stop_loss is not None and paper_return <= -stop_loss:
                    is_exit = True
                    is_stop = True
                elif take_profit is not None and paper_return >= take_profit:
                    is_exit = True
                elif sell_fn(arr, i):
                    is_exit = True
                    
                if is_exit and arr[i + 1, 0] > 0:
                    exit_price = arr[i + 1, 0] * (1.0 - FEE_RATE)
                    ret = ((exit_price - entry_price) / entry_price) * 100.0
                    h_days = max(1, (i + 1) - entry_bar_idx)
                    
                    total_trades += 1
                    gain_krw = trade_amount * (ret / 100.0)
                    if ret >= 0:
                        win_trades += 1
                        total_profit_krw += gain_krw
                    else:
                        total_loss_krw += abs(gain_krw)
                    total_return_pct_sum += ret
                    total_holding_days += h_days
                    
                    d_start = date_to_idx.get(dates[entry_bar_idx], 0)
                    d_end = date_to_idx.get(dates[i + 1], num_sim_dates - 1)
                    active_daily[d_start:d_end + 1] += 1
                    
                    if is_stop:
                        last_stop_loss_bar = i + 1
                    in_pos = False
                    
        if in_pos:
            exit_price = arr[-1, 3] * (1.0 - FEE_RATE)
            ret = ((exit_price - entry_price) / entry_price) * 100.0
            h_days = max(1, (n_rows - 1) - entry_bar_idx)
            gain_krw = trade_amount * (ret / 100.0)
            total_trades += 1
            if ret >= 0:
                win_trades += 1
                total_profit_krw += gain_krw
            else:
                total_loss_krw += abs(gain_krw)
            total_return_pct_sum += ret
            total_holding_days += h_days
            d_start = date_to_idx.get(dates[entry_bar_idx], 0)
            d_end = date_to_idx.get(dates[-1], num_sim_dates - 1)
            active_daily[d_start:d_end + 1] += 1
            
    win_rate = (win_trades / total_trades) * 100.0 if total_trades > 0 else 0.0
    profit_factor = (total_profit_krw / total_loss_krw) if total_loss_krw > 0 else 99.9
    avg_ret = total_return_pct_sum / total_trades if total_trades > 0 else 0.0
    avg_days = total_holding_days / total_trades if total_trades > 0 else 0.0
    avg_holdings = float(np.mean(active_daily))
    max_holdings = int(np.max(active_daily))
    
    net_profit_krw = total_profit_krw - total_loss_krw
    avg_capital = max(1, avg_holdings) * trade_amount
    return_on_avg_cap = (net_profit_krw / avg_capital) * 100.0 if avg_capital > 0 else 0.0
    
    return {
        'name': name,
        'total_trades': total_trades,
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'avg_return': round(avg_ret, 2),
        'avg_days': round(avg_days, 1),
        'avg_holdings': round(avg_holdings, 1),
        'max_holdings': max_holdings,
        'net_profit_million': round(net_profit_krw / 1000000, 1),
        'return_on_avg_cap': round(return_on_avg_cap, 2)
    }

# 1. Benchmark (전략 1번)
def b1_buy(a, i):
    prev_minus = a[i-1, 11] if i > 0 else a[i, 11]
    prev_adx = a[i-1, 9] if i > 0 else a[i, 9]
    return a[i, 9] >= 30 and prev_minus > prev_adx and a[i, 11] <= a[i, 9]
def b1_sell(a, i): return a[i, 4] >= 65

# 2. Strategy A: Ultra High-Winrate Oversold Triple Filter (초고승률 과매도 3중필터)
# RSI <= 28 AND 볼린저 %b <= 0.12 AND 스토캐스틱 %K <= 20
def sa_buy(a, i): return a[i, 4] <= 28 and a[i, 5] <= 0.12 and a[i, 6] <= 20
def sa_sell(a, i): return a[i, 4] >= 65

# 3. Strategy B: Sniper Extreme Oversold (스나이퍼 초과매도 반등)
# RSI <= 25 AND 볼린저 %b <= 0.08
def sb_buy(a, i): return a[i, 4] <= 25 and a[i, 5] <= 0.08
def sb_sell(a, i): return a[i, 4] >= 60

# 4. Strategy C: Disparity Rebound (이격도 바닥 급반등)
# 이격도(20일) <= 92% AND 볼린저 %b <= 0.10
def sc_buy(a, i): return a[i, 7] <= 92 and a[i, 5] <= 0.10
def sc_sell(a, i): return a[i, 5] >= 0.90

# 5. Strategy D: Volume Surge Reversal (거래량 폭발 바닥 탈출형)
# 거래량비율 >= 180% AND RSI <= 32 AND 볼린저 %b <= 0.18
def sd_buy(a, i): return a[i, 8] >= 180 and a[i, 4] <= 32 and a[i, 5] <= 0.18
def sd_sell(a, i): return a[i, 4] >= 65

# 6. Strategy E: Trend Momentum Pullback (추세 모멘텀 눌림목)
# ADX >= 28 AND +DI >= 25 AND +DI > -DI AND RSI 45~55
def se_buy(a, i): return a[i, 9] >= 28 and a[i, 10] >= 25 and a[i, 10] > a[i, 11] and (45 <= a[i, 4] <= 55)
def se_sell(a, i): return a[i, 4] >= 70

# 7. Strategy F: Dual DNF Compound (과매도 반등 OR 추세 눌림목)
# Group 1: RSI <= 28 & 볼린저 <= 0.12
# Group 2: ADX >= 28 & +DI >= 25 & RSI <= 55
def sf_buy(a, i):
    g1 = a[i, 4] <= 28 and a[i, 5] <= 0.12
    g2 = a[i, 9] >= 28 and a[i, 10] >= 25 and a[i, 10] > a[i, 11] and a[i, 4] <= 55
    return g1 or g2
def sf_sell(a, i): return a[i, 4] >= 65

strategies = [
    run_eval("0. 전략 1번 (기존 벤치마크)", b1_buy, b1_sell, stop_loss=20, take_profit=None, cooldown=10),
    run_eval("A. 초고승률 과매도 3중필터", sa_buy, sa_sell, stop_loss=15, take_profit=20, cooldown=10),
    run_eval("B. 스나이퍼 바닥 반등 (초소수 집중형)", sb_buy, sb_sell, stop_loss=10, take_profit=15, cooldown=10),
    run_eval("C. 이격도 과매도 급반등", sc_buy, sc_sell, stop_loss=12, take_profit=20, cooldown=10),
    run_eval("D. 거래량 실린 바닥 턴어라운드", sd_buy, sd_sell, stop_loss=10, take_profit=20, cooldown=10),
    run_eval("E. 추세 모멘텀 눌림목", se_buy, se_sell, stop_loss=10, take_profit=25, cooldown=10),
    run_eval("F. 복합 DNF (과매도 OR 추세돌파)", sf_buy, sf_sell, stop_loss=15, take_profit=20, cooldown=10)
]

print("\n" + "="*105)
print(f"{'전략명':<28} | {'승률':<7} | {'손익비':<6} | {'평균수익':<7} | {'총체결':<7} | {'평잔종목':<8} | {'최대보유':<8} | {'평잔수익률':<10}")
print("="*105)

for s in strategies:
    print(f"{s['name']:<28} | {s['win_rate']:>5}% | {s['profit_factor']:>5} | {s['avg_return']:>6}% | {s['total_trades']:>5}회 | {s['avg_holdings']:>6}개 | {s['max_holdings']:>6}개 | {s['return_on_avg_cap']:>8}%")
print("="*105)

with open('curated_results.json', 'w', encoding='utf-8') as f:
    json.dump(strategies, f, ensure_ascii=False, indent=2)
