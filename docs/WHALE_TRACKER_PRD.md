# 🐋 HyperWhale — Whale Behavior Analytics Engine

> **Project Name:** HyperWhale  
> **Author:** Sahil  
> **Date:** February 12, 2026  
> **Status:** Planning Phase  
> **Philosophy:** Deliver verifiable facts, not predictions. Let users make their own decisions.

---

## 1. Executive Summary

**What are we building?**  
A Python-based analytics engine that **tracks large traders ("whales") on Hyperliquid** and uses data science techniques — **anomaly detection, clustering, and correlation analysis** — to surface **factual, verifiable insights** about whale behavior.

**What we are NOT building:**  
We are NOT building a price predictor. We don't tell you *what will happen* — we tell you *what IS happening* and *what's unusual about it*. Users decide what to do with that information.

**Why this approach?**

| ❌ Prediction Approach | ✅ Our Analytics Approach |
|------------------------|--------------------------|
| "ETH will go up 5%" → probably wrong, loses trust | "3 whale clusters just converged on ETH for the first time in 2 months" → verifiable fact |
| Requires labeled data that doesn't exist (intent is subjective) | Unsupervised methods — no labeling needed |
| Overfits to noise, fails in new market regimes | Statistical facts hold across regimes |
| Competing with billion-dollar quant firms | Nobody else is doing this on Hyperliquid |

**Why is this different from HyperDash?**  

| Aspect | HyperDash | HyperWhale (Ours) |
|--------|-----------|-------------------|
| **Focus** | General trading terminal for all users | Deep analytics on whale behavior patterns |
| **Approach** | Shows raw data (positions, trades, order book) | Applies anomaly detection, clustering, and statistical analysis |
| **Output** | Visual dashboard (charts, tables) | Factual insights + alerts ("this is unusual", "these wallets are linked") |
| **Value** | "Whale tier is Slightly Bullish" | "Whale X just deviated 3σ from their normal behavior. Wallets A, B, C are 92% correlated — likely same entity" |

---

## 1.1 Competitive Analysis: HyperDash Cohorts

HyperDash already has a **Cohorts** feature (e.g., `hyperdash.com/explore/cohorts/apex`) that does wallet-tier analysis. We must understand exactly what it does and build **beyond** it.

### What HyperDash Cohorts Already Does:

| Feature | How It Works |
|---------|-------------|
| **Wallet Tiers** | Divides wallets by account size into: **Apex** → **Mega** → **Whale** → **Dolphin** → **Fish** → **Shrimp** |
| **Cohort Sentiment** | Shows overall sentiment per tier (e.g., Whale tier = "Slightly Bullish") |
| **Long/Short Ratio** | Aggregated notional: e.g., $429.5M Long / $423.67M Short (50/50) |
| **Profit Distribution** | % of wallets in profit vs loss (e.g., 55.1% in profit) |
| **Per-Coin Sentiment** | Per token: BTC = "Bullish", ETH = "Bit Bearish", SOL = "Bit Bearish", HYPE = "Bearish" |
| **Per-Coin UPNL** | Unrealized PnL per coin (e.g., BTC +$4.5M, SOL +$14.32M) |
| **Wallet Count** | Number of wallets in the cohort (e.g., 285 wallets, 234 markets) |
| **Sentiment Scale** | Ext Bullish → Very Bullish → Bullish → Slightly Bullish → Neutral → Bit Bearish → Bearish → Very Bearish → Ext Bearish |

### What HyperDash Cohorts Does NOT Do (Our Opportunity):

| Gap in HyperDash | What We Build | Type of Analysis |
|-------------------|--------------|------------------|
| ❌ **Static snapshot** — current state only | ✅ **Sentiment time-series** — how did sentiment change over 1h/4h/24h/7d? | Time-series tracking |
| ❌ **No individual whale tracking** | ✅ **Individual whale profiles** — each whale's behavior history | Data engineering |
| ❌ **No unusual behavior detection** | ✅ **Anomaly detection** — "This whale just did something they've NEVER done before" | Unsupervised ML |
| ❌ **No trader grouping by behavior** | ✅ **Behavior clustering** — automatically group whales by trading style | Unsupervised ML |
| ❌ **No wallet linking** | ✅ **Correlation analysis** — find wallets that move together (same entity? copy-trading?) | Statistical analysis |
| ❌ **No alerts** — manual dashboard checking | ✅ **Real-time Telegram alerts** for anomalies and significant shifts | Alerting |
| ❌ **No cross-cohort divergence** | ✅ **Smart money divergence** — when whales and retail are on opposite sides | Statistical analysis |
| ❌ **No trade-level granularity** | ✅ **Trade pattern analysis** — limit vs market orders, scaling patterns | Pattern analysis |
| ❌ **No historical context** | ✅ **Historical statistics** — "When whale long ratio exceeded 70%, here's what the distribution looked like" | Backtesting / stats |

### Our Positioning:

```
HyperDash Cohorts  = "What are whales holding RIGHT NOW?"
HyperWhale         = "What's UNUSUAL, who's CONNECTED, and what does HISTORY show?"
```

We don't compete with HyperDash — we build the **intelligence layer on top** of the same raw data.

---

## 2. Problem Statement

Retail traders on Hyperliquid lack the ability to:
1. **Detect** when a whale does something unusual (anomaly detection)
2. **Understand** how whales cluster into different trading styles (clustering)
3. **Discover** which wallets are linked or coordinated (correlation analysis)
4. **Track** how cohort sentiment shifts over time (time-series analytics)
5. **React** quickly when significant changes happen (real-time alerts)

Every answer we provide is **factual and verifiable** — not a prediction.

---

## 3. Data Sources (Hyperliquid API)

All data comes from Hyperliquid's **public Info API** (`POST https://api.hyperliquid.xyz/info`).  
**No API key is needed for read-only data.** No private keys required.

### 3.1 Primary Data Endpoints We'll Use

| # | Endpoint | Request Type | What It Gives Us | Use Case |
|---|----------|-------------|------------------|----------|
| 1 | **User's Perpetuals Account Summary** | `{"type": "clearinghouseState", "user": "0x..."}` | Open positions, leverage, margin, liquidation price, unrealized PnL | Core whale position tracking |
| 2 | **User's Fills** | `{"type": "userFills", "user": "0x..."}` | Trade history (coin, price, size, side, direction, timestamp) | Trading pattern analysis |
| 3 | **User's Fills by Time** | `{"type": "userFillsByTime", "user": "0x...", "startTime": ...}` | Same as above but with time range filtering | Historical pattern building |
| 4 | **User's Historical Orders** | `{"type": "historicalOrders", "user": "0x..."}` | Order history including cancelled/rejected orders | Behavioral pattern analysis |
| 5 | **User's Open Orders** | `{"type": "openOrders", "user": "0x..."}` | Current limit orders waiting to be filled | Current intent signals |
| 6 | **Perpetuals Asset Contexts** | `{"type": "metaAndAssetCtxs"}` | Mark price, funding rate, open interest, 24h volume for all coins | Market context |
| 7 | **L2 Book Snapshot** | `{"type": "l2Book", "coin": "BTC"}` | Order book depth (20 levels per side) | Detect large orders in the book |
| 8 | **Candle Snapshot** | `{"type": "candleSnapshot", "coin": "BTC", "interval": "1h", ...}` | OHLCV data | Price context for position analysis |
| 9 | **Funding Rate History** | `{"type": "fundingHistory", "coin": "BTC", ...}` | Historical funding rates | Market context |
| 10 | **User's Portfolio** | `{"type": "portfolio", "user": "0x..."}` | Account value history, PnL history over time | Whale performance tracking |
| 11 | **Vault Details** | `{"type": "vaultDetails", "vaultAddress": "0x..."}` | Vault followers, AUM, PnL, leader info | Identify whale-run vaults |

### 3.2 Data We Need to Build Ourselves

| Data | Source | Method |
|------|--------|--------|
| **Whale Address List** | Hyperliquid leaderboard, community lists, large trade monitoring | Curate top trader addresses |
| **Historical Position Snapshots** | Polling `clearinghouseState` periodically | Our own database (SQLite → PostgreSQL) |
| **Behavioral Baselines** | Accumulated data over time | Statistical profiles built automatically (no manual labeling!) |

### 3.3 API Rate Limits

- Hyperliquid uses a **weight-based rate limiting** system
- Each request has a weight (typically 1-2)
- Rate limit is tied to your trading volume (higher volume = more requests)
- For read-only analytics: we need to be smart about polling frequency
- **Strategy:** Poll top 50 whales every 30-60 seconds, batch requests

---

## 4. Feature Breakdown

### Phase 1: Whale Tracker (Weeks 1-2) — Data Foundation

**Goal:** Identify and continuously monitor the top traders on Hyperliquid. Build the data foundation everything else depends on.

#### Features:
1. **Whale Discovery Module**
   - Curate a list of top 50-100 whale addresses
   - Sources: Hyperliquid leaderboard, known vault leaders, community-shared addresses
   - Score whales by: account value, trade volume, PnL track record

2. **Position Monitor**
   - Poll each whale's `clearinghouseState` every 30-60 seconds
   - Store snapshots in a local database (SQLite for dev, PostgreSQL for prod)
   - Track: which coins, position size, leverage, entry price, liquidation price, unrealized PnL

3. **Trade Feed**
   - Pull each whale's recent fills using `userFillsByTime`
   - Detect new trades in real-time (compare with last known state)
   - Categorize: Open Long, Open Short, Close Long, Close Short, Increase, Decrease

4. **Change Detection Engine**
   - Compare consecutive snapshots to detect:
     - New position opened
     - Position size increased/decreased by >10%
     - Position closed
     - Leverage changed
     - New coin added to portfolio
   - Generate structured "events" from raw data

5. **Cohort Sentiment Time-Series**
   - Group tracked wallets into tiers (like HyperDash: by account size)
   - Compute long/short ratio, profit/loss distribution per cohort per snapshot
   - Store as time-series → enables "sentiment shifted from bearish to bullish over the past 4h"

#### Deliverables:
- `data/collector.py` — Pulls data from Hyperliquid API
- `data/whale_registry.py` — Manages the list of tracked whales
- `data/database.py` — SQLite storage layer
- `models.py` — Data models (WhaleProfile, Position, Trade, PositionEvent)
- `tracker/position_monitor.py` — Continuous position tracking loop
- `tracker/trade_feed.py` — Trade detection and processing
- `tracker/change_detector.py` — Detects meaningful position changes
- `tracker/cohort_tracker.py` — Cohort-level sentiment time-series

---

### Phase 2: Analytics Engine (Weeks 3-5) — The Data Science Layer

**Goal:** Apply unsupervised ML and statistical analysis to surface **factual, verifiable insights**. No labeled data needed. No predictions.

#### 2A. Anomaly Detection 🔍

**Question answered:** *"Is this whale doing something unusual compared to their own history?"*

**Approach:**
- Build a **behavioral baseline** for each whale using their historical data (rolling 7-30 day window)
- For each new action, compute how far it deviates from the baseline
- Flag actions that are >2σ (unusual) or >3σ (highly unusual) from the norm

**What we measure per whale:**

| Metric | Baseline | Anomaly Example |
|--------|----------|-----------------|
| **Average position size** | Usually trades $50K-$200K | Suddenly opens a $2M position |
| **Typical leverage** | Usually 3-5x | Just used 20x leverage |
| **Trading frequency** | 2-3 trades per day | Made 15 trades in the last hour |
| **Coins traded** | Usually BTC, ETH only | Just opened a position in a micro-cap |
| **Direction bias** | Usually 70% long | Just went 100% short |
| **Order type** | Usually limit orders | Suddenly using all market orders (urgency signal) |
| **Time of day** | Usually trades during US hours | Trading at 3 AM for the first time |

**Method:** Isolation Forest + Z-score on rolling statistics
- No labels needed — purely based on each whale's own history
- Every alert includes: "This is X standard deviations from their average behavior"
- **Verifiable:** anyone can check the whale's history and confirm

**Output example:**
> 🔍 **ANOMALY DETECTED — Whale 0xABC**  
> Position size: $1.8M (usual range: $50K-$200K) — **3.2σ above normal**  
> Leverage: 15x (usual: 3-5x) — **2.8σ above normal**  
> This whale has NEVER used more than 7x leverage in 47 days of tracking.

#### 2B. Whale Clustering 🎯

**Question answered:** *"What types of traders exist on Hyperliquid, and which type is each whale?"*

**Approach:**
- Extract behavioral features for each whale (over their full history)
- Apply clustering algorithms to automatically discover trader archetypes
- No manual labeling — the algorithm finds natural groupings

**Features for clustering (per whale, aggregated):**

| Feature | Description |
|---------|-------------|
| `avg_hold_time` | How long they typically hold a position |
| `trade_frequency` | How often they trade (trades per day) |
| `avg_leverage` | Typical leverage used |
| `avg_position_size_pct` | Position size as % of account |
| `win_rate` | % of trades that are profitable |
| `num_coins_traded` | How many different coins they trade |
| `concentration_ratio` | % of portfolio in top 1-2 coins |
| `limit_vs_market_ratio` | Patient (limit) vs urgent (market) order usage |
| `direction_bias` | Net long vs short tendency |
| `avg_pnl_per_trade` | Average profit/loss per trade |
| `max_drawdown` | Largest peak-to-trough decline |
| `trading_hours_entropy` | How spread out are their trading times |

**Method:** K-Means / DBSCAN / Gaussian Mixture Models
- Start with K-Means, use elbow method + silhouette score to find optimal K
- Expect to find 4-7 natural clusters (e.g., "patient accumulators", "high-frequency scalpers", "leveraged trend followers", etc.)
- Name clusters based on their centroid characteristics

**Output example:**
> 🎯 **WHALE CLUSTERS (auto-discovered)**  
> **Cluster 1 — "Patient Giants"** (23 whales): Low leverage (2-3x), long hold times (3-7 days), mostly limit orders, high win rate  
> **Cluster 2 — "Degen Snipers"** (18 whales): High leverage (10-25x), short hold times (<1h), market orders, low win rate but big winners  
> **Cluster 3 — "Steady Grinders"** (31 whales): Medium leverage (5x), 5-15 trades/day, mixed order types, consistent small PnL  
> **Cluster 4 — "Macro Whales"** (8 whales): Huge positions ($1M+), very infrequent (1-2 trades/week), strong directional bias  

#### 2C. Correlation & Network Analysis 🔗

**Question answered:** *"Which wallets move together? Who's likely the same entity? Who follows whom?"*

**Approach:**
- For each pair of whales, compute **correlation** of their trading actions over time
- Build a **network graph** where edges represent correlation strength
- Detect **communities** (groups of linked wallets)

**What we correlate:**

| Correlation Type | Method | What It Reveals |
|-----------------|--------|-----------------|
| **Position correlation** | Pearson correlation of position changes over time | Wallets that increase/decrease positions together |
| **Timing correlation** | Cross-correlation of trade timestamps | Wallets that trade within seconds/minutes of each other |
| **Coin overlap** | Jaccard similarity of coins traded | Wallets that trade the same tokens |
| **Direction alignment** | % of time both wallets are on the same side | Wallets with consistent directional agreement |
| **Leader-follower detection** | Granger causality / lagged cross-correlation | Wallet A trades → Wallet B trades 5 min later (who's copying whom?) |

**Method:**
- Pairwise Pearson/Spearman correlation on position time-series
- Time-lagged cross-correlation for leader-follower detection
- Community detection (Louvain algorithm) on the correlation graph
- **Threshold:** r > 0.7 = "likely connected", r > 0.85 = "almost certainly same entity or copy-trading"

**Output example:**
> 🔗 **CORRELATED WALLETS DETECTED**  
> Wallets 0xABC, 0xDEF, 0x123 have r=0.92 correlation over the past 14 days  
> — They traded the same coin within 30 seconds of each other 87% of the time  
> — 0xABC appears to be the **leader** (trades first by avg 45 seconds)  
> — Combined notional: $12.3M — effectively a single $12.3M whale  

#### 2D. Cohort Divergence Analysis 📊

**Question answered:** *"Are whales and retail on opposite sides? How does sentiment compare across tiers?"*

**Approach:**
- Compute long/short ratio per cohort tier (Apex, Whale, Fish, Shrimp)
- Track divergences: when one tier is very long and another is very short
- Report as factual observation with historical context

**Method:** Simple arithmetic on aggregated positions + Z-score on historical divergence

**Output example:**
> 📊 **COHORT DIVERGENCE ALERT**  
> Apex tier: 78% long on ETH ($45M notional)  
> Fish tier: 62% short on ETH ($8M notional)  
> **Divergence score: 2.4σ** — This level of disagreement between tiers has occurred 7 times in the past 90 days  
> Historical context: Here is the distribution of 7-day returns following those 7 instances: mean +4.2%, median +3.1%, std 6.1%  
> *(Note: 7 samples is too small for statistical significance — presented as context only)*

---

#### Deliverables:
- `analytics/anomaly_detector.py` — Behavioral anomaly detection per whale
- `analytics/clustering.py` — Whale behavior clustering (K-Means, DBSCAN)
- `analytics/correlation.py` — Pairwise wallet correlation analysis
- `analytics/network.py` — Network graph and community detection
- `analytics/cohort_divergence.py` — Cross-tier sentiment divergence
- `analytics/feature_builder.py` — Feature extraction for clustering
- `analytics/statistics.py` — Historical statistical summaries

---

### Phase 3: Alerts & Interface (Week 6) — Delivery Layer

**Goal:** Deliver factual insights to users in real-time.

#### Features:
1. **Telegram Bot**
   - Real-time alerts for:
     - 🔍 Anomalies — whale deviates from their baseline
     - 🔗 New correlations discovered — wallets start moving together
     - 📊 Cohort divergence — tiers disagree significantly
     - 🐋 Large position changes — whale opens/closes >$500K position
   - Format: factual, includes context, never says "buy" or "sell"

2. **CLI Dashboard**
   - Terminal-based dashboard (using `rich`) showing:
     - All tracked whales and current positions
     - Cluster membership for each whale
     - Active anomalies
     - Cohort sentiment breakdown

3. **Data Export**
   - CSV/JSON export of whale activity history
   - Correlation matrices, cluster assignments
   - Historical cohort sentiment data

#### Deliverables:
- `alerts/telegram_bot.py` — Telegram bot for real-time alerts
- `alerts/formatter.py` — Format alerts into readable messages
- `dashboard/cli.py` — Terminal dashboard (using `rich` library)

---

## 5. Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| **Language** | Python 3.10+ | Best for data science + good Hyperliquid SDK |
| **Hyperliquid SDK** | `hyperliquid-python-sdk` | Official SDK, well-maintained |
| **HTTP Client** | `httpx` | Async-capable HTTP client for API calls |
| **Database** | SQLite (dev) → PostgreSQL (prod) | Simple start, scale later |
| **ORM** | SQLAlchemy | Database abstraction |
| **Data Processing** | pandas, numpy | Feature engineering, statistics |
| **Anomaly Detection** | scikit-learn (Isolation Forest, Z-score) | Unsupervised anomaly detection |
| **Clustering** | scikit-learn (K-Means, DBSCAN, GMM) | Unsupervised trader grouping |
| **Network Analysis** | networkx | Correlation graphs, community detection |
| **Visualization** | matplotlib, plotly | Charts for analysis in notebooks |
| **CLI Dashboard** | `rich` | Beautiful terminal output |
| **Telegram Bot** | `python-telegram-bot` | Alert delivery |
| **Task Scheduling** | `APScheduler` | Periodic data collection |
| **Config** | `pydantic-settings` | Type-safe configuration |
| **Logging** | `loguru` | Better logging |

---

## 6. Project Structure

```
HyperLiquid/
├── docs/
│   └── WHALE_TRACKER_PRD.md          ← You are here
│
├── src/
│   └── hyperwhale/
│       ├── __init__.py
│       ├── config.py                  # Configuration management
│       ├── constants.py               # API URLs, thresholds
│       ├── models.py                  # Data models (Pydantic)
│       │
│       ├── data/                      # --- DATA LAYER ---
│       │   ├── __init__.py
│       │   ├── collector.py           # Hyperliquid API data collection
│       │   ├── database.py            # Database operations (SQLite)
│       │   └── whale_registry.py      # Whale address management
│       │
│       ├── tracker/                   # --- TRACKING LAYER ---
│       │   ├── __init__.py
│       │   ├── position_monitor.py    # Continuous position monitoring
│       │   ├── trade_feed.py          # Trade detection and processing
│       │   ├── change_detector.py     # Position change detection
│       │   └── cohort_tracker.py      # Cohort sentiment time-series
│       │
│       ├── analytics/                 # --- ANALYTICS LAYER ---
│       │   ├── __init__.py
│       │   ├── feature_builder.py     # Extract behavioral features per whale
│       │   ├── anomaly_detector.py    # Detect unusual whale behavior
│       │   ├── clustering.py          # Cluster whales by trading style
│       │   ├── correlation.py         # Pairwise wallet correlation
│       │   ├── network.py             # Network graph + community detection
│       │   ├── cohort_divergence.py   # Cross-tier divergence signals
│       │   └── statistics.py          # Historical statistical summaries
│       │
│       ├── alerts/                    # --- DELIVERY LAYER ---
│       │   ├── __init__.py
│       │   ├── telegram_bot.py        # Telegram notifications
│       │   └── formatter.py           # Message formatting
│       │
│       └── dashboard/
│           ├── __init__.py
│           └── cli.py                 # Terminal dashboard (rich)
│
├── notebooks/
│   ├── 01_data_exploration.ipynb      # Explore Hyperliquid API data
│   ├── 02_anomaly_detection.ipynb     # Develop anomaly detection
│   ├── 03_clustering.ipynb            # Whale clustering experiments
│   └── 04_correlation_analysis.ipynb  # Wallet correlation & networks
│
├── tests/
│   ├── test_collector.py
│   ├── test_change_detector.py
│   ├── test_anomaly_detector.py
│   └── test_clustering.py
│
├── data/
│   └── whale_addresses.json           # Curated whale list
│
├── requirements.txt
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

---

## 7. Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    HYPERLIQUID API                           │
│  (positions, trades, orders, market data — all public)      │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│              DATA COLLECTOR (every 30-60s)                   │
│  • Poll whale positions (clearinghouseState)                │
│  • Pull recent trades (userFillsByTime)                     │
│  • Fetch market context (metaAndAssetCtxs)                  │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│              DATABASE (SQLite → PostgreSQL)                   │
│  • Position snapshots (time series)                          │
│  • Trade history                                             │
│  • Market data cache                                         │
│  • Behavioral baselines (auto-computed)                      │
└─────────────────┬───────────────────────────────────────────┘
                  │
    ┌─────────────┼──────────────┬──────────────┐
    ▼             ▼              ▼              ▼
┌────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────┐
│ CHANGE │ │ ANOMALY  │ │ CLUSTERING │ │ CORRELATION  │
│DETECTOR│ │ DETECTOR │ │            │ │ & NETWORK    │
│        │ │          │ │            │ │              │
│• New   │ │• Z-score │ │• K-Means   │ │• Pairwise r  │
│  pos   │ │• Isolat° │ │• DBSCAN    │ │• Lead-follow │
│• Size Δ│ │  Forest  │ │• Auto-name │ │• Communities │
│• Close │ │• vs own  │ │  clusters  │ │• Linked      │
│• Lever │ │  history │ │            │ │  wallets     │
└───┬────┘ └────┬─────┘ └─────┬──────┘ └──────┬───────┘
    │           │             │                │
    ▼           ▼             ▼                ▼
┌─────────────────────────────────────────────────────────────┐
│                   ALERT ENGINE                               │
│  • Filter by significance (>2σ for anomalies, r>0.7, etc)   │
│  • Format as FACTUAL statements (never predictions)          │
│  • Include context: "this happened N times before"           │
└─────────────────┬───────────────────────────────────────────┘
                  │
          ┌───────┼────────┐
          ▼       ▼        ▼
      Telegram   CLI     CSV/JSON
       Bot     Dashboard  Export
```

---

## 8. Milestones & Timeline

| Week | Milestone | Key Deliverables | Success Criteria |
|------|-----------|-----------------|------------------|
| **1** | 🔧 **Project Setup + Data Collection** | Project structure, API connection, basic data pulling, database | Can pull positions for 10+ whales and store in SQLite |
| **2** | 📊 **Position Monitoring + Change Detection** | Continuous monitoring loop, change events, cohort tracking | Detect when a whale opens/closes/changes a position within 60s |
| **3** | 🔍 **Anomaly Detection** | Behavioral baselines, Z-score + Isolation Forest anomaly detection | Flag unusual behavior with σ-score, verified on 5+ real examples |
| **4** | 🎯 **Whale Clustering** | Feature extraction, K-Means/DBSCAN clustering, cluster profiling | Discover 4-7 natural trader archetypes with clear characteristics |
| **5** | 🔗 **Correlation & Network Analysis** | Pairwise correlation, leader-follower detection, community discovery | Identify 3+ groups of correlated wallets with r > 0.7 |
| **6** | 📱 **Alerts + Dashboard** | Telegram bot, CLI dashboard, data export | End-to-end: whale anomaly → factual alert in <2 minutes |

---

## 9. Key Decisions to Make

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| 1 | **How to get whale addresses?** | a) Scrape leaderboard b) Community lists c) Monitor large trades | Start with (c) — find addresses that trade >$100K in a single trade |
| 2 | **Polling frequency** | 15s / 30s / 60s / 5min | 30s for top 20 whales, 60s for the rest |
| 3 | **Database** | SQLite / PostgreSQL / MongoDB | SQLite for now — migrate to PostgreSQL when needed |
| 4 | **Anomaly threshold** | 2σ / 2.5σ / 3σ | 2.5σ — good balance of sensitivity vs false alarms |
| 5 | **Clustering algorithm** | K-Means / DBSCAN / GMM | Start with K-Means (simple), try DBSCAN later (handles outliers) |
| 6 | **Correlation window** | 3 days / 7 days / 14 days / 30 days | 14 days — long enough for signal, short enough to catch changes |
| 7 | **Alert channel** | Telegram / Discord / Email | Telegram first — most popular in crypto |
| 8 | **How many whales to track?** | 20 / 50 / 100 / 200 | Start with 50, scale to 100+ |

---

## 10. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **Rate limiting** | Can't poll enough whales frequently | Medium | Batch requests, stagger polling, cache aggressively |
| **Whale uses multiple wallets** | Split behavior across wallets | High | Correlation analysis will help discover linked wallets! |
| **Not enough data for clustering** | Clusters are noisy or meaningless | Medium | Wait for 2+ weeks of data before running clustering |
| **Anomaly baselines too short** | Too many false positives initially | Medium | Start with conservative 3σ threshold, reduce over time |
| **Correlated wallets = coincidence** | False positive on wallet linking | Medium | Require high r (>0.8) + timing correlation + minimum sample size |
| **API changes** | Breaking changes in endpoints | Low | Pin SDK version, add error handling |

---

## 11. Success Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| **Whales tracked** | 50+ | Count of active whale profiles |
| **Detection latency** | <60 seconds | Time from whale action to our detection |
| **Anomaly precision** | >80% | Manual review: are flagged anomalies genuinely unusual? |
| **Clusters discovered** | 4-7 meaningful types | Silhouette score >0.4, clusters are interpretable |
| **Correlated pairs found** | 10+ with r>0.7 | Count of verified correlated wallet pairs |
| **Alert delivery time** | <2 minutes | End-to-end from event to Telegram message |
| **Uptime** | >95% | Monitoring of data collection pipeline |
| **All outputs verifiable** | 100% | Every insight can be independently checked |

---

## 12. What We Explicitly Do NOT Build

To stay focused and honest, we commit to NOT building:

| ❌ Not Building | Why |
|----------------|-----|
| Price predictions | Everyone tries, nobody succeeds reliably. We'd be competing with billion-dollar quant firms. |
| Buy/sell signals | We provide information, not financial advice. Users make their own decisions. |
| Intent classification (supervised ML) | Intent is subjective — no ground truth exists. Unsupervised methods are more honest. |
| Backtested "strategies" | Backtests overfit. We report historical statistics with proper caveats. |
| Confidence scores on predictions | We don't predict, so there's nothing to score. We report σ-scores on anomalies instead — those are factual. |

---

## 13. Getting Started (Next Steps)

1. ✅ Read and finalize this document
2. ⬜ Set up the Python project structure
3. ⬜ Install dependencies (`hyperliquid-python-sdk`, `pandas`, `scikit-learn`, `networkx`, etc.)
4. ⬜ Write the first data collection script — pull one whale's position data
5. ⬜ Explore the data in a Jupyter notebook
6. ⬜ Build the position monitoring loop
7. ⬜ Implement change detection
8. ⬜ Build behavioral baselines → anomaly detection
9. ⬜ Run clustering on accumulated data
10. ⬜ Compute wallet correlations and build network graph
11. ⬜ Set up Telegram alerts

---

*This is a living document. Update it as we learn more and make decisions.*
