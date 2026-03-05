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
    leverage        REAL
);

CREATE INDEX IF NOT EXISTS idx_wallet_states_address    ON wallet_states(address);
CREATE INDEX IF NOT EXISTS idx_wallet_states_snapshot   ON wallet_states(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_wallet_states_fetched    ON wallet_states(fetched_at);
CREATE INDEX IF NOT EXISTS idx_positions_address        ON positions(address);
CREATE INDEX IF NOT EXISTS idx_positions_snapshot       ON positions(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_positions_coin           ON positions(coin);

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

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(DDL)

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
                    coin, side, notional, upnl, entry, liq, leverage)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    wallet_state_id, snapshot_id, fetched_at, addr,
                    p.get("coin", ""),
                    p.get("side", ""),
                    p.get("notional", 0),
                    p.get("upnl", 0),
                    p.get("entry", 0),
                    str(p.get("liq", "")),
                    p.get("leverage", 1),
                ),
            )
            position_rows += 1

    con.commit()
    con.close()

    print(f"[store_snapshot] Stored snapshot {snapshot_id}  |  "
          f"{wallet_rows} wallets  |  {position_rows} positions  |  {fetched_at}")


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
