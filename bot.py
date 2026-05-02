# ============================================================
#  bot.py  —  Renko trailing SL bot for Delta Exchange
#
#  Set INSTRUMENT in config.py then run:
#    python bot.py
#
#  To trade BTC:  set INSTRUMENT = "BTC" in config.py
#  To trade ETH:  set INSTRUMENT = "ETH" in config.py
# ============================================================

import time
import logging
import logging.handlers
from dataclasses import dataclass
from typing      import Optional

import config
from config       import C
from renko_engine import RenkoEngine, Signal, Direction
from brokers      import get_broker


# ── Logging ───────────────────────────────────────────────────

def setup_logging():
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    import sys, io
    stream = io.TextIOWrapper(
        sys.stdout.buffer, encoding='utf-8', errors='replace')
    ch = logging.StreamHandler(stream)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    fh = logging.handlers.RotatingFileHandler(
        config.LOG_FILE, maxBytes=5_000_000,
        backupCount=3, encoding='utf-8')
    fh.setFormatter(fmt)
    root.addHandler(fh)

log = logging.getLogger(__name__)


# ── Position ──────────────────────────────────────────────────

@dataclass
class Position:
    order_id:    str
    direction:   Direction
    entry_price: float
    qty:         float
    current_sl:  float


# ── Bot ───────────────────────────────────────────────────────

class RenkoBot:

    def __init__(self):
        setup_logging()
        log.info("=" * 60)
        log.info(f"RenkoBot  {C.summary()}")
        log.info("=" * 60)

        self.engine = RenkoEngine(
            brick_type     = C.renko_brick_type,
            brick_value    = C.renko_brick_value,
            stepline_type  = C.stepline_type,
            stepline_value = C.stepline_value,
            min_bricks     = C.min_bricks,
            chop_cooldown  = C.chop_cooldown,
        )
        self.broker       = None
        self.position:    Optional[Position] = None
        self.trades_today = 0

    def run(self):
        log.info("Connecting to Delta Exchange...")
        self.broker = get_broker(config)

        log.info("Seeding engine with first price...")
        ltp = self.broker.get_ltp(C.instrument)
        self.engine.seed(ltp)
        log.info(f"Seeded @ {ltp:.4f}")
        log.info(f"Polling every {C.check_interval_sec}s — waiting for signals...")

        while True:
            try:
                self._tick()
            except KeyboardInterrupt:
                log.info("Stopping — closing any open position...")
                self._close_position()
                break
            except Exception as e:
                log.error(f"Tick error: {e}", exc_info=True)

            time.sleep(C.check_interval_sec)

    def _tick(self):
        ltp     = self.broker.get_ltp(C.instrument)
        pos_str = (f"IN {self.position.direction.value} "
                   f"SL={self.position.current_sl:.4f}"
                   if self.position else "FLAT")
        log.info(f"LTP={ltp:.4f}  {pos_str}")

        # Daily loss guard
        pnl = self.broker.get_pnl()
        if pnl <= -abs(C.max_daily_loss):
            log.warning(f"Daily loss limit hit  pnl={pnl:.2f}  "
                        f"limit={C.max_daily_loss}  Stopping.")
            self._close_position()
            raise SystemExit("Daily loss limit reached.")

        # Engine update
        signal  = self.engine.update(ltp)
        summary = self.engine.summary()
        log.info(f"bricks={summary['bricks_total']}  "
                 f"stepline={summary['stepline_dir']}  "
                 f"moved={summary['stepline_moved']}  "
                 f"threshold={summary['stepline_threshold']}")

        # Signal handling
        if signal in (Signal.BUY, Signal.SELL):
            new_dir = Direction.UP if signal == Signal.BUY else Direction.DOWN
            if self.position and self.position.direction != new_dir:
                log.info(f"Reversal — closing {self.position.direction.value}")
                self._close_position()
            if not self.position:
                if self.trades_today < C.max_trades_per_day:
                    self._open_position(signal, ltp)
                else:
                    log.warning(f"Max trades/day ({C.max_trades_per_day}) "
                                f"reached — signal skipped")
        elif self.position:
            self._trail_sl(ltp)

    def _open_position(self, signal: Signal, ltp: float):
        direction  = Direction.UP if signal == Signal.BUY else Direction.DOWN
        initial_sl = self.engine.trail_sl(direction, C.trail_bricks)
        size       = C.delta_size

        log.info(f"OPEN {direction.value} @ {ltp:.4f}  "
                 f"SL={initial_sl:.4f}  size={size}")

        order_id = self.broker.place_order(
            instrument = C.instrument,
            direction  = signal.value,
            qty        = size,
            sl_price   = initial_sl,
        )

        self.position = Position(
            order_id    = order_id,
            direction   = direction,
            entry_price = ltp,
            qty         = size,
            current_sl  = initial_sl,
        )
        self.trades_today += 1
        log.info(f"Position open  id={order_id}  "
                 f"trades_today={self.trades_today}/{C.max_trades_per_day}")

    def _trail_sl(self, ltp: float):
        p      = self.position
        new_sl = self.engine.trail_sl(p.direction, C.trail_bricks)

        should_update = (
            (p.direction == Direction.UP   and new_sl > p.current_sl) or
            (p.direction == Direction.DOWN and new_sl < p.current_sl)
        )
        if should_update:
            log.info(f"Trail SL  {p.current_sl:.4f} -> {new_sl:.4f}")
            new_id = self.broker.modify_sl(p.order_id, new_sl)
            if new_id:
                self.position.current_sl = new_sl
                self.position.order_id   = new_id

        # SL hit detection
        sl_hit = (
            (p.direction == Direction.UP   and ltp <= p.current_sl) or
            (p.direction == Direction.DOWN and ltp >= p.current_sl)
        )
        if sl_hit:
            log.info(f"SL hit  ltp={ltp:.4f}  sl={p.current_sl:.4f}")
            self.position = None

    def _close_position(self):
        if not self.position:
            return
        p = self.position
        self.broker.close_position(
            order_id   = p.order_id,
            instrument = C.instrument,
            direction  = p.direction.value,
            qty        = p.qty,
        )
        self.position = None


if __name__ == "__main__":
    bot = RenkoBot()
    bot.run()
