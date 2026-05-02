# ============================================================
#  test_connection.py  —  Delta Exchange connection test
#  Run this before bot.py to verify everything works.
# ============================================================

import requests
import hashlib
import hmac
import time

print("=" * 55)
print("  DELTA EXCHANGE CONNECTION TEST")
print("=" * 55)

try:
    import config
    BASE  = ("https://cdn.testnet.deltaex.org"
             if config.DELTA_TESTNET
             else "https://api.india.delta.exchange")
    MODE  = "TESTNET" if config.DELTA_TESTNET else "LIVE"
    print(f"  Mode: {MODE}")
    print(f"  URL:  {BASE}")
except Exception as e:
    print(f"  ERROR reading config.py: {e}")
    exit()

# ── Step 1: Public prices (no auth) ──────────────────────────
print("\n[1] Public price feed...")
for sym in ["BTCUSDT", "ETHUSDT"]:
    try:
        r    = requests.get(f"{BASE}/v2/tickers/{sym}", timeout=10)
        data = r.json()
        res  = data.get("result") or {}
        price = (res.get("mark_price") or
                 res.get("last_price") or
                 res.get("close"))
        if price:
            print(f"    OK  {sym}: ${float(price):,.2f}")
        else:
            print(f"  FAIL  {sym}: no price in response")
    except Exception as e:
        print(f"  FAIL  {sym}: {e}")

# ── Step 2: API key auth ──────────────────────────────────────
print("\n[2] API key authentication...")
try:
    key       = config.DELTA_API_KEY
    sec       = config.DELTA_API_SECRET
    if not key or not sec:
        print("  FAIL  DELTA_API_KEY or DELTA_API_SECRET is empty in config.py")
    else:
        timestamp = str(int(time.time()))
        path      = "/v2/profile"
        msg       = "GET" + timestamp + path
        sig       = hmac.new(sec.encode(), msg.encode(),
                             hashlib.sha256).hexdigest()
        headers   = {
            "api-key":   key,
            "timestamp": timestamp,
            "signature": sig,
            "Content-Type": "application/json",
        }
        r = requests.get(f"{BASE}{path}", headers=headers, timeout=10)
        d = r.json()
        if d.get("success"):
            email = d.get("result", {}).get("email", "?")
            print(f"    OK  Auth successful  email={email}")
        else:
            print(f"  FAIL  Auth failed: {d}")
            print("        Check DELTA_API_KEY and DELTA_API_SECRET in config.py")
except Exception as e:
    print(f"  FAIL  {e}")

# ── Step 3: Full broker test ──────────────────────────────────
print("\n[3] Full broker connection...")
try:
    from brokers import get_broker
    b = get_broker(config)
    for sym in ["BTC", "ETH"]:
        try:
            price = b.get_ltp(sym)
            print(f"    OK  {sym} price: ${price:,.2f}")
        except Exception as e:
            print(f"  FAIL  {sym}: {e}")
except Exception as e:
    print(f"  FAIL  Broker init: {e}")

# ── Step 4: Wallet balance ────────────────────────────────────
print("\n[4] Wallet / positions...")
try:
    pnl = b.get_pnl()
    print(f"    OK  Unrealized PnL: ${pnl:.4f}")
    print(f"        (0.0 = no open positions — normal)")
except Exception as e:
    print(f"  FAIL  {e}")

print("\n" + "=" * 55)
print("  If all steps show OK — run:  python bot.py")
print("=" * 55 + "\n")
