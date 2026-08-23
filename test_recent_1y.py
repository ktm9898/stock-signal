import json
import numpy as np

with open('data/stocks_350_real.json', encoding='utf-8') as f:
    d = json.load(f)

raw_data = d['preloaded_data']
START_DATE = '2025-06-01'
END_DATE = '2026-08-20'
FEE_RATE = 0.0025

stock_arrays = []
stock_dates = []
all_dates_set = set()

for ticker, rows in raw_data.items():
    if ticker in ['069500', 'KOSPI', 'KOSDAQ']: continue
    sub = [r for r in rows if START_DATE <= r[0] <= END_DATE]
    if len(sub) < 10: continue
    dates = [r[0] for r in sub]
    for dt in dates: all_dates_set.add(dt)
    arr = np.zeros((len(sub), 12), dtype=np.float32)
    for i, r in enumerate(sub):
        arr[i, 0] = r[1] or 0
        arr[i, 1] = r[2] or 0
        arr[i, 2] = r[3] or 0
        arr[i, 3] = r[4] or 0
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

def run_test(name, buy_fn, sell_fn, sl=10, tp=None):
    total_trades = 0
    win_trades = 0
    total_profit_krw = 0.0
    total_loss_krw = 0.0
    total_ret = 0.0
    total_days = 0
    active_daily = np.zeros(num_sim_dates, dtype=np.int32)
    trade_amount = 1000000
    
    for s_idx in range(len(stock_arrays)):
        arr = stock_arrays[s_idx]
        dates = stock_dates[s_idx]
        n_rows = len(arr)
        in_pos = False
        entry_price = 0.0
        entry_bar_idx = 0
        
        for i in range(n_rows - 1):
            if not in_pos:
                if buy_fn(arr, i) and arr[i + 1, 0] > 0:
                    in_pos = True
                    entry_price = arr[i + 1, 0] * (1.0 + FEE_RATE)
                    entry_bar_idx = i + 1
            else:
                curr_close = arr[i, 3]
                paper_return = ((curr_close - entry_price) / entry_price) * 100.0
                is_exit = False
                if sl is not None and paper_return <= -sl: is_exit = True
                elif tp is not None and paper_return >= tp: is_exit = True
                elif sell_fn(arr, i): is_exit = True
                    
                if is_exit and arr[i + 1, 0] > 0:
                    exit_price = arr[i + 1, 0] * (1.0 - FEE_RATE)
                    ret = ((exit_price - entry_price) / entry_price) * 100.0
                    h_days = max(1, (i + 1) - entry_bar_idx)
                    total_trades += 1
                    gain = trade_amount * (ret / 100.0)
                    if ret >= 0:
                        win_trades += 1
                        total_profit_krw += gain
                    else:
                        total_loss_krw += abs(gain)
                    total_ret += ret
                    total_days += h_days
                    d_start = date_to_idx.get(dates[entry_bar_idx], 0)
                    d_end = date_to_idx.get(dates[i + 1], num_sim_dates - 1)
                    active_daily[d_start:d_end + 1] += 1
                    in_pos = False
                    
        if in_pos:
            exit_price = arr[-1, 3] * (1.0 - FEE_RATE)
            ret = ((exit_price - entry_price) / entry_price) * 100.0
            h_days = max(1, (n_rows - 1) - entry_bar_idx)
            total_trades += 1
            gain = trade_amount * (ret / 100.0)
            if ret >= 0:
                win_trades += 1
                total_profit_krw += gain
            else:
                total_loss_krw += abs(gain)
            total_ret += ret
            total_days += h_days
            d_start = date_to_idx.get(dates[entry_bar_idx], 0)
            d_end = date_to_idx.get(dates[-1], num_sim_dates - 1)
            active_daily[d_start:d_end + 1] += 1
            
    if total_trades == 0: return None
    win_rate = win_trades / total_trades * 100.0
    pf = total_profit_krw / total_loss_krw if total_loss_krw > 0 else 99.9
    avg_ret = total_ret / total_trades
    avg_days = total_days / total_trades
    avg_holdings = float(np.mean(active_daily))
    max_holdings = int(np.max(active_daily))
    net_profit = total_profit_krw - total_loss_krw
    avg_cap = max(1, avg_holdings) * trade_amount
    ret_cap = net_profit / avg_cap * 100.0 if avg_cap > 0 else 0
    
    return {
        'name': name,
        'trades': total_trades,
        'win_rate': round(float(win_rate), 2),
        'pf': round(float(pf), 2),
        'avg_ret': round(float(avg_ret), 2),
        'avg_days': round(float(avg_days), 1),
        'avg_holdings': round(float(avg_holdings), 1),
        'max_holdings': max_holdings,
        'ret_cap': round(float(ret_cap), 2)
    }

# 1. 스나이퍼
def s_buy(a, i): return a[i, 4] <= 24 and a[i, 5] <= 0.05 and a[i, 8] >= 100
def s_sell(a, i): return a[i, 4] >= 55

# 2. 전략 1번 (추세추종)
def b1_buy(a, i):
    p_m = a[i-1, 11] if i > 0 else a[i, 11]
    p_a = a[i-1, 9] if i > 0 else a[i, 9]
    return a[i, 9] >= 30 and p_m > p_a and a[i, 11] <= a[i, 9]
def b1_sell(a, i): return a[i, 4] >= 65

# 3. 주도주 추세 눌림목 (추세강도 + 볼린저 중심선 지지 + 거래량)
# ADX >= 25 AND +DI >= 25 AND +DI > -DI AND 볼린저 %b >= 0.4 AND RSI <= 55
def trend_buy(a, i):
    return a[i, 9] >= 25 and a[i, 10] >= 25 and a[i, 10] > a[i, 11] and a[i, 5] >= 0.4 and a[i, 4] <= 55
def trend_sell(a, i): return a[i, 4] >= 68

# 4. 듀얼 결합 전략 (조건1: 스나이퍼 과매도 OR 조건2: 주도주 눌림목)
def dual_buy(a, i):
    g1 = (a[i, 4] <= 24 and a[i, 5] <= 0.05 and a[i, 8] >= 100)
    g2 = (a[i, 9] >= 25 and a[i, 10] >= 25 and a[i, 10] > a[i, 11] and a[i, 5] >= 0.4 and a[i, 4] <= 55)
    return g1 or g2
def dual_sell(a, i): return a[i, 4] >= 60

r1 = run_test('1. 스나이퍼 (과매도 저점잡기)', s_buy, s_sell, 10, 15)
r2 = run_test('2. 전략 1번 (기존 추세추종)', b1_buy, b1_sell, 20, None)
r3 = run_test('3. 주도주 추세 눌림목 (모멘텀)', trend_buy, trend_sell, 10, 20)
r4 = run_test('4. 듀얼 복합 (저점반등 OR 주도주눌림목)', dual_buy, dual_sell, 10, 18)

print("\n" + "="*95)
print("--- 최근 1년 (2025.06 ~ 2026.08) 시장별 성과 비교 ---")
for r in [r1, r2, r3, r4]:
    if r:
        print(f"[{r['name']}]")
        print(f"  - 승률: {r['win_rate']}% | 손익비: {r['pf']} | 평균수익률: {r['avg_ret']}% | 체결: {r['trades']}회 | 평잔: {r['avg_holdings']}개 (최대 {r['max_holdings']}개) | 평잔대비수익률: {r['ret_cap']}%\n")
print("="*95)
