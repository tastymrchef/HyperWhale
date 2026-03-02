"""Quick test for the scoring system."""
from datetime import datetime, timedelta
from hyperwhale.scoring import WhaleScorer

s = WhaleScorer()
now = datetime.utcnow()

cases = [
    # (label, account_value, total_notional, trade_count_30d, last_trade_time)
    ("$123M dormant",    123_000_000,         0,   0, None),
    ("$50M dormant",      50_000_000,         0,   0, None),
    ("$50M active",       50_000_000, 20_000_000, 100, now - timedelta(hours=1)),
    ("$10M active",       10_000_000,  8_000_000,  50, now - timedelta(hours=2)),
    ("$5M moderate",       5_000_000,  3_000_000,  25, now - timedelta(days=3)),
    ("$2M light",          2_000_000,    500_000,   3, None),
    ("$1.5M grinder",     1_500_000,  1_200_000,  80, now - timedelta(hours=5)),
    ("$1M minimal",        1_000_000,    100_000,   1, None),
    ("$500K rich noob",      500_000,    200_000,   5, now - timedelta(days=2)),
    ("$100K small",          100_000,     50_000,  10, now - timedelta(hours=12)),
]

print(f"{'Label':>18s} | {'Tier':>14s} | {'Score':>5s} | {'Acct':>4s} | {'Pos':>4s} | {'Act':>4s}")
print("-" * 75)

for label, av, tn, tc, ltt in cases:
    r = s.score(av, tn, tc, ltt)
    print(f"{label:>18s} | {r.tier.value:>14s} | {r.whale_score:>5.1f} | {r.account_score:>4.0f} | {r.position_score:>4.0f} | {r.activity_score:>4.0f}")
