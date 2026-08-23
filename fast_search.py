import json
import numpy as np
from datetime import datetime
from data_loader import load_all_preloaded_data

d = load_all_preloaded_data()
raw_data = d['preloaded_data']
START_DATE = '2021-01-04'
END_DATE = '2026-08-20'
FEE_RATE = 0.0025

# Pack each stock into numpy float32 arrays
# columns: 0:open, 1:high, 2:low, 3:close, 4:rsi, 5:bb_pct, 6:stoch_k, 7:disparity20, 8:volume_ratio, 9:adx, 10:plus_di, 11:minus_di
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

print(f"Loaded {len(stock_arrays)} stocks into NumPy memory. Sim dates: {num_sim_dates}")

def test_strategy(buy_type, p1, p2, p3, exit_type, exit_val, stop_loss=15, take_profit=None, cooldown=10):
    total_trades = 0
    win_trades = 0
    total_profit_pct = 0.0
    total_loss_pct = 0.0
    total_return_pct_sum = 0.0
    total_holding_days = 0
    
    # Active holdings tracker per date
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
            # Check cooldown by bar distance
            if not in_pos:
                if (i - last_stop_loss_bar) < cooldown:
                    continue
                    
                is_buy = False
                if buy_type == 'oversold_rsi_bb':
                    # p1: rsi_max, p2: bb_max, p3: stoch_max
                    if arr[i, 4] <= p1 and arr[i, 5] <= p2:
                        if p3 is None or arr[i, 6] <= p3:
                            is_buy = True
                elif buy_type == 'disparity_bb':
                    # p1: disp_max, p2: bb_max, p3: rsi_max
                    if arr[i, 7] <= p1 and arr[i, 5] <= p2:
                        if p3 is None or arr[i, 4] <= p3:
                            is_buy = True
                elif buy_type == 'trend_pullback':
                    # p1: adx_min, p2: plus_di_min, p3: rsi_max
                    if arr[i, 9] >= p1 and arr[i, 10] >= p2 and arr[i, 10] > arr[i, 11] and arr[i, 4] <= p3:
                        is_buy = True
                        
                if is_buy and arr[i + 1, 0] > 0:
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
                else:
                    if exit_type == 'rsi' and arr[i, 4] >= exit_val:
                        is_exit = True
                    elif exit_type == 'bb' and arr[i, 5] >= exit_val:
                        is_exit = True
                    elif exit_type == 'stoch' and arr[i, 6] >= exit_val:
                        is_exit = True
                        
                if is_exit and arr[i + 1, 0] > 0:
                    exit_price = arr[i + 1, 0] * (1.0 - FEE_RATE)
                    ret = ((exit_price - entry_price) / entry_price) * 100.0
                    h_days = (i + 1) - entry_bar_idx
                    if h_days < 1: h_days = 1
                    
                    total_trades += 1
                    if ret >= 0:
                        win_trades += 1
                        total_profit_pct += ret
                    else:
                        total_loss_pct += abs(ret)
                    total_return_pct_sum += ret
                    total_holding_days += h_days
                    
                    # Mark active days in global calendar
                    d_start = date_to_idx.get(dates[entry_bar_idx], 0)
                    d_end = date_to_idx.get(dates[i + 1], num_sim_dates - 1)
                    active_daily[d_start:d_end + 1] += 1
                    
                    if is_stop:
                        last_stop_loss_bar = i + 1
                    in_pos = False
                    
        # Period end close
        if in_pos:
            exit_price = arr[-1, 3] * (1.0 - FEE_RATE)
            ret = ((exit_price - entry_price) / entry_price) * 100.0
            h_days = max(1, (n_rows - 1) - entry_bar_idx)
            total_trades += 1
            if ret >= 0:
                win_trades += 1
                total_profit_pct += ret
            else:
                total_loss_pct += abs(ret)
            total_return_pct_sum += ret
            total_holding_days += h_days
            d_start = date_to_idx.get(dates[entry_bar_idx], 0)
            d_end = date_to_idx.get(dates[-1], num_sim_dates - 1)
            active_daily[d_start:d_end + 1] += 1
            
    if total_trades < 50:
        return None
        
    win_rate = (win_trades / total_trades) * 100.0
    profit_factor = (total_profit_pct / total_loss_pct) if total_loss_pct > 0 else 99.9
    avg_return_pct = total_return_pct_sum / total_trades
    avg_holding_days = total_holding_days / total_trades
    avg_daily_holdings = float(np.mean(active_daily))
    max_holdings = int(np.max(active_daily))
    
    # Capital Efficiency: Return on Average Capital
    # Average capital = avg_daily_holdings * 1,000,000 KRW
    # Net profit = (total_return_pct_sum / 100.0) * 1,000,000 KRW
    # Return on capital = (total_return_pct_sum / max(1.0, avg_daily_holdings))
    return_on_capital = total_return_pct_sum / max(1.0, avg_daily_holdings)
    
    return {
        'total_trades': total_trades,
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'avg_return_pct': round(avg_return_pct, 2),
        'avg_holding_days': round(avg_holding_days, 1),
        'avg_daily_holdings': round(avg_daily_holdings, 1),
        'max_holdings': max_holdings,
        'return_on_capital': round(return_on_capital, 2)
    }

# Run rapid grid search across high conviction strategies
print("Executing fast grid search...")
candidates = []

# 1. Oversold RSI + Bollinger + Stochastic Filter
for r_max in [25, 28, 30]:
    for b_max in [0.08, 0.12, 0.18]:
        for s_max in [15, 20, None]:
            for e_r in [60, 65, 70]:
                for sl in [10, 15, 20]:
                    for tp in [15, 20, None]:
                        r = test_strategy('oversold_rsi_bb', r_max, b_max, s_max, 'rsi', e_r, sl, tp, 10)
                        if r and r['avg_daily_holdings'] <= 35:
                            candidates.append({
                                'archetype': '과매도 반등형',
                                'name': f"RSI<={r_max} & 볼린저<={b_max}" + (f" & 스토<={s_max}" if s_max else ""),
                                'buy': f"RSI <= {r_max}, 볼린저 %b <= {b_max}" + (f", 스토캐스틱 %K <= {s_max}" if s_max else ""),
                                'sell': f"RSI >= {e_r}",
                                'stop_loss': sl,
                                'take_profit': tp,
                                'cooldown': 10,
                                **r
                            })

# 2. Disparity + Bollinger Oversold
for d_max in [90, 92, 94]:
    for b_max in [0.05, 0.1, 0.15]:
        for r_max in [30, 35, None]:
            for e_b in [0.85, 0.95]:
                for sl in [10, 15]:
                    for tp in [15, 20, None]:
                        r = test_strategy('disparity_bb', d_max, b_max, r_max, 'bb', e_b, sl, tp, 10)
                        if r and r['avg_daily_holdings'] <= 35:
                            candidates.append({
                                'archetype': '이격도 과매도형',
                                'name': f"이격도<={d_max}% & 볼린저<={b_max}" + (f" & RSI<={r_max}" if r_max else ""),
                                'buy': f"이격도(20일) <= {d_max}%, 볼린저 %b <= {b_max}" + (f", RSI <= {r_max}" if r_max else ""),
                                'sell': f"볼린저 %b >= {e_b}",
                                'stop_loss': sl,
                                'take_profit': tp,
                                'cooldown': 10,
                                **r
                            })

# 3. Trend Pullback
for adx_min in [25, 30]:
    for p_di_min in [25, 30]:
        for r_max in [50, 55]:
            for e_r in [65, 70, 75]:
                for sl in [10, 15]:
                    for tp in [15, 20, None]:
                        r = test_strategy('trend_pullback', adx_min, p_di_min, r_max, 'rsi', e_r, sl, tp, 10)
                        if r and r['avg_daily_holdings'] <= 35:
                            candidates.append({
                                'archetype': '추세 눌림목형',
                                'name': f"ADX>={adx_min} & +DI>={p_di_min} & RSI<={r_max}",
                                'buy': f"ADX >= {adx_min}, +DI >= {p_di_min}, +DI > -DI, RSI <= {r_max}",
                                'sell': f"RSI >= {e_r}",
                                'stop_loss': sl,
                                'take_profit': tp,
                                'cooldown': 10,
                                **r
                            })

print(f"Total candidate strategies found: {len(candidates)}")

# Top Win-Rate Strategies (승률 극대화형)
top_win = sorted(candidates, key=lambda x: (x['win_rate'], x['profit_factor']), reverse=True)[:5]
# Top Capital Efficiency (평잔 대비 누적 수익률 극대화형)
top_return = sorted(candidates, key=lambda x: (x['return_on_capital'], x['profit_factor']), reverse=True)[:5]
# Top Profit Factor
top_pf = sorted(candidates, key=lambda x: (x['profit_factor'], x['win_rate']), reverse=True)[:5]

print("\n" + "="*85)
print("🏆 [TOP 3 승률 극대화형 전략 (평잔 10~30개 이하 / 승률 70~76%+)]")
print("="*85)
for i, s in enumerate(top_win[:3], 1):
    print(f"\n[{i}] {s['archetype']}: {s['name']}")
    print(f"  - 매수 조건: {s['buy']}")
    print(f"  - 매도 조건: {s['sell']} | 익절선: {s['take_profit']}% | 손절선: -{s['stop_loss']}% | 쿨다운: {s['cooldown']}일")
    print(f"  - 🎯 승률: {s['win_rate']}% | 손익비(PF): {s['profit_factor']} | 평균수익률: {s['avg_return_pct']}% | 총 체결: {s['total_trades']}회")
    print(f"  - 💼 평잔 보유: {s['avg_daily_holdings']}개 (최대 {s['max_holdings']}개) | 평균보유일: {s['avg_holding_days']}일 | 💰 평잔대비 수익률: {s['return_on_capital']}%")

print("\n" + "="*85)
print("🚀 [TOP 3 평잔 대비 총수익률 극대화형 전략 (자본 회전율 & 복리 최강)]")
print("="*85)
for i, s in enumerate(top_return[:3], 1):
    print(f"\n[{i}] {s['archetype']}: {s['name']}")
    print(f"  - 매수 조건: {s['buy']}")
    print(f"  - 매도 조건: {s['sell']} | 익절선: {s['take_profit']}% | 손절선: -{s['stop_loss']}% | 쿨다운: {s['cooldown']}일")
    print(f"  - 🎯 승률: {s['win_rate']}% | 손익비(PF): {s['profit_factor']} | 평균수익률: {s['avg_return_pct']}% | 총 체결: {s['total_trades']}회")
    print(f"  - 💼 평잔 보유: {s['avg_daily_holdings']}개 (최대 {s['max_holdings']}개) | 평균보유일: {s['avg_holding_days']}일 | 💰 평잔대비 수익률: {s['return_on_capital']}%")

with open('fast_results.json', 'w', encoding='utf-8') as f:
    json.dump({'top_win': top_win, 'top_return': top_return, 'top_pf': top_pf}, f, ensure_ascii=False, indent=2)
