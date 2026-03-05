import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from hyperwhale.data.collector import HyperliquidCollector
import urllib.request, json as _json

c = HyperliquidCollector()
rows = c.get_leaderboard()

print(f"Total rows returned by get_leaderboard(): {len(rows)}")
print(f"\nFirst row keys: {list(rows[0].keys()) if rows else 'EMPTY'}")
print(f"\nSample first row: {rows[0] if rows else 'EMPTY'}")
print(f"\nSample row at index 100: {rows[100] if len(rows) > 100 else 'N/A'}")

# Check what 'accountValue' actually is
avs = [float(r.get('accountValue', 0)) for r in rows]
print(f"\nMax AV: ${max(avs):,.0f}")
print(f"Min AV: ${min(avs):,.0f}")
print(f"AV >= $1M: {sum(1 for a in avs if a >= 1_000_000)}")

# Now try the raw URL directly to see full response structure
print("\n--- Raw API response structure ---")
url = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
with urllib.request.urlopen(url, timeout=60) as r:
    data = _json.loads(r.read())
print(f"Top-level keys: {list(data.keys())}")
if 'leaderboardRows' in data:
    print(f"leaderboardRows count: {len(data['leaderboardRows'])}")
# Check for pagination keys
for k in data:
    if k != 'leaderboardRows':
        print(f"  Other key '{k}': {data[k]}")
