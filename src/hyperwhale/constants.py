"""Constants used across HyperWhale."""

# ---------------------------------------------------------------------------
# Hyperliquid API
# ---------------------------------------------------------------------------
MAINNET_API_URL = "https://api.hyperliquid.xyz"
TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"
INFO_ENDPOINT = "/info"

# ---------------------------------------------------------------------------
# Whale Scoring System
# ---------------------------------------------------------------------------

# --- Composite Score Weights (must sum to 1.0) ---
SCORE_WEIGHT_ACCOUNT = 0.60      # 60% — account value dominance
SCORE_WEIGHT_POSITION = 0.20     # 20% — position sizing
SCORE_WEIGHT_ACTIVITY = 0.20     # 20% — trading activity

# --- Account Score Breakpoints (account value → sub-score) ---
ACCOUNT_SCORE_BREAKPOINTS = [
    (100_000_000, 100),   # $100M+  → 100
    (50_000_000,   90),   # $50M+   → 90
    (10_000_000,   70),   # $10M+   → 70
    (5_000_000,    50),   # $5M+    → 50
    (1_000_000,    30),   # $1M+    → 30
]
# Below $1M → linear interpolation 0-20

# --- Position Score Breakpoints (total notional → sub-score) ---
POSITION_SCORE_BREAKPOINTS = [
    (50_000_000, 100),    # $50M+   → 100
    (20_000_000,  85),    # $20M+   → 85
    (10_000_000,  70),    # $10M+   → 70
    (5_000_000,   50),    # $5M+    → 50
    (1_000_000,   30),    # $1M+    → 30
]
# Below $1M → linear interpolation 0-20

# --- Activity Score Breakpoints (trade count in 30d → sub-score) ---
ACTIVITY_SCORE_BREAKPOINTS = [
    (100, 100),           # 100+ trades → 100
    (50,   75),           # 50+ trades  → 75
    (20,   50),           # 20+ trades  → 50
    (10,   30),           # 10+ trades  → 30
    (1,    15),           # 1-9 trades  → 15
]
# 0 trades → 0 (dormant)

# Recency bonus (added to activity sub-score, capped at 100)
RECENCY_BONUS_24H = 10           # last trade < 24 hours ago
RECENCY_BONUS_7D = 5             # last trade < 7 days ago

# --- Tier Cutoffs (composite score → tier) ---
TIER_CUTOFF_APEX = 75            # 75+  → APEX
TIER_CUTOFF_WHALE = 55           # 55-74 → WHALE
TIER_CUTOFF_SHARK = 35           # 35-54 → SHARK
TIER_CUTOFF_DOLPHIN = 20         # 20-34 → DOLPHIN
                                 # <20   → SKIP

# --- Hard Rules (override score-based classification) ---
DORMANT_WHALE_THRESHOLD = 50_000_000   # $50M+ with no activity → DORMANT_WHALE
MIN_ACCOUNT_VALUE = 1_000_000          # Below $1M → auto-SKIP (not worth tracking)

# ---------------------------------------------------------------------------
# Change Detection Defaults
# ---------------------------------------------------------------------------
DEFAULT_MIN_POSITION_CHANGE_PCT = 10.0       # % change to trigger event
DEFAULT_MIN_NOTIONAL_FOR_ALERT = 50_000      # $50K minimum notional

# ---------------------------------------------------------------------------
# Anomaly Detection Defaults
# ---------------------------------------------------------------------------
DEFAULT_ANOMALY_SIGMA = 2.5                  # σ threshold for anomaly
DEFAULT_BASELINE_WINDOW_DAYS = 14            # rolling window for baseline

# ---------------------------------------------------------------------------
# Correlation Analysis Defaults
# ---------------------------------------------------------------------------
DEFAULT_CORRELATION_THRESHOLD = 0.7          # r threshold for "linked"
DEFAULT_CORRELATION_WINDOW_DAYS = 14         # window for correlation calc

# ---------------------------------------------------------------------------
# Polling Defaults
# ---------------------------------------------------------------------------
DEFAULT_POLL_INTERVAL_TOP = 30               # seconds — top whales
DEFAULT_POLL_INTERVAL_OTHER = 60             # seconds — other whales
TOP_WHALE_COUNT = 20                         # how many are "top"
