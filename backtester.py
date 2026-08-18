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

def run_backtest_simulation(history_df=None, strategy=None, start_date=None, end_date=None):
    """
    Run realistic portfolio backtest across 350 components.
    Execution: Signal generated on Day t (Close) -> Enter/Exit on Day t+1 (Open).
    """
    if history_df is None:
        history_df = load_5y_history_cache()

    if history_df is None or len(history_df) == 0:
        return {"success": False, "message": "5년치 주가 데이터를 불러올 수 없습니다."}

    if strategy is None:
        strategy = DEFAULT_STRATEGY

    execution = strategy.get("execution", {})
    fee_rate = float(execution.get("fee_pct", 0.15)) / 100.0
    slippage_rate = float(execution.get("slippage_pct", 0.1)) / 100.0
    total_cost_per_trade = fee_rate + slippage_rate  # applied on entry and exit
    
    raw_sl = execution.get("stop_loss_pct")
    raw_tp = execution.get("take_profit_pct")
    stop_loss_pct = float(raw_sl) if (raw_sl is not None and str(raw_sl).strip() != "") else None
    take_profit_pct = float(raw_tp) if (raw_tp is not None and str(raw_tp).strip() != "") else None

    init_capital = float(execution.get("initial_capital", 10000000))
    buy_config = strategy.get("buy_conditions", {})
    sell_config = strategy.get("sell_conditions", {})

    # Ensure Date sorting
    if 'Date' in history_df.columns:
        history_df['Date'] = pd.to_datetime(history_df['Date'])
    
    if start_date:
        history_df = history_df[history_df['Date'] >= pd.to_datetime(start_date)]
    if end_date:
        history_df = history_df[history_df['Date'] <= pd.to_datetime(end_date)]

    all_trades = []
    unique_tickers = history_df['Ticker'].unique()

    for ticker in unique_tickers:
        stock_df = history_df[history_df['Ticker'] == ticker].sort_values('Date').copy()
        if len(stock_df) < 30:
            continue

        stock_df.reset_index(drop=True, inplace=True)
        name = stock_df['Name'].iloc[0] if 'Name' in stock_df.columns else str(ticker)
        market = stock_df['Market'].iloc[0] if 'Market' in stock_df.columns else "KOSPI200"

        # Generate signals
        buy_mask = evaluate_rule_group(stock_df, buy_config)
        sell_mask = evaluate_rule_group(stock_df, sell_config)

        in_position = False
        entry_idx = 0
        entry_price = 0.0
        entry_signal_date = None
        entry_exec_date = None

        n_candles = len(stock_df)
        for i in range(n_candles - 1):  # iterate up to n-2 so i+1 (next day open) is valid
            curr_row = stock_df.iloc[i]
            next_row = stock_df.iloc[i + 1]

            if not in_position:
                # Check Buy Signal on Day i -> Buy on Day i+1 Open
                if buy_mask.iloc[i]:
                    raw_open = next_row['시가']
                    if raw_open > 0:
                        in_position = True
                        entry_idx = i + 1
                        entry_price = raw_open * (1.0 + total_cost_per_trade)
                        entry_signal_date = curr_row['Date']
                        entry_exec_date = next_row['Date']
            else:
                # We are in position. Check Exit conditions on Day i:
                curr_close = curr_row['종가']
                paper_return_pct = ((curr_close - entry_price) / entry_price) * 100.0

                is_exit = False
                exit_reason = "매도신호"

                # 1. Check Stop Loss trigger on Day i
                if stop_loss_pct is not None and paper_return_pct <= -abs(stop_loss_pct):
                    is_exit = True
                    exit_reason = f"손절 (-{abs(stop_loss_pct):.1f}%)"

                # 2. Check Take Profit trigger on Day i
                elif take_profit_pct is not None and paper_return_pct >= abs(take_profit_pct):
                    is_exit = True
                    exit_reason = f"익절 (+{abs(take_profit_pct):.1f}%)"

                # 3. Check Technical Sell Signal on Day i
                elif sell_mask.iloc[i]:
                    is_exit = True
                    exit_reason = "매도전략"

                if is_exit:
                    exit_exec_date = next_row['Date']
                    raw_exit_open = next_row['시가']
                    actual_exit_price = raw_exit_open * (1.0 - total_cost_per_trade)
                    ret_pct = ((actual_exit_price - entry_price) / entry_price) * 100.0
                    holding_days = (exit_exec_date - entry_exec_date).days

                    all_trades.append({
                        "ticker": ticker,
                        "name": name,
                        "market": market,
                        "signal_date": entry_signal_date.strftime("%Y-%m-%d"),
                        "entry_date": entry_exec_date.strftime("%Y-%m-%d"),
                        "entry_price": int(round(entry_price)),
                        "exit_date": exit_exec_date.strftime("%Y-%m-%d"),
                        "exit_price": int(round(actual_exit_price)),
                        "return_pct": round(ret_pct, 2),
                        "holding_days": max(1, holding_days),
                        "exit_reason": exit_reason,
                        "win": ret_pct > 0
                    })
                    in_position = False

    # Process overall portfolio analytics
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
            "message": "해당 조건으로 체결된 거래 내역이 없습니다. (조건 완화 권장)"
        }

    trades_df = pd.DataFrame(all_trades).sort_values("entry_date").reset_index(drop=True)
    
    total_trades = len(trades_df)
    win_trades = len(trades_df[trades_df['win'] == True])
    loss_trades = total_trades - win_trades
    win_rate = (win_trades / total_trades) * 100.0 if total_trades > 0 else 0.0

    gross_profit = trades_df[trades_df['return_pct'] > 0]['return_pct'].sum()
    gross_loss = abs(trades_df[trades_df['return_pct'] < 0]['return_pct'].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)

    # Build Daily Portfolio Equity Curve
    all_dates = sorted(history_df['Date'].dt.strftime("%Y-%m-%d").unique())
    capital = init_capital
    peak_capital = init_capital
    max_drawdown = 0.0
    equity_curve = []

    # Map daily returns proportionally
    trades_by_exit_date = {}
    for t in all_trades:
        d = t['exit_date']
        trades_by_exit_date.setdefault(d, []).append(t['return_pct'])

    # Assume max 10 concurrent portfolio positions (10% allocation per trade)
    allocation_fraction = 0.10

    for d in all_dates:
        if d in trades_by_exit_date:
            rets = trades_by_exit_date[d]
            for r in rets:
                trade_pnl = (capital * allocation_fraction) * (r / 100.0)
                capital += trade_pnl
        
        if capital > peak_capital:
            peak_capital = capital
        dd = ((peak_capital - capital) / peak_capital) * 100.0
        if dd > max_drawdown:
            max_drawdown = dd

        equity_curve.append({
            "date": d,
            "capital": int(round(capital)),
            "return_pct": round(((capital - init_capital) / init_capital) * 100.0, 2),
            "drawdown": round(dd, 2)
        })

    final_capital = equity_curve[-1]['capital']
    total_return_pct = ((final_capital - init_capital) / init_capital) * 100.0

    # Calculate CAGR
    start_dt = pd.to_datetime(all_dates[0])
    end_dt = pd.to_datetime(all_dates[-1])
    years = max(0.5, (end_dt - start_dt).days / 365.25)
    cagr_pct = (((final_capital / init_capital) ** (1.0 / years)) - 1.0) * 100.0 if final_capital > 0 else -100.0

    # Sample down equity curve for fast JSON payload (1 point per 5 trading days + endpoints)
    sampled_curve = [equity_curve[0]]
    for i in range(1, len(equity_curve) - 1, 3):
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
        "mdd_pct": round(max_drawdown, 2),
        "avg_trade_return": round(trades_df['return_pct'].mean(), 2),
        "avg_holding_days": round(trades_df['holding_days'].mean(), 1),
        "initial_capital": int(init_capital),
        "final_capital": int(final_capital),
        "equity_curve": sampled_curve,
        "recent_trades": all_trades[-100:]  # Latest 100 trades for clean table rendering
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run 5-year Quant Backtest")
    parser.add_argument("--json", type=str, help="Strategy JSON string or file path")
    args = parser.parse_args()

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
