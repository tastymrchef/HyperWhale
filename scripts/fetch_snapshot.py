"""
fetch_snapshot.py — Fetch live position data for all tracked (non-bot) whales.

Calls the Hyperliquid clearinghouseState API for each wallet and saves the
result to data/live_positions_snapshot.json, which is consumed by bubble_map.py
and any other analytics scripts.

Usage:
    cd C:\\Users\\Sahil\\HyperLiquid
    .venv\\Scripts\\python.exe scripts\\fetch_snapshot.py

Output:
    data/live_positions_snapshot.json
"""

from __future__ import annotations

import io
import sys
import json
import time
from collections import Counter

# Force UTF-8 stdout so unicode chars work in Task Scheduler / non-UTF shells
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "whale_addresses.json"
EXCLUSIONS_FILE = ROOT / "data" / "bot_exclusions.json"
OUT_FILE = ROOT / "data" / "live_positions_snapshot.json"

BASE_URL = "https://api.hyperliquid.xyz/info"

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def fetch_state(address: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            r = httpx.post(
                BASE_URL,
                json={"type": "clearinghouseState", "user": address},
                timeout=20,
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                print("  [429] Rate limited — waiting 5s…")
                time.sleep(5)
            elif attempt == retries - 1:
                raise
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not DATA_FILE.exists():
        raise SystemExit(f"[ERROR] {DATA_FILE} not found — run discovery first")

    whales = json.loads(DATA_FILE.read_text(encoding="utf-8"))["whales"]

    excluded: set[str] = set()
    if EXCLUSIONS_FILE.exists():
        exc = json.loads(EXCLUSIONS_FILE.read_text(encoding="utf-8"))
        excluded = {a.lower() for a in exc.get("addresses", [])}
        print(f"Loaded {len(excluded)} bot exclusions\n")

    total = len(whales)
    results = []
    coin_counter: Counter = Counter()
    errors = 0

    print(f"Fetching live positions for {total} whales…\n")

    for i, whale in enumerate(whales, start=1):
        addr = whale["address"]
        label = whale.get("label", "")
        tier = whale.get("tier", "skip")

        if addr.lower() in excluded:
            print(f"[{i:3d}/{total}]  {addr[:12]}...  skipped (bot)")
            continue

        try:
            state = fetch_state(addr)
            ms = state.get("marginSummary", {})
            av = float(ms.get("accountValue", 0))

            pos_list = []
            for ap in state.get("assetPositions", []):
                p = ap.get("position", {})
                szi = float(p.get("szi", 0))
                pv = abs(float(p.get("positionValue", 0)))
                coin = p.get("coin", "?")

                if pv == 0:
                    continue

                coin_counter[coin] += 1
                pos_list.append({
                    "coin": coin,
                    "side": "long" if szi > 0 else "short",
                    "notional": round(pv, 2),
                    "upnl": round(float(p.get("unrealizedPnl", 0)), 2),
                    "entry": float(p.get("entryPx", 0)),
                    "liq": p.get("liquidationPx"),
                    "leverage": p.get("leverage", {}).get("value", 1),
                })

            results.append({
                "address": addr,
                "label": label,
                "tier": tier,
                "whale_score": whale.get("whale_score", 0),
                "account_value": round(av, 2),
                "staked_hype_tier": whale.get("staked_hype_tier", "none"),
                "positions": pos_list,
            })

            ntl = sum(p["notional"] for p in pos_list)
            long_ntl = sum(p["notional"] for p in pos_list if p["side"] == "long")
            short_ntl = sum(p["notional"] for p in pos_list if p["side"] == "short")
            bias = ((long_ntl - short_ntl) / ntl * 100) if ntl > 0 else 0
            direction = f"{'LONG' if bias > 0 else 'SHORT'} {abs(bias):.0f}%" if ntl > 0 else "FLAT"

            print(
                f"[{i:3d}/{total}]  {addr[:12]}…  {(label or tier):22s}  "
                f"AV=${av:>12,.0f}  ntl=${ntl:>12,.0f}  {direction}  ({len(pos_list)} pos)"
            )

        except Exception as exc:
            print(f"[{i:3d}/{total}]  {addr[:12]}…  ERROR: {exc}")
            errors += 1

        time.sleep(0.25)

    # Save
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_wallets": len(results),
        "errors": errors,
        "top_coins": dict(coin_counter.most_common(30)),
        "wallets": results,
    }
    OUT_FILE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"✅ Saved {len(results)} wallets → {OUT_FILE}")
    print(f"   Errors: {errors}")
    print(f"\nTop coins by # wallets holding:")
    for coin, count in coin_counter.most_common(15):
        print(f"   {coin:12s}  {count:3d} wallets")


if __name__ == "__main__":
    main()
