# ============================================================
#  config.py  —  Renko Bot Configuration
#  Edit INSTRUMENT below. Credentials live in .env.
# ============================================================

import os
from dotenv import load_dotenv
load_dotenv()

# ── ACTIVE SYMBOL ─────────────────────────────────────────────
INSTRUMENT = "BTC"       # "BTC" | "ETH" | "SOL"
BROKER     = "delta"

# ── DELTA EXCHANGE CREDENTIALS ───────────────────────────────
DELTA_API_KEY    = os.getenv("DELTA_API_KEY", "")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET", "")
DELTA_TESTNET    = True  # True = testnet | False = live India

# ── SYMBOL CONFIGS (backtested values) ───────────────────────
# Each symbol has its own brick size, stepline, lot size etc.
# Only edit delta_size and max_daily_loss to match your risk.

SYMBOL_CONFIGS = {

    "BTC": dict(
        broker                = "delta",
        renko_brick_type      = "percent",
        renko_brick_value     = 0.1,      # 0.1% per brick
        stepline_type         = "points",
        stepline_value        = 300,      # BACKTESTED: 93 trades, 50.5% WR, 2.8:1 RR
        trail_bricks          = 2,        # initial SL distance in bricks
        break_even_bricks     = 3,        # bricks in profit → snap SL to entry
        trail_bricks_after_be = 1,        # tighter trail after break-even fires
        check_interval_sec    = 300,      # poll every 5 minutes
        delta_size            = 0.001,    # micro lot — $70 position at $70k BTC
        max_daily_loss        = 50,       # USD — bot stops if loss exceeds this
        max_trades_per_day    = 6,
        min_bricks            = 2,
        chop_cooldown         = 3,
    ),

    "ETH": dict(
        broker                = "delta",
        renko_brick_type      = "percent",
        renko_brick_value     = 0.1,      # 0.1% per brick
        stepline_type         = "percent",
        stepline_value        = 0.8,      # BACKTESTED: 28 trades, 42.9% WR, 6.62:1 RR
        trail_bricks          = 2,
        break_even_bricks     = 3,
        trail_bricks_after_be = 1,
        check_interval_sec    = 300,
        delta_size            = 0.01,     # micro lot — $22 position at $2200 ETH
        max_daily_loss        = 20,       # USD
        max_trades_per_day    = 6,
        min_bricks            = 2,
        chop_cooldown         = 3,
    ),

    "SOL": dict(
        broker                = "delta",
        renko_brick_type      = "percent",
        renko_brick_value     = 0.2,
        stepline_type         = "percent",
        stepline_value        = 2.0,      # 13 trades in 59d — low sample, trade carefully
        trail_bricks          = 2,
        break_even_bricks     = 3,
        trail_bricks_after_be = 1,
        check_interval_sec    = 300,
        delta_size            = 0.1,
        max_daily_loss        = 20,
        max_trades_per_day    = 4,
        min_bricks            = 2,
        chop_cooldown         = 3,
    ),
}

# ── DEFAULTS (fallback for any missing field) ─────────────────
DEFAULTS = dict(
    broker                = "delta",
    renko_brick_type      = "percent",
    renko_brick_value     = 0.1,
    stepline_type         = "points",
    stepline_value        = 300,
    min_bricks            = 2,
    chop_cooldown         = 3,
    trail_bricks          = 2,
    break_even_bricks     = 3,    # 0 = disabled
    trail_bricks_after_be = 1,    # must be < trail_bricks to be tighter
    check_interval_sec    = 300,
    delta_size            = 0.001,
    max_daily_loss        = 50,
    max_trades_per_day    = 6,
)

# ── RESOLVED CONFIG (auto-built — do not edit) ────────────────
class _SymbolConfig:
    def __init__(self, instrument: str):
        if instrument not in SYMBOL_CONFIGS:
            raise ValueError(
                f"'{instrument}' not in SYMBOL_CONFIGS. "
                f"Available: {list(SYMBOL_CONFIGS.keys())}"
            )
        merged = {**DEFAULTS, **SYMBOL_CONFIGS[instrument]}
        for k, v in merged.items():
            setattr(self, k, v)
        self.instrument = instrument

    def summary(self) -> str:
        be = (f"BE@{self.break_even_bricks}bricks→trail{self.trail_bricks_after_be}"
              if self.break_even_bricks > 0 else "BE=off")
        return (
            f"{self.instrument}  broker={self.broker}  "
            f"brick={self.renko_brick_value}{self.renko_brick_type}  "
            f"stepline={self.stepline_value}{self.stepline_type}  "
            f"trail={self.trail_bricks}bricks  {be}  "
            f"interval={self.check_interval_sec}s  "
            f"size={self.delta_size}"
        )

C = _SymbolConfig(INSTRUMENT)

# ── LOGGING ───────────────────────────────────────────────────
LOG_FILE  = "renko_bot.log"
LOG_LEVEL = "INFO"
