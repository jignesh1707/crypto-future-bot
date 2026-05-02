# ============================================================
#  data_fetcher.py  —  Download historical OHLCV data
#
#  Usage:
#    python data_fetcher.py --source yfinance --instrument BTC-USD --interval 5min --days 59
#    python data_fetcher.py --source yfinance --instrument ETH-USD --interval 5min --days 59
#    python data_fetcher.py --source yfinance --instrument SOL-USD --interval 5min --days 59
#
#  Note: yfinance 5min data = max 60 days
#        yfinance 1d  data  = years of data
# ============================================================

import argparse
import csv
import os
import time
import logging
from datetime import datetime, timedelta
from pathlib  import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

OUTPUT_DIR = Path("historical_data")


class Candle:
    __slots__ = ("dt","open","high","low","close","volume")
    def __init__(self, dt, o, h, l, c, v=0):
        self.dt     = dt
        self.open   = float(o)
        self.high   = float(h)
        self.low    = float(l)
        self.close  = float(c)
        self.volume = int(v) if v else 0


def save_csv(candles, filename: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / filename
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datetime","open","high","low","close","volume"])
        for c in candles:
            w.writerow([
                c.dt.strftime("%Y-%m-%d %H:%M:%S"),
                f"{c.open:.4f}", f"{c.high:.4f}",
                f"{c.low:.4f}",  f"{c.close:.4f}",
                c.volume
            ])
    log.info(f"Saved {len(candles)} candles -> {path}")
    return path


# ── yfinance ──────────────────────────────────────────────────

class YFinanceFetcher:

    MAX_DAYS = {
        "1m": 7, "2m": 60, "5m": 60, "15m": 60,
        "30m": 60, "60m": 730, "1h": 730,
        "1d": 9999, "1wk": 9999,
    }

    INTERVAL_MAP = {
        "1min":  "1m",  "2min":  "2m",  "5min":  "5m",
        "15min": "15m", "30min": "30m", "60min": "60m",
        "1h":    "1h",  "1d":    "1d",  "1wk":   "1wk",
    }

    def fetch(self, instrument: str, interval: str, days: int):
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("python -m pip install yfinance")

        yf_interval = self.INTERVAL_MAP.get(interval, interval)
        max_days    = self.MAX_DAYS.get(yf_interval, 60)
        if days > max_days:
            log.warning(f"yfinance {interval} max={max_days}d. Capping.")
            days = max_days

        end_dt   = datetime.now()
        start_dt = end_dt - timedelta(days=days)

        log.info(f"yfinance: {instrument} {interval} "
                 f"{start_dt.date()} -> {end_dt.date()}")

        ticker = yf.Ticker(instrument)
        df = ticker.history(
            start    = start_dt.strftime("%Y-%m-%d"),
            end      = end_dt.strftime("%Y-%m-%d"),
            interval = yf_interval,
            auto_adjust = True,
        )

        if df.empty:
            raise ValueError(f"No data returned for {instrument}")

        candles = []
        for ts, row in df.iterrows():
            try:
                dt = ts.to_pydatetime().replace(tzinfo=None)
                candles.append(Candle(
                    dt=dt,
                    o=row['Open'], h=row['High'],
                    l=row['Low'],  c=row['Close'],
                    v=row.get('Volume', 0)
                ))
            except Exception:
                continue

        log.info(f"yfinance: {len(candles)} candles for {instrument}")
        return candles


# ── Delta Exchange (global, public, no auth) ──────────────────
#
#  Practical data depth by interval:
#    5min  → ~60–90 days    (sub-hourly cache limited by exchange)
#    60min → ~1–2 years
#    4h    → ~2–3 years
#    1d    → ~4–5 years     (Delta launched 2019)
#
#  Recommended brick sizes when switching timeframe:
#    5min  → brick 0.1%     (current backtested params)
#    60min → brick 0.3–0.5%
#    4h    → brick 0.5–1.0%

class DeltaFetcher:

    INTERVAL_MAP = {
        "1min": "1m", "5min": "5m", "15min": "15m",
        "30min": "30m", "60min": "1h", "4h": "4h",
        "1d": "1d", "1w": "1w"
    }

    # Realistic max days per interval — request more and the API
    # silently returns whatever it has, so no hard cap needed here.
    SUGGESTED_MAX_DAYS = {
        "1m": 7, "5m": 90, "15m": 180, "30m": 365,
        "1h": 730, "4h": 1095, "1d": 1825, "1w": 9999,
    }

    # Try USDT-margined first (more liquid on Delta India),
    # fall back to inverse (USD-margined) if no data returned.
    SYMBOL_CANDIDATES = {
        "BTC": ["BTCUSDT", "BTCUSD"],
        "ETH": ["ETHUSDT", "ETHUSD"],
        "SOL": ["SOLUSDT", "SOLUSD"],
    }

    def fetch(self, instrument: str, interval: str, days: int):
        try:
            import requests
        except ImportError:
            raise ImportError("python -m pip install requests")

        resolution = self.INTERVAL_MAP.get(interval)
        if not resolution:
            raise ValueError(f"Unsupported interval '{interval}'. "
                             f"Choose: {list(self.INTERVAL_MAP.keys())}")

        suggested = self.SUGGESTED_MAX_DAYS.get(resolution, 90)
        if days > suggested:
            log.warning(f"Requested {days}d for {interval} — Delta typically "
                        f"provides ~{suggested}d at this resolution. "
                        f"Fetching anyway; actual depth depends on the exchange.")

        candidates = self.SYMBOL_CANDIDATES.get(
            instrument.upper(),
            [f"{instrument.upper()}USDT", f"{instrument.upper()}USD"]
        )
        base_url = "https://api.delta.exchange/v2/history/candles"

        secs       = {"1m":60,"5m":300,"15m":900,"30m":1800,
                      "1h":3600,"4h":14400,"1d":86400,"1w":604800}
        chunk_secs = 500 * secs.get(resolution, 300)

        # Auto-detect working symbol
        symbol = None
        for candidate in candidates:
            test_end   = int(datetime.now().timestamp())
            test_start = test_end - chunk_secs
            try:
                r = requests.get(base_url, params={
                    "resolution": resolution, "symbol": candidate,
                    "start": test_start, "end": test_end,
                }, timeout=15)
                d = r.json()
                if d.get("success") and d.get("result"):
                    symbol = candidate
                    log.info(f"Delta symbol resolved: {symbol}")
                    break
            except Exception:
                continue

        if not symbol:
            raise ValueError(
                f"No working symbol found for {instrument} on Delta "
                f"(tried: {candidates}). Check instrument name."
            )

        end_ts      = int(datetime.now().timestamp())
        start_ts    = int((datetime.now() - timedelta(days=days)).timestamp())
        cursor      = start_ts
        all_candles = []

        while cursor < end_ts:
            chunk_end = min(cursor + chunk_secs, end_ts)
            log.info(f"  Delta [{symbol}] "
                     f"{datetime.fromtimestamp(cursor).strftime('%Y-%m-%d')} "
                     f"-> {datetime.fromtimestamp(chunk_end).strftime('%Y-%m-%d')} ...")
            try:
                resp = requests.get(base_url, params={
                    "resolution": resolution,
                    "symbol":     symbol,
                    "start":      cursor,
                    "end":        chunk_end,
                }, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                if data.get("success") and data.get("result"):
                    for bar in data["result"]:
                        try:
                            dt = datetime.fromtimestamp(int(bar["time"]))
                            all_candles.append(Candle(
                                dt=dt,
                                o=bar["open"],  h=bar["high"],
                                l=bar["low"],   c=bar["close"],
                                v=bar.get("volume", 0)
                            ))
                        except Exception:
                            continue
            except Exception as e:
                log.error(f"  Chunk failed: {e}")

            cursor = chunk_end + 1
            time.sleep(0.3)

        all_candles.sort(key=lambda c: c.dt)
        seen, unique = set(), []
        for c in all_candles:
            if c.dt not in seen:
                seen.add(c.dt)
                unique.append(c)

        log.info(f"Delta: {len(unique)} candles for {instrument} "
                 f"({interval}, {days}d requested)")
        return unique


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Download historical OHLCV data",
        epilog="""
Examples — Delta Exchange (deeper history):
  5-min  ~90 days  : python data_fetcher.py --source delta --instrument BTC --interval 5min  --days 90
  1-hour ~2 years  : python data_fetcher.py --source delta --instrument BTC --interval 60min --days 730
  4-hour ~3 years  : python data_fetcher.py --source delta --instrument BTC --interval 4h    --days 1095
  Daily  ~5 years  : python data_fetcher.py --source delta --instrument BTC --interval 1d    --days 1825

Suggested brick sizes per timeframe:
  5min  → --brick 0.1  (backtested)
  60min → --brick 0.4
  4h    → --brick 0.7
  1d    → --brick 1.0
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--source",     required=True,
                   help="yfinance | delta")
    p.add_argument("--instrument", required=True,
                   help="BTC-USD | ETH-USD | SOL-USD (yfinance)  or  BTC | ETH | SOL (delta)")
    p.add_argument("--interval",   default="5min",
                   help="1min | 5min | 15min | 30min | 60min | 4h | 1d | 1w  (default: 5min)")
    p.add_argument("--days",       type=int, default=59,
                   help="Days of history to fetch (default: 59)")
    args = p.parse_args()

    fetchers = {"yfinance": YFinanceFetcher, "delta": DeltaFetcher}
    cls = fetchers.get(args.source.lower())
    if not cls:
        print(f"Unknown source '{args.source}'. Choose: yfinance | delta")
        exit(1)

    try:
        candles = cls().fetch(args.instrument, args.interval, args.days)
        if not candles:
            print("No candles returned.")
            exit(1)
        fname  = f"{args.instrument}_{args.source}_{args.interval}_{args.days}d.csv"
        path   = save_csv(candles, fname)
        prices = [c.close for c in candles]
        log.info(f"Range: {min(prices):.2f} - {max(prices):.2f}  "
                 f"First: {candles[0].dt}  Last: {candles[-1].dt}")

        # Suggest brick size based on interval
        brick_hints = {
            "5min": "0.1", "60min": "0.4", "4h": "0.7", "1d": "1.0"
        }
        brick = brick_hints.get(args.interval, "0.1")
        print(f"\nReady for backtest (suggested brick for {args.interval}):")
        print(f"  python backtest.py --csv {path} "
              f"--bricktype percent --brick {brick} "
              f"--steplinetype points --stepline 300 --trail 2")
    except Exception as e:
        log.error(f"Failed: {e}")
        exit(1)
