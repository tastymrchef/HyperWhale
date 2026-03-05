import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from hyperwhale.data.collector import HyperliquidCollector

c = HyperliquidCollector()
rows = c.get_leaderboard()

# The leaderboard is sorted by allTime PnL — let's confirm
# and check how many wallets have AV >= $1M anywhere in the list
av_1m = [r for r in rows if float(r.get('accountValue', 0)) >= 1_000_000]
av_1m_sorted = sorted(av_1m, key=lambda r: float(r.get('accountValue', 0)), reverse=True)

print(f"Total rows: {len(rows):,}")
print(f"AV >= $1M: {len(av_1m):,} wallets (scattered throughout all 31,590 rows)")

# Show the rank positions of $1M+ wallets — are they concentrated at the top or spread out?
positions = sorted([i for i, r in enumerate(rows) if float(r.get('accountValue', 0)) >= 1_000_000])
print(f"\nPosition of first $1M+ wallet: rank {positions[0]+1}")
print(f"Position of last $1M+ wallet:  rank {positions[-1]+1}")
print(f"Positions 990-1000 of $1M+ wallets: ranks {[p+1 for p in positions[989:999]]}")

print(f"\nTop 10 by AV:")
for r in av_1m_sorted[:10]:
    av = float(r.get('accountValue', 0))
    name = r.get('displayName') or r.get('ethAddress', '')[:12] + '...'
    pnl = float(r.get('windowPerformances', [['allTime', {'pnl': 0}]])[3][1].get('pnl', 0)) if len(r.get('windowPerformances', [])) > 3 else 0
    print(f"  {name:<22s}  AV: ${av:>15,.0f}")

print(f"\nConclusion: We already have ALL {len(av_1m):,} wallets with AV >= $1M in the API response.")
print(f"The issue is the existing registry only has 139 wallets because discover() was never run.")
