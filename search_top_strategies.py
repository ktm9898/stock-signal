import json
import sys
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

with open('data/stocks_350_real.json', encoding='utf-8') as f:
    d = json.load(f)

raw_data = d['preloaded_data']
START_DATE = '2021-01-04'
END_DATE = '2026-08-20'
FEE_RATE = 0.0025

preprocessed_stocks = {}
all_dates_set = set()

for ticker, rows in raw_data.items():
    if ticker in ['069500', 'KOSPI', 'KOSDAQ']:
        continue
    
    clean_rows = []
    for r in rows:
        dt = r[0]
        if START_DATE <= dt <= END_DATE:
            all_dates_set.add(dt)
        clean_rows.append((
            r[0], # 0: date
            r[1], # 1: open
            r[2], # 2: high
            r[3], # 3: low
            r[4], # 4: close
            r[5], # 5: volume
            r[6] if r[6] is not None else 0, # 6: adx
            r[7] if r[7] is not None else 0, # 7: plus_di
            r[8] if r[8] is not None else 0, # 8: minus_di
            r[9] if r[9] is not None else 50, # 9: rsi
            r[10] if r[10] is not None else 0.5, # 10: bb_pct
            r[11] if r[11] is not None else 0, # 11: macd
            r[12] if r[12] is not None else 50, # 12: stoch_k
            r[13] if r[13] is not None else 100, # 13: disparity20
            r[14] if r[14] is not None else 100 # 14: volume_ratio
        ))
    clean_rows.sort(key=lambda x: x[0])
    preprocessed_stocks[ticker] = clean_rows

sorted_sim_dates = sorted(list(all_dates_set))
sim_dates_count = len(sorted_sim_dates)

def evaluate_single_config(cfg):
    # cfg is a dict with strategy definitions
    trade_amount = 1000000
    trades = []
    
    strat_type = cfg['type']
    stop_loss = cfg.get('stop_loss', 20)
    take_profit = cfg.get('take_profit', None)
    cooldown_days = cfg.get('cooldown', 10)
    
    for ticker, all_rows in preprocessed_stocks.items():
        rows = [r for r in all_rows if START_DATE <= r[0] <= END_DATE]
        if len(rows) < 10:
            continue
            
        in_pos = False
        entry_price = 0
        entry_date = ""
        last_stop_loss_date = ""
        
        for i in range(len(rows) - 1):
            curr = rows[i]
            nxt = rows[i + 1]
            prev = rows[i - 1] if i > 0 else curr
            
            # Cooldown check
            is_cooldown = False
            if cooldown_days > 0 and last_stop_loss_date:
                # Fast date diff in days approximation
                d1 = datetime.strptime(curr[0], '%Y-%m-%d')
                d2 = datetime.strptime(last_stop_loss_date, '%Y-%m-%d')
                if (d1 - d2).days < cooldown_days:
                    is_cooldown = True
                    
            if not in_pos:
                if not is_cooldown:
                    # Check buy condition based on strat_type
                    is_buy = False
                    if strat_type == 'oversold':
                        # rsi <= r_t, bb <= b_t, stoch <= s_t, vol >= v_t
                        if curr[9] <= cfg['rsi'] and curr[10] <= cfg['bb']:
                            if cfg['stoch'] is None or curr[12] <= cfg['stoch']:
                                if cfg['vol'] is None or curr[14] >= cfg['vol']:
                                    is_buy = True
                    elif strat_type == 'trend_pullback':
                        # adx >= a_t, plus_di >= p_t, plus_di > minus_di, rsi in [r_l, r_h]
                        if curr[6] >= cfg['adx'] and curr[7] >= cfg['plus_di'] and curr[7] > curr[8]:
                            if cfg['rsi_min'] <= curr[9] <= cfg['rsi_max']:
                                is_buy = True
                    elif strat_type == 'disparity_oversold':
                        # disparity <= d_t, bb <= b_t
                        if curr[13] <= cfg['disp'] and curr[10] <= cfg['bb']:
                            is_buy = True
                    elif strat_type == 'stoch_rsi_double':
                        # stoch_k <= s_k AND rsi <= r_t AND bb <= b_t
                        if curr[12] <= cfg['stoch'] and curr[9] <= cfg['rsi'] and curr[10] <= cfg['bb']:
                            is_buy = True
                            
                    if is_buy and nxt[1] > 0:
                        in_pos = True
                        entry_price = nxt[1] * (1 + FEE_RATE)
                        entry_date = nxt[0]
            else:
                curr_close = curr[4]
                paper_return_pct = ((curr_close - entry_price) / entry_price) * 100
                is_exit = False
                trigger_type = "SIGNAL"
                
                if stop_loss is not None and paper_return_pct <= -abs(stop_loss):
                    is_exit = True
                    trigger_type = "STOP_LOSS"
                    last_stop_loss_date = nxt[0]
                elif take_profit is not None and paper_return_pct >= abs(take_profit):
                    is_exit = True
                    trigger_type = "TAKE_PROFIT"
                else:
                    # Signal exit
                    if cfg['exit_type'] == 'rsi' and curr[9] >= cfg['exit_val']:
                        is_exit = True
                    elif cfg['exit_type'] == 'bb' and curr[10] >= cfg['exit_val']:
                        is_exit = True
                    elif cfg['exit_type'] == 'stoch' and curr[12] >= cfg['exit_val']:
                        is_exit = True
                        
                if is_exit and nxt[1] > 0:
                    exit_price = nxt[1] * (1 - FEE_RATE)
                    actual_return_pct = ((exit_price - entry_price) / entry_price) * 100
                    d_entry = datetime.strptime(entry_date, '%Y-%m-%d')
                    d_exit = datetime.strptime(nxt[0], '%Y-%m-%d')
                    holding_days = max(1, (d_exit - d_entry).days)
                    trades.append({
                        'returnPct': actual_return_pct,
                        'holdingDays': holding_days,
                        'entryDate': entry_date,
                        'exitDate': nxt[0],
                        'win': actual_return_pct >= 0
                    })
                    in_pos = False
                    
        if in_pos and len(rows) > 0:
            last_r = rows[-1]
            exit_price = last_r[4] * (1 - FEE_RATE)
            actual_return_pct = ((exit_price - entry_price) / entry_price) * 100
            d_entry = datetime.strptime(entry_date, '%Y-%m-%d')
            d_exit = datetime.strptime(last_r[0], '%Y-%m-%d')
            holding_days = max(1, (d_exit - d_entry).days)
            trades.append({
                'returnPct': actual_return_pct,
                'holdingDays': holding_days,
                'entryDate': entry_date,
                'exitDate': last_r[0],
                'win': actual_return_pct >= 0
            })
            
    total_trades = len(trades)
    if total_trades < 60:
        return None
        
    wins = [t for t in trades if t['win']]
    losses = [t for t in trades if not t['win']]
    win_rate = (len(wins) / total_trades) * 100
    
    total_profit_krw = sum(trade_amount * (t['returnPct'] / 100) for t in wins)
    total_loss_krw = abs(sum(trade_amount * (t['returnPct'] / 100) for t in losses))
    net_profit_krw = total_profit_krw - total_loss_krw
    
    profit_factor = (total_profit_krw / total_loss_krw) if total_loss_krw > 0 else (99.9 if total_profit_krw > 0 else 1.0)
    avg_return_pct = sum(t['returnPct'] for t in trades) / total_trades
    avg_holding_days = sum(t['holdingDays'] for t in trades) / total_trades
    
    # Calculate daily active holdings
    daily_active = [sum(1 for t in trades if t['entryDate'] <= dt <= t['exitDate']) for dt in sorted_sim_dates]
    avg_holdings = sum(daily_active) / sim_dates_count if sim_dates_count else 1.0
    max_holdings = max(daily_active) if daily_active else 0
    avg_capital = max(1, avg_holdings) * trade_amount
    return_on_avg_cap = (net_profit_krw / avg_capital) * 100 if avg_capital > 0 else 0
    
    return {
        'name': cfg['name'],
        'buy_desc': cfg['buy_desc'],
        'sell_desc': cfg['sell_desc'],
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'cooldown': cooldown_days,
        'total_trades': total_trades,
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'avg_return_pct': round(avg_return_pct, 2),
        'avg_holding_days': round(avg_holding_days, 1),
        'avg_daily_holdings': round(avg_holdings, 1),
        'max_holdings': max_holdings,
        'net_profit_krw': round(net_profit_krw),
        'return_on_avg_capital': round(return_on_avg_cap, 2)
    }

# Generate Targeted Strategy Configurations (focused on High Conviction & Low Holdings)
configs = []

# 1. High-Conviction Oversold
for r_t in [25, 28, 30]:
    for b_t in [0.08, 0.12, 0.18]:
        for s_t in [15, 20, None]:
            for e_r in [60, 65, 70]:
                for sl in [10, 15]:
                    for tp in [15, 20, None]:
                        configs.append({
                            'type': 'oversold',
                            'rsi': r_t,
                            'bb': b_t,
                            'stoch': s_t,
                            'vol': None,
                            'exit_type': 'rsi',
                            'exit_val': e_r,
                            'stop_loss': sl,
                            'take_profit': tp,
                            'cooldown': 10,
                            'name': f"[과매도 반등] RSI<={r_t} & 볼린저<={b_t}" + (f" & 스토<={s_t}" if s_t else ""),
                            'buy_desc': f"RSI <= {r_t}, 볼린저 %b <= {b_t}" + (f", 스토캐스틱 %K <= {s_t}" if s_t else ""),
                            'sell_desc': f"RSI >= {e_r}"
                        })

# 2. Disparity + Bollinger Oversold
for d_t in [90, 92, 94]:
    for b_t in [0.05, 0.1, 0.15]:
        for e_b in [0.85, 0.95]:
            for sl in [10, 15]:
                for tp in [15, 20, None]:
                    configs.append({
                        'type': 'disparity_oversold',
                        'disp': d_t,
                        'bb': b_t,
                        'exit_type': 'bb',
                        'exit_val': e_b,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'cooldown': 10,
                        'name': f"[이격도 과매도] 이격도<={d_t}% & 볼린저<={b_t}",
                        'buy_desc': f"이격도(20일) <= {d_t}%, 볼린저 %b <= {b_t}",
                        'sell_desc': f"볼린저 %b >= {e_b}"
                    })

# 3. Stochastic + RSI Double Bottom
for s_k in [15, 20]:
    for r_t in [28, 32]:
        for b_t in [0.15, 0.25]:
            for e_s in [75, 80]:
                for sl in [10, 15]:
                    for tp in [15, 20, None]:
                        configs.append({
                            'type': 'stoch_rsi_double',
                            'stoch': s_k,
                            'rsi': r_t,
                            'bb': b_t,
                            'exit_type': 'stoch',
                            'exit_val': e_s,
                            'stop_loss': sl,
                            'take_profit': tp,
                            'cooldown': 10,
                            'name': f"[스토캐스틱 바닥돌파] 스토<={s_k} & RSI<={r_t} & 볼린저<={b_t}",
                            'buy_desc': f"스토캐스틱 %K <= {s_k}, RSI <= {r_t}, 볼린저 %b <= {b_t}",
                            'sell_desc': f"스토캐스틱 %K >= {e_s}"
                        })

print(f"Generated {len(configs)} targeted configs. Running batch simulation...")

results = []
for i, cfg in enumerate(configs):
    res = evaluate_single_config(cfg)
    if res:
        results.append(res)

print(f"Completed! Total valid strategy results: {len(results)}")

# Filter strategies by average daily holdings (<= 30 stocks)
manageable = [r for r in results if r['avg_daily_holdings'] <= 30]

# 1. TOP Win-rate
top_win = sorted(manageable, key=lambda x: (x['win_rate'], x['profit_factor']), reverse=True)[:5]
# 2. TOP Return on Capital
top_return = sorted(manageable, key=lambda x: (x['return_on_avg_capital'], x['profit_factor']), reverse=True)[:5]
# 3. TOP Profit Factor
top_pf = sorted(manageable, key=lambda x: (x['profit_factor'], x['win_rate']), reverse=True)[:5]

print("\n" + "="*80)
print("🏆 [TOP 3 승률 극대화형 전략 (평잔 30개 이하 / 높은 승률)]")
print("="*80)
for i, s in enumerate(top_win[:3], 1):
    print(f"\n[{i}] {s['name']}")
    print(f"  - 매수 조건: {s['buy_desc']}")
    print(f"  - 매도 조건: {s['sell_desc']} | 익절선: {s['take_profit']}% | 손절선: -{s['stop_loss']}% | 쿨다운: {s['cooldown']}일")
    print(f"  - 🎯 승률: {s['win_rate']}% | 손익비(PF): {s['profit_factor']} | 평균수익률: {s['avg_return_pct']}% | 총체결: {s['total_trades']}회")
    print(f"  - 💼 평잔 보유: {s['avg_daily_holdings']}개 (최대 {s['max_holdings']}개) | 평균보유일: {s['avg_holding_days']}일 | 💰 평잔대비수익률: {s['return_on_avg_capital']}%")

print("\n" + "="*80)
print("🚀 [TOP 3 평잔 대비 총수익률 극대화형 전략 (자본 효율 최강)]")
print("="*80)
for i, s in enumerate(top_return[:3], 1):
    print(f"\n[{i}] {s['name']}")
    print(f"  - 매수 조건: {s['buy_desc']}")
    print(f"  - 매도 조건: {s['sell_desc']} | 익절선: {s['take_profit']}% | 손절선: -{s['stop_loss']}% | 쿨다운: {s['cooldown']}일")
    print(f"  - 🎯 승률: {s['win_rate']}% | 손익비(PF): {s['profit_factor']} | 평균수익률: {s['avg_return_pct']}% | 총체결: {s['total_trades']}회")
    print(f"  - 💼 평잔 보유: {s['avg_daily_holdings']}개 (최대 {s['max_holdings']}개) | 평균보유일: {s['avg_holding_days']}일 | 💰 평잔대비수익률: {s['return_on_avg_capital']}%")

with open('top_strategies_summary.json', 'w', encoding='utf-8') as f:
    json.dump({'top_win': top_win, 'top_return': top_return, 'top_pf': top_pf}, f, ensure_ascii=False, indent=2)
