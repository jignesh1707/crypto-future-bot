# ============================================================
#  renko_engine.py  —  Renko brick builder + Stepline machine
#  Broker-agnostic. Feed it prices, get signals out.
# ============================================================

from dataclasses import dataclass, field
from enum        import Enum
from typing      import List
import logging

log = logging.getLogger(__name__)


class Direction(Enum):
    UP   = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class Signal(Enum):
    BUY  = "BUY"
    SELL = "SELL"
    NONE = "NONE"


@dataclass
class RenkoBrick:
    open:      float
    close:     float
    direction: Direction


@dataclass
class SteplineState:
    direction:    Direction = Direction.FLAT
    start_price:  float     = 0.0
    high:         float     = 0.0
    low:          float     = 0.0
    points_moved: float     = 0.0


@dataclass
class EngineState:
    bricks:            List[RenkoBrick] = field(default_factory=list)
    last_brick_close:  float            = 0.0
    stepline:          SteplineState    = field(default_factory=SteplineState)
    last_signal:       Signal           = Signal.NONE
    bricks_since_flip: int              = 0
    last_flip_brick:   int              = 0


class RenkoEngine:
    """
    Renko brick builder + Stepline state machine.

    stepline_type = "points"  : flip after stepline_value raw price points
    stepline_type = "percent" : flip after stepline_value % of start price
                                scales automatically as price changes
    """

    def __init__(self,
                 brick_type:     str   = "percent",
                 brick_value:    float = 0.1,
                 stepline_type:  str   = "points",
                 stepline_value: float = 300.0,
                 min_bricks:     int   = 2,
                 chop_cooldown:  int   = 3):

        self.brick_type     = brick_type
        self.brick_value    = brick_value
        self.stepline_type  = stepline_type
        self.stepline_value = stepline_value
        self.min_bricks     = min_bricks
        self.chop_cooldown  = chop_cooldown
        self.state          = EngineState()

    def seed(self, price: float):
        self.state.last_brick_close = price
        self.state.stepline = SteplineState(
            direction=Direction.FLAT,
            start_price=price,
            high=price,
            low=price,
            points_moved=0.0,
        )
        log.info(f"Engine seeded at {price:.4f}")

    def update(self, price: float) -> Signal:
        self._build_bricks(price)
        return self._update_stepline(price)

    def trail_sl(self, direction: Direction, trail_bricks: int = 2) -> float:
        brick_size = self._brick_size(self.state.last_brick_close)
        if direction == Direction.UP:
            return self.state.stepline.high - brick_size * trail_bricks
        else:
            return self.state.stepline.low  + brick_size * trail_bricks

    def summary(self) -> dict:
        s = self.state
        threshold = (
            f"{self.stepline_value}% of start"
            if self.stepline_type == "percent"
            else f"{self.stepline_value}pts"
        )
        return {
            "bricks_total":       len(s.bricks),
            "last_brick_close":   s.last_brick_close,
            "stepline_dir":       s.stepline.direction.value,
            "stepline_moved":     round(s.stepline.points_moved, 4),
            "stepline_threshold": threshold,
            "bricks_since_flip":  s.bricks_since_flip,
            "last_signal":        s.last_signal.value,
        }

    # ── Internal ──────────────────────────────────────────────

    def _brick_size(self, reference_price: float) -> float:
        if self.brick_type == "percent":
            return reference_price * self.brick_value / 100.0
        return float(self.brick_value)

    def _build_bricks(self, price: float):
        ref   = self.state.last_brick_close
        count = 0
        while True:
            size = self._brick_size(ref)
            if price >= ref + size:
                self.state.bricks.append(
                    RenkoBrick(open=ref, close=ref+size, direction=Direction.UP))
                ref += size
                self.state.bricks_since_flip += 1
                count += 1
            elif price <= ref - size:
                self.state.bricks.append(
                    RenkoBrick(open=ref, close=ref-size, direction=Direction.DOWN))
                ref -= size
                self.state.bricks_since_flip += 1
                count += 1
            else:
                break
            if count >= 500:
                log.warning(f"_build_bricks: capped at 500 bricks "
                            f"(price={price:.4f} ref={ref:.4f}) — large price gap?")
                break
        self.state.last_brick_close = ref

    def _update_stepline(self, price: float) -> Signal:
        sl = self.state.stepline

        if price > sl.high: sl.high = price
        if sl.low == 0.0 or price < sl.low: sl.low = price

        # Threshold — points or percent
        if self.stepline_type == "percent":
            threshold = sl.start_price * self.stepline_value / 100.0
        else:
            threshold = float(self.stepline_value)

        # Points moved from leg start
        if sl.direction == Direction.UP:
            sl.points_moved = price - sl.start_price
        elif sl.direction == Direction.DOWN:
            sl.points_moved = sl.start_price - price
        else:
            sl.points_moved = abs(price - sl.start_price)

        signal = Signal.NONE

        if sl.direction != Direction.UP and price >= sl.start_price + threshold:
            signal = self._try_emit(Direction.UP, price)
        elif sl.direction != Direction.DOWN and price <= sl.start_price - threshold:
            signal = self._try_emit(Direction.DOWN, price)

        return signal

    def _try_emit(self, new_direction: Direction, price: float) -> Signal:
        total_bricks  = len(self.state.bricks)
        bricks_since  = total_bricks - self.state.last_flip_brick

        # Chop filter
        if bricks_since < self.chop_cooldown:
            log.debug(f"Chop filter: {bricks_since} bricks since last flip "
                      f"(need {self.chop_cooldown})")
            return Signal.NONE

        # Min bricks in new direction
        direction_bricks = sum(
            1 for b in self.state.bricks[-self.min_bricks:]
            if b.direction.value == new_direction.value
        )
        if direction_bricks < self.min_bricks:
            log.debug(f"Min brick filter: {direction_bricks}/{self.min_bricks}")
            return Signal.NONE

        # Commit flip
        old_dir = self.state.stepline.direction
        self.state.stepline.direction    = new_direction
        self.state.stepline.start_price  = price
        self.state.stepline.high         = price
        self.state.stepline.low          = price
        self.state.stepline.points_moved = 0.0
        self.state.last_flip_brick       = total_bricks
        self.state.bricks_since_flip     = 0

        signal = Signal.BUY if new_direction == Direction.UP else Signal.SELL
        self.state.last_signal = signal

        log.info(f"STEPLINE FLIP  {old_dir.value} -> {new_direction.value}  "
                 f"@ {price:.4f}  signal={signal.value}")
        return signal
