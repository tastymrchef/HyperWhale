"""
store_snapshot.py  --  persist a snapshot JSON into the SQLite history database.

Schema
------
snapshots       : one row per fetch run
wallet_states   : one row per wallet per run
positions       : one row per position per wallet per run

Usage
-----
    .venv/Scripts/python.exe scripts/store_snapshot.py
    .venv/Scripts/python.exe scripts/store_snapshot.py --snapshot data/live_positions_snapshot.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT          = Path(__file__).resolve().parent.parent
DEFAULT_SNAP  = ROOT / "data" / "live_positions_snapshot.json"
DB_PATH       = ROOT / "data" / "hyperwhale.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at    TEXT NOT NULL,
    total_wallets INTEGER NOT NULL,
    errors        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS wallet_states (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id),
    fetched_at    TEXT NOT NULL,
    address       TEXT NOT NULL,
    label         TEXT,
    tier          TEXT,
    whale_score   REAL,
    account_value REAL
);

CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_state_id INTEGER NOT NULL REFERENCES wallet_states(id),
    snapshot_id     INTEGER NOT NULL,
    fetched_at      TEXT NOT NULL,
    address         TEXT NOT NULL,
    coin            TEXT NOT NULL,
    side            TEXT NOT NULL,
    notional        REAL,
    upnl            REAL,
    entry           REAL,
    liq             TEXT,
    leverage        REAL,
    leverage_type   TEXT NOT NULL DEFAULT 'cross'   -- 'cross' or 'isolated'
);

CREATE INDEX IF NOT EXISTS idx_wallet_states_address    ON wallet_states(address);
CREATE INDEX IF NOT EXISTS idx_wallet_states_snapshot   ON wallet_states(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_wallet_states_fetched    ON wallet_states(fetched_at);
CREATE INDEX IF NOT EXISTS idx_positions_address        ON positions(address);
CREATE INDEX IF NOT EXISTS idx_positions_snapshot       ON positions(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_positions_coin           ON positions(coin);

-- Per-coin long/short bias snapshot (all tiers + smart money = apex+whale)
CREATE TABLE IF NOT EXISTS coin_bias (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id      INTEGER NOT NULL REFERENCES snapshots(id),
    fetched_at       TEXT NOT NULL,
    coin             TEXT NOT NULL,

    -- ALL tracked wallets aggregate
    long_notional    REAL NOT NULL DEFAULT 0,
    short_notional   REAL NOT NULL DEFAULT 0,
    long_pct         REAL NOT NULL DEFAULT 0,   -- 0-100
    wallet_count     INTEGER NOT NULL DEFAULT 0,

    -- Smart money only (apex + whale tiers)
    sm_long_notional  REAL NOT NULL DEFAULT 0,
    sm_short_notional REAL NOT NULL DEFAULT 0,
    sm_long_pct       REAL NOT NULL DEFAULT 0,  -- 0-100  (NULL if no SM in coin)
    sm_wallet_count   INTEGER NOT NULL DEFAULT 0,

    -- Price at snapshot time (from HL allMids)
    mark_price        REAL                       -- NULL for old backfilled rows
);

CREATE INDEX IF NOT EXISTS idx_coin_bias_snapshot ON coin_bias(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_coin_bias_coin     ON coin_bias(coin);
CREATE INDEX IF NOT EXISTS idx_coin_bias_fetched  ON coin_bias(fetched_at);

-- CEX top-trader long/short bias (Binance + Bybit), one row per coin per fetch
CREATE TABLE IF NOT EXISTS cex_bias (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at            TEXT NOT NULL,
    coin                  TEXT NOT NULL,
    mark_price            REAL,           -- Binance mark price at fetch time

    -- Binance top traders (big accounts)
    bn_top_long_pct       REAL,   -- NULL if fetch failed
    bn_all_long_pct       REAL,   -- global (all accounts)
    bn_funding_rate       REAL,
    bn_oi_usd             REAL,

    -- Bybit top traders
    by_top_long_pct       REAL,
    by_funding_rate       REAL,
    by_oi_usd             REAL
);

CREATE INDEX IF NOT EXISTS idx_cex_bias_coin    ON cex_bias(coin);
CREATE INDEX IF NOT EXISTS idx_cex_bias_fetched ON cex_bias(fetched_at);

-- Pre-computed baselines per wallet (rebuilt by anomaly detector later)
CREATE TABLE IF NOT EXISTS wallet_baselines (
    address           TEXT PRIMARY KEY,
    label             TEXT,
    tier              TEXT,
    updated_at        TEXT NOT NULL,
    snapshot_count    INTEGER NOT NULL DEFAULT 0,  -- how many snapshots used
    avg_account_value REAL,
    std_account_value REAL,
    avg_num_positions REAL,
    std_num_positions REAL,
    avg_total_notional REAL,
    std_total_notional REAL,
    avg_leverage      REAL,
    std_leverage      REAL,
    avg_long_pct      REAL,   -- 0-100, usual long bias %
    std_long_pct      REAL,
    usual_coins       TEXT    -- JSON array of coins this wallet normally trades
);
"""

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def store(snap_path: Path = DEFAULT_SNAP, db_path: Path = DB_PATH) -> None:
    snap = json.loads(snap_path.read_text(encoding="utf-8"))

    fetched_at    = snap.get("fetched_at", datetime.now(timezone.utc).isoformat())
    total_wallets = snap.get("total_wallets", 0)
    errors        = snap.get("errors", 0)
    wallets       = snap.get("wallets", [])
    prices        = snap.get("prices", {})

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(DDL)

    # Migrations — add columns that didn't exist in older schema (safe to re-run)
    for migration in [
        "ALTER TABLE coin_bias ADD COLUMN mark_price REAL",
        "ALTER TABLE cex_bias  ADD COLUMN mark_price REAL",
    ]:
        try:
            con.execute(migration)
        except sqlite3.OperationalError:
            pass  # column already exists — fine
    con.commit()

    # Check for duplicate (same fetched_at already stored)
    existing = con.execute(
        "SELECT id FROM snapshots WHERE fetched_at = ?", (fetched_at,)
    ).fetchone()
    if existing:
        print(f"[store_snapshot] Already stored snapshot for {fetched_at} — skipping.")
        con.close()
        return

    # Insert snapshot row
    cur = con.execute(
        "INSERT INTO snapshots(fetched_at, total_wallets, errors) VALUES (?,?,?)",
        (fetched_at, total_wallets, errors),
    )
    snapshot_id = cur.lastrowid

    wallet_rows  = 0
    position_rows = 0

    for w in wallets:
        addr  = w.get("address", "")
        label = w.get("label", "")
        tier  = w.get("tier", "")
        score = w.get("whale_score", 0)
        av    = w.get("account_value", 0)

        # Insert wallet_state row
        wc = con.execute(
            """INSERT INTO wallet_states
               (snapshot_id, fetched_at, address, label, tier, whale_score, account_value)
               VALUES (?,?,?,?,?,?,?)""",
            (snapshot_id, fetched_at, addr, label, tier, score, av),
        )
        wallet_state_id = wc.lastrowid
        wallet_rows += 1

        for p in w.get("positions", []):
            con.execute(
                """INSERT INTO positions
                   (wallet_state_id, snapshot_id, fetched_at, address,
                    coin, side, notional, upnl, entry, liq, leverage, leverage_type)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    wallet_state_id, snapshot_id, fetched_at, addr,
                    p.get("coin", ""),
                    p.get("side", ""),
                    p.get("notional", 0),
                    p.get("upnl", 0),
                    p.get("entry", 0),
                    str(p.get("liq", "")),
                    p.get("leverage", 1),
                    p.get("leverage_type", "cross"),
                ),
            )
            position_rows += 1

    # Compute and store per-coin bias
    coin_rows = store_coin_bias(snapshot_id, fetched_at, wallets, con, prices)

    con.commit()
    con.close()

    print(f"[store_snapshot] Stored snapshot {snapshot_id}  |  "
          f"{wallet_rows} wallets  |  {position_rows} positions  |  "
          f"{coin_rows} coin_bias rows  |  {fetched_at}")


# ---------------------------------------------------------------------------
# Per-coin bias aggregation
# ---------------------------------------------------------------------------

SMART_MONEY_TIERS = {"apex", "whale"}


def _compute_coin_bias(wallets: list) -> dict:
    """
    Aggregate per-coin long/short notional for:
      - all tiers combined
      - smart money only (apex + whale)

    Returns dict keyed by coin:
      {
        "BTC": {
          "long": float, "short": float, "wallets": int,
          "sm_long": float, "sm_short": float, "sm_wallets": int
        }, ...
      }
    """
    from collections import defaultdict
    coins: dict = defaultdict(lambda: {
        "long": 0.0, "short": 0.0, "wallets": 0,
        "sm_long": 0.0, "sm_short": 0.0, "sm_wallets": 0,
    })

    for w in wallets:
        tier = (w.get("tier") or "").lower()
        is_sm = tier in SMART_MONEY_TIERS
        positions = w.get("positions", [])
        if not positions:
            continue

        # Track which coins this wallet touched (for wallet_count per coin)
        touched: set = set()
        sm_touched: set = set()

        for p in positions:
            coin = p.get("coin", "")
            side = p.get("side", "")
            n = abs(p.get("notional") or 0)
            if not coin or not side or n == 0:
                continue

            if side == "long":
                coins[coin]["long"] += n
            elif side == "short":
                coins[coin]["short"] += n

            touched.add(coin)

            if is_sm:
                if side == "long":
                    coins[coin]["sm_long"] += n
                elif side == "short":
                    coins[coin]["sm_short"] += n
                sm_touched.add(coin)

        for coin in touched:
            coins[coin]["wallets"] += 1
        for coin in sm_touched:
            coins[coin]["sm_wallets"] += 1

    return dict(coins)


def store_coin_bias(
    snapshot_id: int,
    fetched_at: str,
    wallets: list,
    con: sqlite3.Connection,
    prices: dict | None = None,
) -> int:
    """Compute and insert coin_bias rows. Returns number of coins written."""
    bias = _compute_coin_bias(wallets)
    prices = prices or {}
    rows = []
    for coin, d in bias.items():
        tot    = d["long"] + d["short"]
        sm_tot = d["sm_long"] + d["sm_short"]
        long_pct    = round(d["long"]    / tot    * 100, 2) if tot    > 0 else 0.0
        sm_long_pct = round(d["sm_long"] / sm_tot * 100, 2) if sm_tot > 0 else 0.0
        mark_price  = prices.get(coin)
        rows.append((
            snapshot_id, fetched_at, coin,
            round(d["long"],  2), round(d["short"],  2), long_pct,    d["wallets"],
            round(d["sm_long"], 2), round(d["sm_short"], 2), sm_long_pct, d["sm_wallets"],
            mark_price,
        ))

    con.executemany(
        """INSERT INTO coin_bias
           (snapshot_id, fetched_at, coin,
            long_notional, short_notional, long_pct, wallet_count,
            sm_long_notional, sm_short_notional, sm_long_pct, sm_wallet_count,
            mark_price)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    return len(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Store snapshot into SQLite DB")
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAP))
    parser.add_argument("--db",       default=str(DB_PATH))
    args = parser.parse_args()
    store(Path(args.snapshot), Path(args.db))


if __name__ == "__main__":
    main()
