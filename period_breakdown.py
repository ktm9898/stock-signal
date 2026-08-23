import json
import numpy as np

with open('data/stocks_350_real.json', encoding='utf-8') as f:
    d = json.load(f)

raw_data = d['preloaded_data']
FEE_RATE = 0.0025

stock_arrays = []
stock_dates = []

for ticker, rows in raw_data.items():
    if ticker in ['069500', 'KOSPI', 'KOSDAQ']: continue
    if len(rows) < 10: continue
    dates = [r[0] for r in rows]
    arr = np.zeros((len(rows), 12), dtype=np.float32)
    for i, r in enumerate(rows):
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

def eval_period(s_date, e_date):
    # Strategy 1
    def b1(a, i):
        p_m = a[i-1, 11] if i > 0 else a[i, 11]
        p_a = a[i-1, 9] if i > 0 else a[i, 9]
        return a[i, 9] >= 30 and p_m > p_a and a[i, 11] <= a[i, 9]
    def s1(a, i): return a[i, 4] >= 65
    
    # Sniper
    def bs(a, i): return a[i, 4] <= 24 and a[i, 5] <= 0.05
    def ss(a, i): return a[i, 4] >= 55
    
    def test_strat(b_fn, s_fn, sl=20, tp=None):
        trades = []
        for s_idx in range(len(stock_arrays)):
            arr = stock_arrays[s_idx]
            dates = stock_dates[s_idx]
            n = len(arr)
            in_pos = False
            entry_price = 0.0
            
            for i in range(n - 1):
                dt = dates[i]
                if not (s_date <= dt <= e_date):
                    if in_pos and dt > e_date:
                        # close at period end
                        exit_price = arr[i, 3] * (1.0 - FEE_RATE)
                        ret = (exit_price - entry_price) / entry_price * 100.0
                        trades.append(ret)
                        in_pos = False
                    continue
                    
                if not in_pos:
                    if b_fn(arr, i) and arr[i+1, 0] > 0:
                        in_pos = True
                        entry_price = arr[i+1, 0] * (1.0 + FEE_RATE)
                else:
                    curr_c = arr[i, 3]
                    ret_p = (curr_c - entry_price) / entry_price * 100.0
                    is_exit = False
                    if sl is not None and ret_p <= -sl: is_exit = True
                    elif tp is not None and ret_p >= tp: is_exit = True
                    elif s_fn(arr, i): is_exit = True
                    
                    if is_exit and arr[i+1, 0] > 0:
                        exit_price = arr[i+1, 0] * (1.0 - FEE_RATE)
                        ret = (exit_price - entry_price) / entry_price * 100.0
                        trades.append(ret)
                        in_pos = False
                        
            if in_pos:
                exit_price = arr[-1, 3] * (1.0 - FEE_RATE)
                ret = (exit_price - entry_price) / entry_price * 100.0
                trades.append(ret)
                
        if not trades: return {'win_rate': 0, 'pf': 0, 'avg_ret': 0, 'trades': 0}
        wins = [t for t in trades if t >= 0]
        losses = [t for t in trades if t < 0]
        win_rate = len(wins) / len(trades) * 100.0
        profit_sum = sum(wins)
        loss_sum = abs(sum(losses))
        pf = profit_sum / loss_sum if loss_sum > 0 else 99.9
        avg_ret = sum(trades) / len(trades)
        return {'win_rate': round(win_rate, 1), 'pf': round(pf, 2), 'avg_ret': round(avg_ret, 2), 'trades': len(trades)}

    r_bench = test_strat(b1, s1, sl=20)
    r_sniper = test_strat(bs, ss, sl=10, tp=15)
    return r_bench, r_sniper

periods = [
    ('2021년 (상승/고점)', '2021-01-01', '2021-12-31'),
    ('2022년 (역대급 하락장)', '2022-01-01', '2022-12-31'),
    ('2023년 (반등/테마장)', '2023-01-01', '2023-12-31'),
    ('2024년 (박스/반도체장)', '2024-01-01', '2024-12-31'),
    ('2025~2026년 (최근)', '2025-01-01', '2026-08-20')
]

print("Yearly Breakdown Comparison:")
for label, s_dt, e_dt in periods:
    b, sn = eval_period(s_dt, e_dt)
    print(f"\n[{label}]")
    print(f"  전략 1번: 승률 {b['win_rate']}% | PF {b['pf']} | 건당수익 {b['avg_ret']}% | 체결 {b['trades']}회")
    print(f"  스나이퍼: 승률 {sn['win_rate']}% | PF {sn['pf']} | 건당수익 {sn['avg_ret']}% | 체결 {sn['trades']}회")
