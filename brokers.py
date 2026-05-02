# ============================================================
#  brokers.py  —  Delta Exchange India broker adapter
#
#  Supports:
#    - Testnet:  https://cdn.testnet.deltaex.org
#    - Live:     https://api.india.delta.exchange
#
#  Confirmed working symbols on testnet:
#    BTC -> BTCUSDT  (id=84)
#    ETH -> ETHUSDT  (id=1699)
# ============================================================

import time
import logging
import hashlib
import hmac
import requests

log = logging.getLogger(__name__)


class DeltaBroker:

    # Confirmed symbol names for India platform
    SYMBOLS = {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        "BNB": "BNBUSDT",
        "XRP": "XRPUSDT",
    }

    # Confirmed product IDs on testnet
    PRODUCT_IDS = {
        "BTC": 27,
        "ETH": 3136,
        "SOL": 92410,
    }

    def __init__(self, cfg):
        self.cfg              = cfg
        self.client           = None
        self._last_product_id = None
        self._last_direction  = None

        if cfg.DELTA_TESTNET:
            self.base = "https://cdn.testnet.deltaex.org"
        else:
            self.base = "https://api.india.delta.exchange"

    def connect(self):
        try:
            from delta_rest_client import DeltaRestClient
            self.client = DeltaRestClient(
                base_url   = self.base,
                api_key    = self.cfg.DELTA_API_KEY,
                api_secret = self.cfg.DELTA_API_SECRET,
            )
            mode = "TESTNET" if self.cfg.DELTA_TESTNET else "LIVE (India)"
            log.info(f"Delta Exchange connected: {mode}  url={self.base}")

            # Auth check
            try:
                timestamp = str(int(time.time()))
                path      = "/v2/profile"
                msg       = "GET" + timestamp + path
                sig       = hmac.new(
                    self.cfg.DELTA_API_SECRET.encode(),
                    msg.encode(), hashlib.sha256
                ).hexdigest()
                headers = {
                    "api-key":   self.cfg.DELTA_API_KEY,
                    "timestamp": timestamp,
                    "signature": sig,
                    "Content-Type": "application/json",
                }
                r = requests.get(f"{self.base}{path}",
                                 headers=headers, timeout=10)
                d = r.json()
                if d.get("success"):
                    email = d.get("result", {}).get("email", "?")
                    log.info(f"Delta auth OK  email={email}")
                else:
                    log.warning("Delta auth check failed — verify API keys")
            except Exception as e:
                log.warning(f"Delta auth check error: {e}")

        except ImportError:
            raise ImportError(
                "Run: python -m pip install delta-rest-client requests"
            )

    # ── Price ─────────────────────────────────────────────────

    def get_ltp(self, instrument: str) -> float:
        """
        Fetch mark price via public REST endpoint.
        Tries multiple symbol formats automatically.
        """
        inst = instrument.upper()
        candidates = {
            "BTC": ["BTCUSDT", "BTCUSD"],
            "ETH": ["ETHUSDT", "ETHUSD"],
            "SOL": ["SOLUSDT", "SOLUSD"],
        }.get(inst, [f"{inst}USDT", f"{inst}USD"])

        last_error = None
        for symbol in candidates:
            try:
                url  = f"{self.base}/v2/tickers/{symbol}"
                resp = requests.get(url, timeout=10)
                if resp.status_code != 200:
                    continue
                data   = resp.json()
                result = data.get("result")
                if result and isinstance(result, dict):
                    price = (result.get("mark_price") or
                             result.get("last_price") or
                             result.get("close"))
                    if price and float(price) > 0:
                        return float(price)
            except Exception as e:
                last_error = e
                continue

        raise ValueError(
            f"Delta get_ltp failed for {instrument}. "
            f"Last error: {last_error}"
        )

    # ── Order placement ───────────────────────────────────────

    def place_order(self, instrument: str, direction: str,
                    qty, sl_price: float) -> str:
        """
        Place market entry order then immediately place stop-loss order.
        Two separate calls — delta-rest-client does not support
        stop_loss_order as a kwarg.
        Returns the SL order id (used for modify and cancel).
        """
        product_id = self._get_product_id(instrument)
        side       = "buy"  if direction == "BUY"  else "sell"
        sl_side    = "sell" if direction == "BUY"  else "buy"
        size       = float(self.cfg.C.delta_size)

        # Cache for modify_sl
        self._last_product_id = product_id
        self._last_direction  = direction

        log.info(f"Delta order: {instrument} {side}  "
                 f"size={size}  sl={sl_price:.4f}")

        # Step 1 — market entry
        try:
            order = self.client.place_order(
                product_id = product_id,
                size       = size,
                side       = side,
                order_type = "market_order",
            )
            if not order or 'id' not in order:
                raise RuntimeError(f"Entry order failed: {order}")
            entry_id = str(order['id'])
            log.info(f"Entry OK  id={entry_id}  {instrument} {side} {size}")
        except Exception as e:
            raise RuntimeError(f"Delta entry order failed: {e}")

        # Brief pause — let entry fill
        time.sleep(0.5)

        # Step 2 — stop loss order
        try:
            sl_order = self.client.place_order(
                product_id  = product_id,
                size        = size,
                side        = sl_side,
                order_type  = "stop_market_order",
                stop_price  = round(sl_price, 2),
                reduce_only = True,
            )
            if sl_order and 'id' in sl_order:
                sl_id = str(sl_order['id'])
                log.info(f"SL order OK  id={sl_id}  trigger={sl_price:.4f}")
                return sl_id
            else:
                log.warning(f"SL order issue: {sl_order} "
                            f"— position open but NO stop loss!")
                return entry_id
        except Exception as e:
            log.warning(f"SL order failed: {e} "
                        f"— position open WITHOUT stop loss! "
                        f"Close manually if needed.")
            return entry_id

    # ── Modify SL ─────────────────────────────────────────────

    def modify_sl(self, order_id: str, new_sl: float):
        """
        Cancel old SL order and place new one at updated price.
        Returns new SL order id (str) on success, None on failure.
        Delta REST client does not support editing stop price directly.
        """
        # Cancel old SL
        try:
            self.client.cancel_order(order_id=order_id)
            log.debug(f"Old SL {order_id} cancelled")
            time.sleep(0.3)
        except Exception as e:
            log.debug(f"Cancel SL {order_id}: {e} (may already be filled)")

        if not self._last_product_id:
            log.warning("Cannot place new SL — product_id not cached")
            return False

        # Place new SL
        try:
            sl_side  = "sell" if self._last_direction == "BUY" else "buy"
            size     = float(self.cfg.C.delta_size)
            sl_order = self.client.place_order(
                product_id  = self._last_product_id,
                size        = size,
                side        = sl_side,
                order_type  = "stop_market_order",
                stop_price  = round(new_sl, 2),
                reduce_only = True,
            )
            if sl_order and 'id' in sl_order:
                new_id = str(sl_order['id'])
                log.info(f"SL updated -> {new_sl:.4f}  new_id={new_id}")
                return new_id
            else:
                log.warning(f"New SL failed: {sl_order}")
                return None
        except Exception as e:
            log.error(f"modify_sl failed: {e}")
            return None

    # ── Close position ────────────────────────────────────────

    def close_position(self, order_id: str, instrument: str,
                       direction: str, qty) -> bool:
        """Cancel SL order and close position with reduce-only market order."""
        product_id = self._get_product_id(instrument)
        close_side = "sell" if direction == "BUY" else "buy"
        size       = float(self.cfg.C.delta_size)

        # Cancel pending SL first
        try:
            self.client.cancel_order(order_id=order_id)
            log.info(f"SL order {order_id} cancelled")
        except Exception as e:
            log.debug(f"Cancel SL on close: {e}")

        # Market close
        try:
            self.client.place_order(
                product_id  = product_id,
                size        = size,
                side        = close_side,
                order_type  = "market_order",
                reduce_only = True,
            )
            log.info(f"Position closed: {instrument} {close_side} {size}")
            return True
        except Exception as e:
            log.error(f"close_position failed: {e}")
            return False

    # ── PnL ───────────────────────────────────────────────────

    def get_pnl(self) -> float:
        """Unrealized PnL across all open positions (USD)."""
        try:
            timestamp = str(int(time.time()))
            path      = "/v2/positions/margined"
            msg       = "GET" + timestamp + path
            sig       = hmac.new(
                self.cfg.DELTA_API_SECRET.encode(),
                msg.encode(), hashlib.sha256
            ).hexdigest()
            headers = {
                "api-key":   self.cfg.DELTA_API_KEY,
                "timestamp": timestamp,
                "signature": sig,
                "Content-Type": "application/json",
            }
            r         = requests.get(f"{self.base}{path}",
                                     headers=headers, timeout=10)
            positions = r.json().get("result", [])
            if not positions:
                return 0.0
            return sum(
                float(p.get("unrealized_pnl", 0))
                for p in positions if isinstance(p, dict)
            )
        except Exception as e:
            log.debug(f"get_pnl: {e}")
            return 0.0

    # ── Helpers ───────────────────────────────────────────────

    def _get_product_id(self, instrument: str) -> int:
        pid = self.PRODUCT_IDS.get(instrument.upper())
        if not pid:
            raise ValueError(
                f"Unknown instrument '{instrument}'. "
                f"Known: {list(self.PRODUCT_IDS.keys())}"
            )
        return pid


# ── Factory ───────────────────────────────────────────────────

def get_broker(cfg) -> DeltaBroker:
    broker = DeltaBroker(cfg)
    broker.connect()
    return broker
