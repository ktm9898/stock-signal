import json
import numpy as np
from data_loader import load_all_preloaded_data

d = load_all_preloaded_data()
raw_data = d['preloaded_data']
START_DATE = '2021-01-04'
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
        arr[i, 0] = r[1] or 0 # open
        arr[i, 1] = r[2] or 0 # high
        arr[i, 2] = r[3] or 0 # low
        arr[i, 3] = r[4] or 0 # close
        arr[i, 4] = r[9] if r[9] is not None else 50
        arr[i, 5] = r[10] if r[10] is not None else 0.5
        arr[i, 6] = r[12] if r[12] is not None else 50
        arr[i, 7] = r[13] if r[13] is not None else 100
        arr[i, 8] = r[14] if r[14] is not None else 100
        arr[i, 9] = r[6] if r[6] is not None else 0
        arr[i, 10] = r[7] if r[7] is not None else 0
        arr[i, 11] = r[8] if r[8] is not None else 0
    stock_arrays.append(arr)
    stock_dates.append(dates)

sorted_sim_dates = sorted(list(all_dates_set))
num_sim_dates = len(sorted_sim_dates)
date_to_idx = {dt: i for i, dt in enumerate(sorted_sim_dates)}

def test_strat(name, buy_fn, sell_fn, sl=None, tp=None):
    total_trades = 0
    win_trades = 0
    total_profit_krw = 0.0
    total_loss_krw = 0.0
    total_ret = 0.0
    total_days = 0
    losses_list = []
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
                        losses_list.append(ret)
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
                losses_list.append(ret)
            total_ret += ret
            total_days += h_days
            d_start = date_to_idx.get(dates[entry_bar_idx], 0)
            d_end = date_to_idx.get(dates[-1], num_sim_dates - 1)
            active_daily[d_start:d_end + 1] += 1
            
    win_rate = win_trades / total_trades * 100.0 if total_trades > 0 else 0
    pf = total_profit_krw / total_loss_krw if total_loss_krw > 0 else 99.9
    avg_ret = total_ret / total_trades if total_trades > 0 else 0
    avg_days = total_days / total_trades if total_trades > 0 else 0
    avg_holdings = float(np.mean(active_daily))
    max_holdings = int(np.max(active_daily))
    net_profit = total_profit_krw - total_loss_krw
    avg_cap = max(1, avg_holdings) * trade_amount
    ret_cap = net_profit / avg_cap * 100.0 if avg_cap > 0 else 0
    max_loss = min(losses_list) if losses_list else 0
    
    return {
        'name': name,
        'trades': total_trades,
        'win_rate': round(float(win_rate), 2),
        'pf': round(float(pf), 2),
        'avg_ret': round(float(avg_ret), 2),
        'avg_days': round(float(avg_days), 1),
        'avg_holdings': round(float(avg_holdings), 1),
        'max_holdings': max_holdings,
        'ret_cap': round(float(ret_cap), 2),
        'max_loss': round(float(max_loss), 2)
    }

def user_hybrid_buy(a, i):
    c1 = (a[i, 4] <= 24 and a[i, 5] <= 0.05 and a[i, 8] >= 100)
    p_m = a[i-1, 11] if i > 0 else a[i, 11]
    p_a = a[i-1, 9] if i > 0 else a[i, 9]
    c2 = (a[i, 9] >= 33 and p_m > p_a and a[i, 11] <= a[i, 9] and a[i, 8] >= 100)
    return c1 or c2

r1 = test_strat('1. 손절 -10% & 익절 +15% (청산: RSI>=55)', user_hybrid_buy, lambda a, i: a[i, 4] >= 55, sl=10, tp=15)
r2 = test_strat('2. 손절/익절 없음 (청산: RSI>=55 단독)', user_hybrid_buy, lambda a, i: a[i, 4] >= 55, sl=None, tp=None)
r3 = test_strat('3. 손절/익절 없음 (청산: RSI>=60 단독)', user_hybrid_buy, lambda a, i: a[i, 4] >= 60, sl=None, tp=None)
r4 = test_strat('4. 손절/익절 없음 (청산: RSI>=65 단독)', user_hybrid_buy, lambda a, i: a[i, 4] >= 65, sl=None, tp=None)
r5 = test_strat('5. 안전 손절 -20%만 유지 (청산: RSI>=55 단독)', user_hybrid_buy, lambda a, i: a[i, 4] >= 55, sl=20, tp=None)

print("\n" + "="*110)
for r in [r1, r2, r3, r4, r5]:
    print(f"[{r['name']}]")
    print(f"  - 승률: {r['win_rate']}% | 손익비: {r['pf']} | 건당수익: {r['avg_ret']}% | 5년체결: {r['trades']}회 | 평잔: {r['avg_holdings']}개 (최대 {r['max_holdings']}개) | 평잔수익률: {r['ret_cap']}% | 최대개별손실: {r['max_loss']}%\n")
print("="*110)
