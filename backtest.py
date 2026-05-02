# ============================================================
#  backtest.py  —  Renko strategy backtester
#
#  Usage:
#    python backtest.py --csv historical_data\BTC-USD_yfinance_5min_59d.csv --bricktype percent --brick 0.1 --steplinetype points --stepline 300 --trail 2
#    python backtest.py --csv historical_data\ETH-USD_yfinance_5min_59d.csv --bricktype percent --brick 0.1 --steplinetype percent --stepline 0.8 --trail 2
#
#  Output:
#    - Full results with win rate, R:R, drawdown
#    - All trades with entry/exit datetime
#    - _trades.csv     — full log, open in Excel
#    - _tradingview.csv — import to TradingView (right-click chart -> Import trades)
# ============================================================

import argparse
import csv
import sys
import os
from datetime    import datetime
from renko_engine import RenkoEngine, Signal, Direction


def load_csv(csv_file: str):
    rows = []
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        close_col = None
        for c in reader.fieldnames:
            if c.lower() in ('close', 'ltp', 'price'):
                close_col = c; break
        if not close_col:
            print(f"ERROR: CSV needs a 'close' column. Found: {reader.fieldnames}")
            sys.exit(1)

        dt_col = None
        for c in reader.fieldnames:
            if c.lower() in ('datetime', 'date', 'time', 'timestamp'):
                dt_col = c; break

        for row in reader:
            try:
                price = float(row[close_col])
                dt    = None
                if dt_col:
                    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
                                '%Y-%m-%d'):
                        try:
                            dt = datetime.strptime(row[dt_col], fmt); break
                        except ValueError:
                            pass
                rows.append((dt, price))
            except (ValueError, KeyError):
                continue
    return rows


def run_backtest(csv_file, brick_type="percent", brick_value=0.1,
                 stepline_type="points", stepline_value=300.0,
                 trail_bricks=2, min_bricks=2, chop_cd=3):

    import logging; logging.disable(logging.CRITICAL)

    engine = RenkoEngine(
        brick_type=brick_type, brick_value=brick_value,
        stepline_type=stepline_type, stepline_value=stepline_value,
        min_bricks=min_bricks, chop_cooldown=chop_cd,
    )

    rows     = load_csv(csv_file)
    trades   = []
    position = None
    equity   = 0.0
    peak     = 0.0
    max_dd   = 0.0

    engine.seed(rows[0][1])

    for i, (dt, price) in enumerate(rows[1:], 1):
        signal = engine.update(price)

        if position:
            new_sl = engine.trail_sl(position['entry'],
                                     position['direction'], trail_bricks)
            if position['direction'] == Direction.UP:
                if new_sl > position['sl']: position['sl'] = new_sl
                if price <= position['sl']:
                    pnl = position['sl'] - position['entry']
                    equity += pnl; peak = max(peak,equity)
                    max_dd  = min(max_dd, equity-peak)
                    trades.append({'num':len(trades)+1,'type':'SL',
                        'dir':'LONG','entry_dt':position['dt'],'exit_dt':dt,
                        'entry':position['entry'],'exit':position['sl'],
                        'pnl':pnl,'equity':equity}); position=None
            elif position['direction'] == Direction.DOWN:
                if new_sl < position['sl']: position['sl'] = new_sl
                if price >= position['sl']:
                    pnl = position['entry'] - position['sl']
                    equity += pnl; peak = max(peak,equity)
                    max_dd  = min(max_dd, equity-peak)
                    trades.append({'num':len(trades)+1,'type':'SL',
                        'dir':'SHORT','entry_dt':position['dt'],'exit_dt':dt,
                        'entry':position['entry'],'exit':position['sl'],
                        'pnl':pnl,'equity':equity}); position=None

        if signal in (Signal.BUY, Signal.SELL):
            if position:
                d   = position['direction']
                pnl = (price-position['entry']) if d==Direction.UP \
                       else (position['entry']-price)
                equity += pnl; peak = max(peak,equity)
                max_dd  = min(max_dd, equity-peak)
                trades.append({'num':len(trades)+1,'type':'REV',
                    'dir':'LONG' if d==Direction.UP else 'SHORT',
                    'entry_dt':position['dt'],'exit_dt':dt,
                    'entry':position['entry'],'exit':price,
                    'pnl':pnl,'equity':equity}); position=None

            direction = Direction.UP if signal==Signal.BUY else Direction.DOWN
            sl = engine.trail_sl(price, direction, trail_bricks)
            position = {'direction':direction,'entry':price,'sl':sl,
                        'bar':i,'dt':dt}

    if position:
        dt_last, p_last = rows[-1]
        d   = position['direction']
        pnl = (p_last-position['entry']) if d==Direction.UP \
               else (position['entry']-p_last)
        equity += pnl
        trades.append({'num':len(trades)+1,'type':'END',
            'dir':'LONG' if d==Direction.UP else 'SHORT',
            'entry_dt':position['dt'],'exit_dt':dt_last,
            'entry':position['entry'],'exit':p_last,
            'pnl':pnl,'equity':equity})

    # ── Stats ─────────────────────────────────────────────────
    wins    = [t for t in trades if t['pnl']>0]
    losses  = [t for t in trades if t['pnl']<=0]
    win_pct = len(wins)/len(trades)*100 if trades else 0
    avg_win = sum(t['pnl'] for t in wins)/len(wins)     if wins   else 0
    avg_los = sum(t['pnl'] for t in losses)/len(losses) if losses else 0
    rr      = abs(avg_win/avg_los) if avg_los else 0
    best    = max((t['pnl'] for t in trades), default=0)
    worst   = min((t['pnl'] for t in trades), default=0)

    print("\n" + "="*58)
    print(f"  BACKTEST RESULTS")
    print(f"  Brick  : {brick_value} {brick_type}  "
          f"| Stepline: {stepline_value} {stepline_type}")
    print(f"  Trail  : {trail_bricks} bricks  "
          f"| MinBricks: {min_bricks}  | Chop: {chop_cd}")
    print(f"  CSV    : {os.path.basename(csv_file)}")
    print("="*58)
    print(f"  Bars processed  : {len(rows)}")
    print(f"  Total trades    : {len(trades)}")
    print(f"  Win rate        : {win_pct:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Avg win         : {avg_win:+.4f} pts")
    print(f"  Avg loss        : {avg_los:+.4f} pts")
    print(f"  Risk:Reward     : {rr:.2f} : 1")
    print(f"  Best trade      : {best:+.4f} pts")
    print(f"  Worst trade     : {worst:+.4f} pts")
    print(f"  Max drawdown    : {max_dd:+.4f} pts")
    print(f"  Net equity      : {equity:+.4f} pts")
    print("="*58)

    print(f"\n  ALL TRADES ({len(trades)}):")
    print(f"  {'#':>3}  {'Dir':5}  {'Type':3}  "
          f"{'Entry time':<18}  {'Exit time':<18}  "
          f"{'Entry':>10}  {'Exit':>10}  {'PnL':>10}")
    print("  " + "-"*90)
    for t in trades:
        edt = t['entry_dt'].strftime('%Y-%m-%d %H:%M') if t['entry_dt'] else "?"
        xdt = t['exit_dt'].strftime('%Y-%m-%d %H:%M')  if t['exit_dt']  else "?"
        print(f"  {t['num']:>3}  {t['dir']:5}  {t['type']:3}  "
              f"{edt:<18}  {xdt:<18}  "
              f"{t['entry']:>10.2f}  {t['exit']:>10.2f}  "
              f"{t['pnl']:>+10.4f}")

    # ── Save trade logs ───────────────────────────────────────
    base     = csv_file.replace('.csv','')
    log_path = base + '_trades.csv'
    tv_path  = base + '_tradingview.csv'

    with open(log_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['trade_num','direction','type','entry_datetime',
                    'exit_datetime','entry_price','exit_price',
                    'pnl_pts','equity_pts'])
        for t in trades:
            edt = t['entry_dt'].strftime('%Y-%m-%d %H:%M:%S') if t['entry_dt'] else ''
            xdt = t['exit_dt'].strftime('%Y-%m-%d %H:%M:%S')  if t['exit_dt']  else ''
            w.writerow([t['num'],t['dir'],t['type'],edt,xdt,
                        f"{t['entry']:.4f}",f"{t['exit']:.4f}",
                        f"{t['pnl']:.4f}",f"{t['equity']:.4f}"])

    # TradingView format
    with open(tv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Trade #','Signal','Date','Price','Date','Price','Profit'])
        for t in trades:
            edt = t['entry_dt'].strftime('%Y-%m-%dT%H:%M:%SZ') if t['entry_dt'] else ''
            xdt = t['exit_dt'].strftime('%Y-%m-%dT%H:%M:%SZ')  if t['exit_dt']  else ''
            w.writerow([t['num'],
                        'Long' if t['dir']=='LONG' else 'Short',
                        edt, f"{t['entry']:.4f}",
                        xdt, f"{t['exit']:.4f}",
                        f"{t['pnl']:.4f}"])

    print(f"\n  Trade log      -> {os.path.basename(log_path)}")
    print(f"  TradingView CSV -> {os.path.basename(tv_path)}")
    print(f"\n  To see trades on TradingView:")
    print(f"    1. Open BTC/ETH 5-min chart")
    print(f"    2. Right-click chart -> Import trades")
    print(f"    3. Select: {os.path.basename(tv_path)}")
    print()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Renko backtest")
    p.add_argument("--csv",          required=True)
    p.add_argument("--brick",        type=float, default=0.1)
    p.add_argument("--bricktype",    default="percent")
    p.add_argument("--stepline",     type=float, default=300)
    p.add_argument("--steplinetype", default="points")
    p.add_argument("--trail",        type=int,   default=2)
    p.add_argument("--minbricks",    type=int,   default=2)
    p.add_argument("--chop",         type=int,   default=3)
    args = p.parse_args()

    run_backtest(
        csv_file       = args.csv,
        brick_type     = args.bricktype,
        brick_value    = args.brick,
        stepline_type  = args.steplinetype,
        stepline_value = args.stepline,
        trail_bricks   = args.trail,
        min_bricks     = args.minbricks,
        chop_cd        = args.chop,
    )
