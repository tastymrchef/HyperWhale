"""Test what historical data Hyperliquid API actually provides."""

import json
import time
import httpx
from datetime import datetime, timedelta

API = "https://api.hyperliquid.xyz/info"
client = httpx.Client(timeout=30)

# Use one of our known active whales
WHALE = "0xbe19541903f64af97bcf8436f4d15bf3a56b8bd1"

print("=" * 60)
print(f"Testing historical data for {WHALE[:12]}...")
print("=" * 60)

# 1. userFillsByTime — how far back can we go?
print("\n--- 1. Trade History (userFillsByTime) ---")
two_months_ago = int((datetime.utcnow() - timedelta(days=60)).timestamp() * 1000)
one_month_ago = int((datetime.utcnow() - timedelta(days=30)).timestamp() * 1000)
one_week_ago = int((datetime.utcnow() - timedelta(days=7)).timestamp() * 1000)

for label, start_ts in [("60 days", two_months_ago), ("30 days", one_month_ago), ("7 days", one_week_ago)]:
    resp = client.post(API, json={"type": "userFillsByTime", "user": WHALE, "startTime": start_ts})
    fills = resp.json()
    print(f"  Last {label}: {len(fills)} fills")
    if fills and len(fills) > 0:
        first = fills[0]
        last = fills[-1]
        first_time = datetime.fromtimestamp(first.get("time", 0) / 1000)
        last_time = datetime.fromtimestamp(last.get("time", 0) / 1000)
        print(f"    First fill: {first_time}")
        print(f"    Last fill:  {last_time}")
        if len(fills) > 0:
            sample = fills[0]
            print(f"    Sample: coin={sample.get('coin')} side={sample.get('side')} sz={sample.get('sz')} px={sample.get('px')} dir={sample.get('dir')}")
    time.sleep(0.3)

# 2. historicalOrders — what comes back?
print("\n--- 2. Historical Orders ---")
resp = client.post(API, json={"type": "historicalOrders", "user": WHALE})
orders = resp.json()
print(f"  Total historical orders: {len(orders)}")
if orders and len(orders) > 0:
    first_order = orders[0]
    if isinstance(first_order, dict):
        print(f"  First order keys: {list(first_order.keys())[:10]}")
        ts = first_order.get("timestamp")
        if ts:
            print(f"  First order time: {datetime.fromtimestamp(ts / 1000)}")
    last_order = orders[-1]
    if isinstance(last_order, dict):
        ts = last_order.get("timestamp")
        if ts:
            print(f"  Last order time: {datetime.fromtimestamp(ts / 1000)}")

# 3. portfolio — account value history
print("\n--- 3. Portfolio (Account Value History) ---")
resp = client.post(API, json={"type": "portfolio", "user": WHALE})
portfolio = resp.json()
print(f"  Type: {type(portfolio)}")
if isinstance(portfolio, list):
    print(f"  Entries: {len(portfolio)}")
    for entry in portfolio[:3]:
        if isinstance(entry, list) and len(entry) >= 2:
            period = entry[0]
            data = entry[1]
            if isinstance(data, dict):
                av_hist = data.get("accountValueHistory", [])
                pnl_hist = data.get("pnlHistory", [])
                print(f"    Period '{period}': {len(av_hist)} account value points, {len(pnl_hist)} PnL points")
                if av_hist:
                    first_ts = datetime.fromtimestamp(av_hist[0][0] / 1000)
                    last_ts = datetime.fromtimestamp(av_hist[-1][0] / 1000)
                    print(f"      Range: {first_ts} → {last_ts}")
                    print(f"      First AV: ${float(av_hist[0][1]):,.2f}  Last AV: ${float(av_hist[-1][1]):,.2f}")

# 4. userFills — basic (no time filter)
print("\n--- 4. User Fills (basic, no time filter) ---")
resp = client.post(API, json={"type": "userFills", "user": WHALE})
fills_basic = resp.json()
print(f"  Total fills returned: {len(fills_basic)}")

# 5. Check a second whale too
WHALE2 = "0x6417da1d2452a4b4a81aa151b7235ffec865082f"
print(f"\n--- 5. Second whale {WHALE2[:12]}... ---")
resp = client.post(API, json={"type": "userFillsByTime", "user": WHALE2, "startTime": two_months_ago})
fills2 = resp.json()
print(f"  Fills in last 60 days: {len(fills2)}")
if fills2:
    first_time = datetime.fromtimestamp(fills2[0].get("time", 0) / 1000)
    last_time = datetime.fromtimestamp(fills2[-1].get("time", 0) / 1000)
    print(f"  Range: {first_time} → {last_time}")

    # Count unique coins
    coins = set(f.get("coin") for f in fills2)
    print(f"  Coins traded: {coins}")

    # Summarize by coin
    from collections import Counter
    coin_counts = Counter(f.get("coin") for f in fills2)
    for coin, count in coin_counts.most_common(5):
        print(f"    {coin}: {count} fills")

client.close()
print("\n✅ Done")
