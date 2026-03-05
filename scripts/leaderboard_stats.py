import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from hyperwhale.data.collector import HyperliquidCollector

c = HyperliquidCollector()
rows = c.get_leaderboard()
avs = sorted([float(r.get('accountValue', 0)) for r in rows], reverse=True)

buckets = [
    (0,        10_000),
    (10_000,   50_000),
    (50_000,   100_000),
    (100_000,  250_000),
    (250_000,  500_000),
    (500_000,  1_000_000),
    (1_000_000,2_000_000),
    (2_000_000,5_000_000),
    (5_000_000,999_999_999),
]

print(f"\nLeaderboard AV distribution ({len(avs):,} total traders)\n")
print(f"  {'Range':>30s}   {'Count':>6s}   {'Cumulative >=':>14s}")
print("  " + "-"*60)
for lo, hi in buckets:
    count = sum(1 for a in avs if lo <= a < hi)
    cumulative = sum(1 for a in avs if a >= lo)
    hi_str = f"${hi:>12,.0f}" if hi < 999_999_999 else "         top"
    print(f"  ${lo:>12,.0f}  -  {hi_str}   {count:>6,}   {cumulative:>10,}")

print()
print(f"  Wallets with AV >= $500K  : {sum(1 for a in avs if a >= 500_000):,}")
print(f"  Wallets with AV >= $1M    : {sum(1 for a in avs if a >= 1_000_000):,}")
print(f"  Wallets with AV >= $2M    : {sum(1 for a in avs if a >= 2_000_000):,}")
print(f"  Wallets with AV >= $5M    : {sum(1 for a in avs if a >= 5_000_000):,}")
print(f"\n  Top 5 wallets by AV:")
top5 = sorted(rows, key=lambda r: float(r.get('accountValue', 0)), reverse=True)[:5]
for r in top5:
    av = float(r.get('accountValue', 0))
    name = r.get('displayName') or r.get('ethAddress', '')[:10] + '...'
    print(f"    {name:<20s}  ${av:>15,.0f}")
