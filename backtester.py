"""
Quant Backtesting Simulation Engine
Executes vectorized and trade-by-trade 5-year simulation with dynamic custom strategy rules,
realistic next-day open execution, and detailed equity curve / KPI reports.
"""

import os
import sys
import json
import argparse
import datetime
import pandas as pd
import numpy as np

try:
    from data_loader import load_5y_history_cache
except ImportError:
    from .data_loader import load_5y_history_cache

# Default Built-in Strategy (matches current hardcoded screener logic)
DEFAULT_STRATEGY = {
    "strategy_name": "기존 ADX 반전 & RSI 전략",
    "description": "ADX 25 이상 추세장에서 -DI 하향 돌파 시 매수, RSI 60 이상 또는 +DI 꺾임 시 매도",
    "execution": {
        "entry_timing": "next_open",
        "fee_pct": 0.15,
        "slippage_pct": 0.1,
        "initial_capital": 10000000,
        "stop_loss_pct": None,   # None = disabled
        "take_profit_pct": None  # None = disabled
    },
    "buy_conditions": {
        "operator": "AND",
        "rules": [
            {
                "priority": 1,
                "indicator": "minus_di",
                "condition_type": "cross_below_indicator",
                "target_indicator": "adx",
                "label": "1순위: -DI가 ADX 밑으로 하향 돌파"
            },
            {
                "priority": 2,
                "indicator": "adx",
                "condition_type": "gte_value",
                "value": 25.0,
                "label": "2순위: ADX 25 이상 (추세 강도 확보)"
            },
            {
                "priority": 3,
                "indicator": "rsi",
                "condition_type": "lte_value",
                "value": 50.0,
                "label": "3순위: RSI 50 이하 (저평가 구간)"
            }
        ]
    },
    "sell_conditions": {
        "operator": "OR",
        "rules": [
            {
                "indicator": "rsi",
                "condition_type": "gte_value",
                "value": 60.0,
                "label": "RSI 60 이상 익절"
            },
            {
                "indicator": "plus_di",
                "condition_type": "turn_down",
                "label": "+DI 전날 대비 꺾임 발생"
            }
        ]
    }
}

def evaluate_single_rule(df, rule):
    """Evaluate a single rule on a DataFrame and return a Boolean Series."""
    ind = rule.get("indicator", "")
    cond_type = rule.get("condition_type", "")
    val = rule.get("value", 0.0)
    target_ind = rule.get("target_indicator", "")

    if ind not in df.columns:
        return pd.Series(False, index=df.index)

    series = df[ind]

    # 1. Comparison against fixed value
    if cond_type == "gte_value":
        return series >= float(val)
    elif cond_type == "lte_value":
        return series <= float(val)
    elif cond_type == "gt_value":
        return series > float(val)
    elif cond_type == "lt_value":
        return series < float(val)
    elif cond_type == "eq_value":
        return series == float(val)

    # 2. Comparison against another indicator
    elif cond_type == "cross_below_indicator" and target_ind in df.columns:
        # Prev: Ind > Target, Current: Ind <= Target
        prev_s = series.shift(1)
        prev_t = df[target_ind].shift(1)
        curr_t = df[target_ind]
        return (prev_s > prev_t) & (series <= curr_t)

    elif cond_type == "cross_above_indicator" and target_ind in df.columns:
        # Prev: Ind < Target, Current: Ind >= Target
        prev_s = series.shift(1)
        prev_t = df[target_ind].shift(1)
        curr_t = df[target_ind]
        return (prev_s < prev_t) & (series >= curr_t)

    elif cond_type == "gte_indicator" and target_ind in df.columns:
        return series >= df[target_ind]

    elif cond_type == "lte_indicator" and target_ind in df.columns:
        return series <= df[target_ind]

    # 3. Dynamic trend turns (shift 1 comparison)
    elif cond_type == "turn_down":
        return series < series.shift(1)

    elif cond_type == "turn_up":
        return series > series.shift(1)

    elif cond_type == "increase_pct":
        return (series / (series.shift(1) + 1e-9) - 1.0) * 100 >= float(val)

    elif cond_type == "decrease_pct":
        return (1.0 - series / (series.shift(1) + 1e-9)) * 100 >= float(val)

    return pd.Series(False, index=df.index)

def evaluate_rule_group(df, group_config):
    """Combine rules in a group with AND / OR logical operator."""
    if not group_config:
        return pd.Series(False, index=df.index)

    rules = group_config.get("rules", [])
    if not rules:
        return pd.Series(False, index=df.index)

    op = str(group_config.get("operator", "AND")).upper()
    
    masks = []
    for r in rules:
        m = evaluate_single_rule(df, r)
        masks.append(m)

    if not masks:
        return pd.Series(False, index=df.index)

    res = masks[0]
    for m in masks[1:]:
        if op == "OR":
            res = res | m
        else:
            res = res & m
    return res

def evaluate_strategy_rules(df, rules_groups):
    """
    Evaluate multiple groups of rules (buyRules or sellRules array).
    Groups are combined with OR (any group matches), rules within each group are combined with AND (all rules match).
    """
    if not rules_groups:
        return pd.Series(False, index=df.index)
    
    combined = pd.Series(False, index=df.index)
    for group in rules_groups:
        rules = group.get("rules", [])
        if not rules:
            continue
        group_mask = pd.Series(True, index=df.index)
        for r in rules:
            m = evaluate_single_rule(df, r)
            group_mask = group_mask & m
        combined = combined | group_mask
    return combined

def run_backtest_simulation(history_df=None, strategy=None, start_date=None, end_date=None):
    """
    Run realistic portfolio backtest across 350 components day-by-day.
    Execution: Signal generated on Day t (Close) -> Enter/Exit on Day t+1 (Open).
    """
    if history_df is None:
        history_df = load_5y_history_cache()

    if history_df is None or len(history_df) == 0:
        return {"success": False, "message": "5년치 주가 데이터를 불러올 수 없습니다."}

    if strategy is None:
        strategy = DEFAULT_STRATEGY

    execution = strategy.get("execution", {})
    fee_rate = float(execution.get("fee_pct", strategy.get("fee_pct", 0.15))) / 100.0
    slippage_rate = float(execution.get("slippage_pct", strategy.get("slippage_pct", 0.1))) / 100.0
    total_cost_per_trade = fee_rate + slippage_rate

    raw_sl = strategy.get("stopLoss", strategy.get("stop_loss", execution.get("stop_loss_pct")))
    raw_tp = strategy.get("takeProfit", strategy.get("take_profit", execution.get("take_profit_pct")))
    stop_loss_pct = float(raw_sl) if (raw_sl is not None and str(raw_sl).strip() != "") else None
    take_profit_pct = float(raw_tp) if (raw_tp is not None and str(raw_tp).strip() != "") else None

    cooldown_days = strategy.get("cooldownDays", strategy.get("cooldown_days", execution.get("cooldown_days", 0)))
    if cooldown_days is not None and str(cooldown_days).strip() != "":
        cooldown_days = int(cooldown_days)
    else:
        cooldown_days = 0

    scale_in_drop = strategy.get("scaleInDrop", strategy.get("scale_in_drop"))
    if scale_in_drop is not None and str(scale_in_drop).strip() != "":
        scale_in_drop = float(scale_in_drop)
    else:
        scale_in_drop = None

    scale_in_mult = strategy.get("scaleInMultiplier", strategy.get("scale_in_multiplier"))
    if scale_in_mult is not None and str(scale_in_mult).strip() != "":
        scale_in_mult = float(scale_in_mult)
    else:
        scale_in_mult = 1.0

    priority_indicator = strategy.get("priorityIndicator", strategy.get("priority_indicator", ""))
    priority_order = strategy.get("priorityOrder", strategy.get("priority_order", "DESC"))
    
    max_buy_count = strategy.get("maxBuyCount", strategy.get("max_buy_count"))
    if max_buy_count is not None and str(max_buy_count).strip() != "":
        max_buy_count = int(max_buy_count)
    else:
        max_buy_count = None

    init_capital = float(strategy.get("tradeAmount", strategy.get("trade_amount", execution.get("trade_amount", execution.get("initial_capital", 1000000)))))
    trade_amount = init_capital

    # Ensure Date sorting
    if 'Date' in history_df.columns:
        history_df['Date'] = pd.to_datetime(history_df['Date'])
    
    if start_date:
        history_df = history_df[history_df['Date'] >= pd.to_datetime(start_date)]
    if end_date:
        history_df = history_df[history_df['Date'] <= pd.to_datetime(end_date)]

    unique_tickers = history_df['Ticker'].unique()

    # 1. Evaluate buy/sell masks for each stock and prepare data
    stocks = []
    all_dates_set = set()

    for ticker in unique_tickers:
        stock_df = history_df[history_df['Ticker'] == ticker].sort_values('Date').copy()
        if len(stock_df) < 30:
            continue

        stock_df.reset_index(drop=True, inplace=True)
        name = stock_df['Name'].iloc[0] if 'Name' in stock_df.columns else str(ticker)
        market = stock_df['Market'].iloc[0] if 'Market' in stock_df.columns else "KOSPI200"

        # Generate signals
        if "buyRules" in strategy or "buy_rules" in strategy:
            buy_mask = evaluate_strategy_rules(stock_df, strategy.get("buyRules", strategy.get("buy_rules")))
        else:
            buy_mask = evaluate_rule_group(stock_df, strategy.get("buy_conditions", {}))

        if "sellRules" in strategy or "sell_rules" in strategy:
            sell_mask = evaluate_strategy_rules(stock_df, strategy.get("sellRules", strategy.get("sell_rules")))
        else:
            sell_mask = evaluate_rule_group(stock_df, strategy.get("sell_conditions", {}))

        # Add dates to global timeline
        for d in stock_df['Date']:
            all_dates_set.add(d)

        stocks.append({
            "ticker": ticker,
            "name": name,
            "market": market,
            "df": stock_df,
            "buy_mask": buy_mask,
            "sell_mask": sell_mask
        })

    sorted_dates = sorted(list(all_dates_set))
    date_str_list = [d.strftime("%Y-%m-%d") for d in sorted_dates]

    # Map stock dfs to Date -> row index for O(1) lookup
    for s in stocks:
        s_df = s['df']
        s['date_to_idx'] = dict(zip(s_df['Date'], s_df.index))

    # Helper function to get indicator value from stock row
    def get_indicator_value(row, ind):
        if row is None:
            return 0.0
        ind_lower = ind.lower()
        if ind_lower in ['volume_ratio', 'volumeratio', 'vr']:
            val = row.get('VolumeRatio', row.get('volume_ratio', row.get('vr', row.get('VR', 0.0))))
        elif ind_lower in ['rsi']:
            val = row.get('RSI', row.get('rsi', 50.0))
        elif ind_lower in ['adx']:
            val = row.get('ADX', row.get('adx', 0.0))
        elif ind_lower in ['minus_di', 'minusdi', 'minus_di']:
            val = row.get('Minus_DI', row.get('minus_di', row.get('minusDi', 0.0)))
        elif ind_lower in ['plus_di', 'plusdi', 'plus_di']:
            val = row.get('Plus_DI', row.get('plus_di', row.get('plusDi', 0.0)))
        elif ind_lower in ['b_band_pct', 'bb_pct', 'bb_%b']:
            val = row.get('b_band_pct', row.get('BB_Pct', row.get('BB_%b', 0.5)))
        elif ind_lower in ['close', 'closeprice']:
            val = row.get('종가', row.get('ClosePrice', row.get('close', 0.0)))
        else:
            val = row.get(ind, 0.0)
        try:
            return float(val) if pd.notna(val) else 0.0
        except (ValueError, TypeError):
            return 0.0

    active_positions = {}  # ticker -> pos_info
    last_stop_loss_dates = {}  # ticker -> date_str
    all_trades = []
    daily_exposures = []

    # 2. Day-by-Day Portfolio Simulation
    for day_idx in range(len(sorted_dates) - 1):
        curr_date = sorted_dates[day_idx]
        next_date = sorted_dates[day_idx + 1]
        curr_date_str = curr_date.strftime("%Y-%m-%d")
        next_date_str = next_date.strftime("%Y-%m-%d")

        # A. Evaluate Exits on curr_date close -> exit on next_date open
        for s in stocks:
            ticker = s['ticker']
            pos = active_positions.get(ticker)
            if not pos:
                continue

            curr_idx = s['date_to_idx'].get(curr_date)
            next_idx = s['date_to_idx'].get(next_date)
            if curr_idx is None or next_idx is None:
                continue

            curr_row = s['df'].iloc[curr_idx]
            next_row = s['df'].iloc[next_idx]

            raw_open = next_row['시가']
            if raw_open <= 0:
                continue

            curr_close = curr_row['종가']
            paper_return_pct = ((curr_close - pos['avg_price']) / pos['avg_price']) * 100.0

            is_exit = False
            exit_reason = "매도전략"

            # Check SL/TP
            if stop_loss_pct is not None and paper_return_pct <= -abs(stop_loss_pct):
                is_exit = True
                exit_reason = f"손절 (-{abs(stop_loss_pct):.1f}%)"
                last_stop_loss_dates[ticker] = next_date_str
            elif take_profit_pct is not None and paper_return_pct >= abs(take_profit_pct):
                is_exit = True
                exit_reason = f"익절 (+{abs(take_profit_pct):.1f}%)"
            elif s['sell_mask'].iloc[curr_idx]:
                is_exit = True
                exit_reason = "매도전략"

            if is_exit:
                actual_exit_price = raw_open * (1.0 - total_cost_per_trade)
                ret_pct = ((actual_exit_price - pos['avg_price']) / pos['avg_price']) * 100.0
                net_profit = (actual_exit_price * pos['total_qty']) - pos['total_invested']
                holding_days = (next_date - pos['entry_date_obj']).days

                if pos['has_scale_in']:
                    exit_reason += " (물타기)"

                all_trades.append({
                    "ticker": ticker,
                    "name": s['name'],
                    "market": s['market'],
                    "signal_date": pos['entry_signal_date'],
                    "entry_date": pos['entry_date'],
                    "entry_price": int(round(pos['initial_buy_price'])),
                    "avg_price": int(round(pos['avg_price'])),
                    "has_scale_in": pos['has_scale_in'],
                    "scale_in_date": pos['scale_in_date'],
                    "scale_in_price": int(round(pos['scale_in_price'])),
                    "scale_in_mult": scale_in_mult,
                    "total_invested": int(round(pos['total_invested'])),
                    "exit_date": next_date_str,
                    "exit_price": int(round(actual_exit_price)),
                    "return_pct": round(ret_pct, 2),
                    "net_profit": int(round(net_profit)),
                    "holding_days": max(1, holding_days),
                    "exit_reason": exit_reason,
                    "win": ret_pct > 0
                })
                del active_positions[ticker]
            else:
                # Check scale-in on curr_date close
                if not pos['has_scale_in'] and scale_in_drop is not None and scale_in_drop > 0:
                    ret_vs_initial = ((curr_close - pos['initial_buy_price']) / pos['initial_buy_price']) * 100.0
                    if ret_vs_initial <= -scale_in_drop:
                        pos['has_scale_in'] = True
                        pos['scale_in_date'] = next_date_str
                        pos['scale_in_price'] = raw_open * (1.0 + total_cost_per_trade)
                        add_invested = trade_amount * scale_in_mult
                        add_qty = add_invested / pos['scale_in_price']
                        pos['total_invested'] += add_invested
                        pos['total_qty'] += add_qty
                        pos['avg_price'] = pos['total_invested'] / pos['total_qty']

        # B. Evaluate Entries on curr_date close -> Enter next_date open
        new_buys = []
        for s in stocks:
            ticker = s['ticker']
            if ticker in active_positions:
                continue

            curr_idx = s['date_to_idx'].get(curr_date)
            next_idx = s['date_to_idx'].get(next_date)
            if curr_idx is None or next_idx is None:
                continue

            curr_row = s['df'].iloc[curr_idx]
            next_row = s['df'].iloc[next_idx]

            raw_open = next_row['시가']
            if raw_open <= 0:
                continue

            last_sl_str = last_stop_loss_dates.get(ticker)
            if cooldown_days > 0 and last_sl_str:
                last_sl_dt = pd.to_datetime(last_sl_str)
                if (curr_date - last_sl_dt).days < cooldown_days:
                    continue

            if s['buy_mask'].iloc[curr_idx]:
                new_buys.append({
                    "stock": s,
                    "row": curr_row,
                    "next_row": next_row
                })

        if new_buys:
            if priority_indicator and max_buy_count is not None and len(new_buys) > max_buy_count:
                new_buys.sort(
                    key=lambda item: get_indicator_value(item['row'], priority_indicator),
                    reverse=(priority_order == "DESC")
                )
                new_buys = new_buys[:max_buy_count]

            for item in new_buys:
                s = item['stock']
                ticker = s['ticker']
                raw_open = item['next_row']['시가']
                initial_buy_price = raw_open * (1.0 + total_cost_per_trade)
                active_positions[ticker] = {
                    "ticker": ticker,
                    "entry_signal_date": curr_date_str,
                    "entry_date": next_date_str,
                    "entry_date_obj": next_date,
                    "initial_buy_price": initial_buy_price,
                    "avg_price": initial_buy_price,
                    "has_scale_in": False,
                    "scale_in_date": "",
                    "scale_in_price": 0.0,
                    "total_invested": trade_amount,
                    "total_qty": trade_amount / initial_buy_price
                }

        # Log daily exposure weight sum
        exposure_weight = 0.0
        for pos in active_positions.values():
            if pos['has_scale_in']:
                exposure_weight += (1.0 + scale_in_mult)
            else:
                exposure_weight += 1.0
        daily_exposures.append(exposure_weight)

    # Close remaining open positions at final close price
    if len(sorted_dates) > 0:
        final_date = sorted_dates[-1]
        final_date_str = final_date.strftime("%Y-%m-%d")
        for s in stocks:
            ticker = s['ticker']
            pos = active_positions.get(ticker)
            if not pos:
                continue

            final_idx = s['date_to_idx'].get(final_date)
            if final_idx is None:
                continue

            final_row = s['df'].iloc[final_idx]
            final_close = final_row['종가']

            actual_exit_price = final_close * (1.0 - total_cost_per_trade)
            ret_pct = ((actual_exit_price - pos['avg_price']) / pos['avg_price']) * 100.0
            net_profit = (actual_exit_price * pos['total_qty']) - pos['total_invested']
            holding_days = (final_date - pos['entry_date_obj']).days

            exit_reason = "백테스트종료"
            if pos['has_scale_in']:
                exit_reason += " (물타기)"

            all_trades.append({
                "ticker": ticker,
                "name": s['name'],
                "market": s['market'],
                "signal_date": pos['entry_signal_date'],
                "entry_date": pos['entry_date'],
                "entry_price": int(round(pos['initial_buy_price'])),
                "avg_price": int(round(pos['avg_price'])),
                "has_scale_in": pos['has_scale_in'],
                "scale_in_date": pos['scale_in_date'],
                "scale_in_price": int(round(pos['scale_in_price'])),
                "scale_in_mult": scale_in_mult,
                "total_invested": int(round(pos['total_invested'])),
                "exit_date": final_date_str,
                "exit_price": int(round(actual_exit_price)),
                "return_pct": round(ret_pct, 2),
                "net_profit": int(round(net_profit)),
                "holding_days": max(1, holding_days),
                "exit_reason": exit_reason,
                "win": ret_pct > 0
            })

    # 3. Calculate metrics and final reports
    if not all_trades:
        return {
            "success": True,
            "strategy_name": strategy.get("strategy_name", "커스텀 전략"),
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "mdd_pct": 0.0,
            "avg_trade_return": 0.0,
            "trades": [],
            "equity_curve": [],
            "message": "해당 조건으로 체결된 거래 내역이 없습니다."
        }

    trades_df = pd.DataFrame(all_trades).sort_values("entry_date").reset_index(drop=True)
    total_trades = len(trades_df)
    win_trades = len(trades_df[trades_df['win'] == True])
    loss_trades = total_trades - win_trades
    win_rate = (win_trades / total_trades) * 100.0

    avg_exposure_weight = sum(daily_exposures) / len(daily_exposures) if daily_exposures else 0.0
    average_balance = max(trade_amount, avg_exposure_weight * trade_amount)
    total_net_profit = sum(t['net_profit'] for t in all_trades)
    total_return_pct = (total_net_profit / average_balance) * 100.0

    gross_profit = sum(t['net_profit'] for t in all_trades if t['net_profit'] > 0)
    gross_loss = abs(sum(t['net_profit'] for t in all_trades if t['net_profit'] < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)

    # Construct equity_curve
    nav = 100.0
    peak_nav = 100.0
    max_nav_dd = 0.0
    equity_curve = []
    
    price_map = {}
    for s in stocks:
        price_map[s['ticker']] = dict(zip(s['df']['Date'].dt.strftime("%Y-%m-%d"), s['df']['종가']))
    
    for idx, d_str in enumerate(date_str_list):
        if idx == 0:
            equity_curve.append({
                "date": d_str,
                "capital": int(round(nav * (average_balance / 100.0))),
                "return_pct": 0.0,
                "drawdown": 0.0
            })
            continue
        
        prev_d_str = date_str_list[idx - 1]
        stock_rets = []
        
        for t in all_trades:
            ticker = t['ticker']
            e_date = t['entry_date']
            x_date = t['exit_date']
            
            if e_date == d_str and x_date == d_str:
                stock_rets.append((t['exit_price'] - t['entry_price']) / t['entry_price'])
            elif e_date == d_str:
                close_p = price_map.get(ticker, {}).get(d_str, t['entry_price'])
                stock_rets.append((close_p - t['entry_price']) / t['entry_price'])
            elif e_date < d_str and x_date > d_str:
                p_close = price_map.get(ticker, {}).get(prev_d_str, t['entry_price'])
                c_close = price_map.get(ticker, {}).get(d_str, p_close)
                if p_close > 0:
                    stock_rets.append((c_close - p_close) / p_close)
            elif x_date == d_str:
                p_close = price_map.get(ticker, {}).get(prev_d_str, t['entry_price'])
                if p_close > 0:
                    stock_rets.append((t['exit_price'] - p_close) / p_close)
        
        day_ret = sum(stock_rets) / len(stock_rets) if stock_rets else 0.0
        nav = nav * (1.0 + day_ret)
        if nav > peak_nav:
            peak_nav = nav
        dd = ((peak_nav - nav) / peak_nav) * 100.0 if peak_nav > 0 else 0.0
        if dd > max_nav_dd:
            max_nav_dd = dd
            
        equity_curve.append({
            "date": d_str,
            "capital": int(round(nav * (average_balance / 100.0))),
            "return_pct": round(nav - 100.0, 2),
            "drawdown": round(dd, 2)
        })

    # Calculate CAGR
    start_dt = sorted_dates[0]
    end_dt = sorted_dates[-1]
    years = max(0.5, (end_dt - start_dt).days / 365.25)
    cagr_pct = (((nav / 100.0) ** (1.0 / years)) - 1.0) * 100.0 if nav > 0 else -100.0

    # Sample down equity curve for fast JSON payload (1 point per 5 trading days + endpoints)
    sampled_curve = [equity_curve[0]]
    for i in range(1, len(equity_curve) - 1, 5):
        sampled_curve.append(equity_curve[i])
    sampled_curve.append(equity_curve[-1])

    return {
        "success": True,
        "strategy_name": strategy.get("strategy_name", "커스텀 전략"),
        "total_trades": total_trades,
        "win_trades": win_trades,
        "loss_trades": loss_trades,
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr_pct, 2),
        "mdd_pct": round(max_nav_dd, 2),
        "avg_trade_return": round(trades_df['return_pct'].mean(), 2),
        "avg_holding_days": round(trades_df['holding_days'].mean(), 1),
        "initial_capital": int(round(average_balance)),
        "final_capital": int(round(average_balance + total_net_profit)),
        "equity_curve": sampled_curve,
        "recent_trades": all_trades[-100:]  # Latest 100 trades for clean table rendering
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run 5-year Quant Backtest")
    parser.add_argument("--json", type=str, help="Strategy JSON string or file path")
    args = parser.parse_args()

    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    strat = DEFAULT_STRATEGY
    if args.json:
        if os.path.exists(args.json):
            with open(args.json, "r", encoding="utf-8") as f:
                strat = json.load(f)
        else:
            strat = json.loads(args.json)

    print(f"[INFO] Running 5-year backtest for strategy: {strat.get('strategy_name')}...")
    res = run_backtest_simulation(strategy=strat)
    print(f"\n=======================================================")
    print(f"📊 [백테스트 5년 종합 성과 리포트] {res.get('strategy_name')}")
    print(f"=======================================================")
    print(f" • 총 누적 수익률: {res.get('total_return_pct')}%")
    print(f" • 연평균 수익률 (CAGR): {res.get('cagr_pct')}%")
    print(f" • 매매 승률 (Win Rate): {res.get('win_rate')}% ({res.get('win_trades')}승 / {res.get('loss_trades')}패)")
    print(f" • 손익비 (Profit Factor): {res.get('profit_factor')}")
    print(f" • 최대 낙폭 (MDD): -{res.get('mdd_pct')}%")
    print(f" • 총 체결 횟수: {res.get('total_trades')}회 (평균 보유 {res.get('avg_holding_days')}일)")
    print(f" • 최종 자산: {res.get('final_capital'):,} 원 (초기 {res.get('initial_capital'):,} 원)")
    print(f"=======================================================\n")
