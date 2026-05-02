# Renko Bot — Runbook

Delta Exchange India · Renko + Stepline trailing SL strategy

---

## Table of Contents

1. [Strategy Overview](#1-strategy-overview)
2. [Backtest Results](#2-backtest-results)
3. [Minimum Order Sizes & Capital](#3-minimum-order-sizes--capital)
4. [VPS Setup (Ubuntu)](#4-vps-setup-ubuntu)
5. [Live Configuration Checklist](#5-live-configuration-checklist)
6. [Running the Bot](#6-running-the-bot)
7. [Monitoring](#7-monitoring)
8. [Risk Settings Guide](#8-risk-settings-guide)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Strategy Overview

| Component | What it does |
|---|---|
| **Renko bricks** | Filter noise — price must move a full brick to register |
| **Stepline** | Tracks trend direction; flips when price reverses by `stepline_value` |
| **Chop filter** | Blocks signals unless at least `chop_cooldown` bricks formed since last flip |
| **Min bricks** | Requires `min_bricks` consecutive bricks in new direction before entering |
| **Trailing SL** | SL sits `trail_bricks` × brick_size behind the stepline high/low |

Signal flow: `price tick → build bricks → update stepline → BUY/SELL/NONE → place order + SL`

---

## 2. Backtest Results

Data source: yfinance · Period: ~59 days (Feb 12 – Apr 5 2026)

### BTC — 5 min · Brick 0.1% · Stepline 300 pts · Trail 2 bricks

| Metric | Value |
|---|---|
| Total trades | 93 |
| Win rate | 50.5% (47W / 46L) |
| Avg win | ~+215 pts |
| Avg loss | ~-130 pts |
| Risk : Reward | **2.8 : 1** |
| Best trade | +2,009 pts (short, Feb 23) |
| Worst trade | -136 pts |
| Net equity | +10,158 pts |
| **Net USD @ 0.001 BTC** | **~$10.16** |
| Max drawdown | ~-1,300 pts (~$1.30 at min size) |

**Trade frequency**: ~1.6 trades/day on average, clustered in active periods.
**Observation**: BTC traded in a narrow $66k–$69k range for most of the period. A trending market would significantly improve results. The 2.8:1 R:R means the strategy can be profitable even below 50% WR.

**Choppy period alert**: Feb 19–20 saw 10 consecutive losses in a short chop window. The chop filter reduces but doesn't eliminate this. The `max_trades_per_day = 6` cap limits damage during such periods.

---

### ETH — 5 min · Brick 0.1% · Stepline 0.8% · Trail 2 bricks

| Metric | Value |
|---|---|
| Total trades | 28 |
| Win rate | 42.9% (12W / 16L) |
| Avg win | ~+21.7 pts |
| Avg loss | ~-3.3 pts |
| Risk : Reward | **6.62 : 1** |
| Best trade | +87.6 pts (long, Mar 2) |
| Worst trade | -3.9 pts |
| Net equity | +208 pts |
| **Net USD @ 0.01 ETH** | **~$2.08** |

**Observation**: Very high R:R but very low trade frequency — less than 1 trade every 2 days. Losses are tiny and consistent (~$0.04 each at min size). This is a patience strategy; a few big trending moves carry all the profit. The high R:R makes it attractive but the 59-day sample of only 28 trades is marginal for confidence.

---

### SOL — 2 min · Brick 0.2% · Stepline 2.0% · Trail 2 bricks

| Metric | Value |
|---|---|
| Total trades | **8** |
| Win rate | 37.5% (3W / 5L) |
| Net equity | +3.56 pts |
| **Net USD @ 0.1 SOL** | **~$0.36** |

> **WARNING**: 8 trades is not statistically meaningful. Do NOT trade SOL live based on this backtest alone. Run on a longer dataset before risking capital.

---

### Key Takeaway

**BTC is the most reliable signal.** 93 trades over 59 days gives reasonable statistical confidence. ETH has an attractive R:R profile but needs more data. SOL should not be live-traded yet.

---

## 3. Minimum Order Sizes & Capital

### Delta Exchange India minimums (confirmed testnet)

| Symbol | Min size | Position value (approx) | Max loss/trade (at min size) |
|---|---|---|---|
| BTC | 0.001 BTC | ~$70 | ~$0.14 |
| ETH | 0.01 ETH | ~$22 | ~$0.04 |
| SOL | 0.1 SOL | ~$9 | ~$0.03 |

These are already set to minimum in `config.py`. Do not go below these values.

### Suggested live testing capital (testnet → live)

Start with these values for live testing:

| Phase | BTC size | Recommended margin | Notes |
|---|---|---|---|
| Paper / testnet | 0.001 | — | Verify signals, no real risk |
| Live micro | 0.001 | $200–300 | Real fills, minimal exposure |
| Live small | 0.005 | $500–1000 | Scale after 2 weeks of clean runs |

**Never risk more than you can afford to lose entirely.** Crypto futures are leveraged instruments.

---

## 4. VPS Setup (Ubuntu)

Tested on Ubuntu 22.04 LTS. Any Debian-based VPS works.

### 4.1 Provision

Minimum specs: **1 vCPU, 1 GB RAM, 10 GB disk**.  
Recommended providers: DigitalOcean, Vultr, Hetzner (~$5–6/month).

### 4.2 Install Python

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git
python3 --version   # should be 3.10+
```

### 4.3 Clone and install

```bash
cd ~
git clone https://github.com/jignesh1707/crypto-future-bot.git
cd crypto-future-bot

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4.4 Set credentials

```bash
cp .env.example .env
nano .env
```

Fill in your live (or testnet) keys:

```
DELTA_API_KEY=your_actual_key
DELTA_API_SECRET=your_actual_secret
```

### 4.5 Test connection

```bash
source venv/bin/activate
python test_connection.py
```

All 4 steps should show `OK` before proceeding.

### 4.6 Create systemd service

This ensures the bot auto-restarts on crash and starts on reboot.

```bash
sudo nano /etc/systemd/system/renkobot.service
```

Paste:

```ini
[Unit]
Description=Renko Delta Exchange Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/crypto-future-bot
ExecStart=/home/ubuntu/crypto-future-bot/venv/bin/python bot.py
Restart=on-failure
RestartSec=30
StandardOutput=append:/home/ubuntu/crypto-future-bot/renko_bot.log
StandardError=append:/home/ubuntu/crypto-future-bot/renko_bot.log

[Install]
WantedBy=multi-user.target
```

> Change `ubuntu` to your VPS username if different. Change `WorkingDirectory` and `ExecStart` paths to match your clone location.

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable renkobot
sudo systemctl start renkobot
sudo systemctl status renkobot
```

---

## 5. Live Configuration Checklist

Before switching from testnet to live, tick every box:

- [ ] Run `test_connection.py` → all 4 steps OK
- [ ] Testnet ran cleanly for at least 48 hours with no crashes
- [ ] Set `DELTA_TESTNET = False` in `config.py`
- [ ] Set `INSTRUMENT` to your chosen symbol (`"BTC"` recommended first)
- [ ] Confirm `delta_size` is at minimum (0.001 for BTC)
- [ ] Confirm `max_daily_loss` is set (default $50 for BTC)
- [ ] Confirm `max_trades_per_day` is set (default 6)
- [ ] Verify your Delta Exchange account has sufficient margin
- [ ] Check Delta Exchange India API key has **trade** permissions enabled
- [ ] Ensure VPS systemd service is running and auto-restart is confirmed

---

## 6. Running the Bot

### Locally (Windows / Mac)

```bash
# activate venv first
python bot.py
```

### On VPS (systemd)

```bash
sudo systemctl start renkobot     # start
sudo systemctl stop renkobot      # graceful stop (closes open position)
sudo systemctl restart renkobot   # restart
sudo systemctl status renkobot    # check status
```

**Stopping cleanly**: `systemctl stop` sends SIGTERM, which the bot catches — it closes any open position before exiting. Do not use `kill -9` as that bypasses cleanup.

### Backtesting

```bash
# BTC
python backtest.py --csv historical_data/BTC-USD_yfinance_5min_59d.csv \
  --bricktype percent --brick 0.1 --steplinetype points --stepline 300 --trail 2

# ETH
python backtest.py --csv historical_data/ETH-USD_yfinance_5min_59d.csv \
  --bricktype percent --brick 0.1 --steplinetype percent --stepline 0.8 --trail 2
```

### Fetch more historical data (Delta Exchange)

Sub-hourly data is exchange-cache limited (~60–90 days regardless of source).
Use longer timeframes to get more depth:

```bash
# 5-min — max ~90 days
python data_fetcher.py --source delta --instrument BTC --interval 5min  --days 90

# 1-hour — ~1–2 years, good for strategy validation
python data_fetcher.py --source delta --instrument BTC --interval 60min --days 730

# 4-hour — ~2–3 years
python data_fetcher.py --source delta --instrument BTC --interval 4h    --days 1095

# Daily — ~4–5 years (since Delta launched 2019)
python data_fetcher.py --source delta --instrument BTC --interval 1d    --days 1825
```

Then backtest with adjusted brick sizes for each timeframe:

```bash
# 1h data — brick 0.4%
python backtest.py --csv historical_data/BTC_delta_60min_730d.csv \
  --bricktype percent --brick 0.4 --steplinetype points --stepline 300 --trail 2

# 4h data — brick 0.7%
python backtest.py --csv historical_data/BTC_delta_4h_1095d.csv \
  --bricktype percent --brick 0.7 --steplinetype points --stepline 300 --trail 2
```

> Brick sizes for 1h/4h are starting points — re-optimise using the backtest results.

### Refresh yfinance 5-min data

```bash
python data_fetcher.py --source yfinance --instrument BTC-USD --interval 5min --days 59
python data_fetcher.py --source yfinance --instrument ETH-USD --interval 5min --days 59
```

---

## 7. Monitoring

### Watch live log

```bash
tail -f renko_bot.log
```

### Key log lines to watch

| Log line | Meaning |
|---|---|
| `LTP=... FLAT` | Bot is polling, no position |
| `STEPLINE FLIP ... signal=BUY/SELL` | Signal generated |
| `OPEN UP/DOWN @ ...` | Order placed |
| `Trail SL ... -> ...` | SL moved up/trailing |
| `SL hit ltp=...` | Position closed by SL |
| `Daily loss limit hit` | Bot stopped for the day |
| `New trading day` | Midnight reset, counter cleared |
| `Emergency close executed` | SL placement failed, entry closed |
| `MANUAL INTERVENTION REQUIRED` | Emergency close also failed — check exchange immediately |

### Check if service is alive

```bash
sudo systemctl is-active renkobot
```

### Quick health check (shows last 20 log lines)

```bash
tail -20 renko_bot.log
```

---

## 8. Risk Settings Guide

All in `config.py` under `SYMBOL_CONFIGS`.

| Parameter | What it controls | Default | Conservative | Aggressive |
|---|---|---|---|---|
| `delta_size` | Position size | 0.001 BTC | 0.001 BTC | 0.005 BTC |
| `max_daily_loss` | Bot stops if unrealized loss exceeds this (USD) | 50 | 20 | 100 |
| `max_trades_per_day` | Cap on signals per day | 6 | 4 | 8 |
| `trail_bricks` | Initial SL distance (bricks from stepline high/low) | 2 | 3 | 1 |
| `break_even_bricks` | Bricks in profit before SL snaps to entry (`0` = off) | 3 | 2 | 4 |
| `trail_bricks_after_be` | Trail tightness once break-even has fired | 1 | 1 | 1 |
| `chop_cooldown` | Bricks between flips before signal allowed | 3 | 5 | 2 |
| `min_bricks` | Minimum trend bricks before entry | 2 | 3 | 1 |

**Break-even flow:**
1. Trade opens → SL at `trail_bricks` (default 2) behind stepline high/low
2. Price moves `break_even_bricks` (default 3) ahead of entry → SL snaps to entry price
3. From that point on, trail tightens to `trail_bricks_after_be` (default 1)
4. Set `break_even_bricks = 0` to disable break-even entirely

**Backtest with break-even:**
```bash
# Default (BE@3, tight trail 1 brick)
python backtest.py --csv historical_data/BTC-USD_yfinance_5min_59d.csv \
  --bricktype percent --brick 0.1 --steplinetype points --stepline 300 \
  --trail 2 --breakeven 3 --trailafter 1

# Disable break-even (original behaviour)
python backtest.py --csv historical_data/BTC-USD_yfinance_5min_59d.csv \
  --bricktype percent --brick 0.1 --steplinetype points --stepline 300 \
  --trail 2 --breakeven 0
```

> **Start conservative.** Tighten only after the bot has run cleanly for 2+ weeks live.

### Daily loss guard note

`max_daily_loss` compares against **unrealized PnL of open positions**, not cumulative realized losses for the day. For tighter protection, lower this value to account for potential slippage on the close.

---

## 9. Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| `Auth failed — verify API keys` | Wrong key/secret in `.env` | Re-copy keys from Delta dashboard |
| `Unknown instrument` | `INSTRUMENT` not in `SYMBOL_CONFIGS` | Use `"BTC"`, `"ETH"`, or `"SOL"` |
| `Delta get_ltp failed` | Testnet down or symbol not found | Check `DELTA_TESTNET` flag; verify symbol exists on Delta |
| Bot places no orders for hours | Chop filter or min_bricks blocking signals | Normal in sideways market — reduce `chop_cooldown` if too restrictive |
| `SL order response invalid` | Delta API rate limit or server issue | Bot emergency-closes position and raises; check log for `Emergency close executed` |
| `MANUAL INTERVENTION REQUIRED` | Both entry and emergency close failed | Log in to Delta Exchange immediately and close manually |
| Bot stopped after max trades | `max_trades_per_day` hit | Normal behaviour — resets at midnight automatically |
| Service won't start | Wrong path in `.service` file | Verify `WorkingDirectory` and `ExecStart` paths |

---

*Last updated: 2026-05-02*
