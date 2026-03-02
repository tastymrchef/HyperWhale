# 🐋 HyperWhale — Whale Behavior Analytics Engine

> **Track whales. Detect anomalies. Discover connections. No predictions — just facts.**

HyperWhale is a Python-based analytics engine that monitors large traders ("whales") on [Hyperliquid](https://hyperliquid.xyz) and surfaces **factual, verifiable insights** using anomaly detection, clustering, and correlation analysis.

## What It Does

| Module | Description |
|--------|-------------|
| 🐋 **Whale Tracker** | Continuously monitor 50+ whale wallets — positions, trades, leverage |
| 🔍 **Anomaly Detection** | Flag when a whale deviates from their historical behavior (Z-score + Isolation Forest) |
| 🎯 **Clustering** | Automatically group whales by trading style (K-Means / DBSCAN) |
| 🔗 **Correlation & Network** | Find wallets that move together — same entity? Copy-trading? |
| 📊 **Cohort Divergence** | Track when whales and retail are on opposite sides |
| 📱 **Telegram Alerts** | Real-time alerts for anomalies and significant changes |

## What It Does NOT Do

- ❌ Price predictions
- ❌ Buy/sell signals
- ❌ Trading advice

Every output is a **verifiable fact**, not a guess. Users make their own decisions.

## Quick Start

```bash
# 1. Clone and enter the project
cd HyperLiquid

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and configure environment
copy .env.example .env

# 5. Run data collection (pulls whale data from Hyperliquid)
python -m hyperwhale.data.collector

# 6. Run the CLI dashboard
python -m hyperwhale.dashboard.cli
```

## Project Structure

```
src/hyperwhale/
├── config.py              # Configuration management
├── constants.py           # API URLs, thresholds
├── models.py              # Pydantic data models
├── data/                  # Data layer (API, DB, whale list)
├── tracker/               # Tracking layer (positions, trades, changes)
├── analytics/             # Analytics layer (anomaly, clustering, correlation)
├── alerts/                # Delivery layer (Telegram, formatting)
└── dashboard/             # CLI dashboard (rich)
```

## Data Sources

All data comes from Hyperliquid's **public API** — no API keys or private keys needed for read-only analytics.

## Docs

See [docs/WHALE_TRACKER_PRD.md](docs/WHALE_TRACKER_PRD.md) for the full project planning document.

## License

MIT
