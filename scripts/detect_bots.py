"""
detect_bots.py — Scan all tracked whale addresses for bot/market-maker behaviour.

Analyses each address using 5 signals:
  1. Fill rate (fills per minute)
  2. Simultaneous fills (0ms gaps between fills)
  3. Large open order book
  4. Balanced buy/sell sides (market-maker signature)
  5. Many unique coins traded

Results are printed to console and saved to data/bot_scan_results.json.
Addresses scoring >= 60 are recommended for the exclusion list.

Usage:
    cd C:\\Users\\Sahil\\HyperLiquid
    .venv\\Scripts\\python.exe scripts\\detect_bots.py

    # Only show bots + suspicious (skip clean humans):
    .venv\\Scripts\\python.exe scripts\\detect_bots.py --bots-only

    # Write exclusion list to data/bot_exclusions.json:
    .venv\\Scripts\\python.exe scripts\\detect_bots.py --save-exclusions
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "whale_addresses.json"
RESULTS_FILE = ROOT / "data" / "bot_scan_results.json"
EXCLUSIONS_FILE = ROOT / "data" / "bot_exclusions.json"

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

BASE_URL = "https://api.hyperliquid.xyz/info"


def _post(payload: dict, retries: int = 3) -> dict | list:
    for attempt in range(retries):
        try:
            r = httpx.post(BASE_URL, json=payload, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def fetch_fills(address: str) -> list[dict]:
    return _post({"type": "userFills", "user": address})


def fetch_open_orders(address: str) -> list[dict]:
    return _post({"type": "openOrders", "user": address})


# ---------------------------------------------------------------------------
# Bot scoring
# ---------------------------------------------------------------------------

BOT_THRESHOLD = 60       # score >= 60 → confirmed bot
SUSPICIOUS_THRESHOLD = 35  # score 35-59 → suspicious


def compute_bot_score(fills: list[dict], open_order_count: int) -> tuple[int, dict]:
    """
    Returns (bot_score 0–100, signals dict).
    Higher score = more likely automated / market-maker.

    Scoring rubric:
      Fill rate    : up to 40 pts  (>20/min → 40, >10/min → 20, >5/min → 10)
      Zero-ms gaps : up to 25 pts  (>10% simultaneous → 25, >2% → 10)
      Open orders  : up to 25 pts  (>100 → 25, >30 → 15, >10 → 5)
      Side balance : up to 10 pts  (buy/sell ratio >0.7 → 10)  [MM signature]
    """
    signals: dict = {}
    score = 0

    if len(fills) < 10:
        return 0, {"reason": "too_few_fills"}

    # -- Fill rate --
    timestamps = sorted(f["time"] for f in fills)
    span_ms = timestamps[-1] - timestamps[0]
    span_min = span_ms / 60_000 if span_ms > 0 else 1.0
    fpm = len(fills) / span_min
    signals["fills_per_min"] = round(fpm, 1)
    signals["fill_span_min"] = round(span_min, 1)

    if fpm > 20:
        score += 40
    elif fpm > 10:
        score += 20
    elif fpm > 5:
        score += 10

    # -- Simultaneous fills (0ms gap) --
    gaps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    avg_gap_ms = sum(gaps) / len(gaps)
    zero_gaps = sum(1 for g in gaps if g == 0)
    zero_gap_pct = zero_gaps / len(gaps) * 100
    signals["avg_gap_ms"] = round(avg_gap_ms)
    signals["zero_gap_pct"] = round(zero_gap_pct, 1)

    if zero_gap_pct > 10:
        score += 25
    elif zero_gap_pct > 2:
        score += 10

    # -- Open order book depth --
    signals["open_orders"] = open_order_count
    if open_order_count > 100:
        score += 25
    elif open_order_count > 30:
        score += 15
    elif open_order_count > 10:
        score += 5

    # -- Balanced buy/sell sides (market-maker signature) --
    dirs = Counter(f.get("dir", "") for f in fills)
    buy_side = dirs.get("Buy", 0) + dirs.get("Open Long", 0) + dirs.get("Close Short", 0)
    sell_side = dirs.get("Sell", 0) + dirs.get("Open Short", 0) + dirs.get("Close Long", 0)
    if max(buy_side, sell_side) > 0:
        balance = min(buy_side, sell_side) / max(buy_side, sell_side)
        signals["side_balance"] = round(balance, 2)
        if balance > 0.7:
            score += 10

    # -- Unique coins (MM trades everything) --
    unique_coins = len({f["coin"] for f in fills})
    signals["unique_coins"] = unique_coins

    return min(score, 100), signals


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def _label(bot_score: int) -> str:
    if bot_score >= BOT_THRESHOLD:
        return "🤖 BOT"
    if bot_score >= SUSPICIOUS_THRESHOLD:
        return "⚠️  SUSPICIOUS"
    return "✅ HUMAN"


def run_scan(bots_only: bool = False, save_exclusions: bool = False) -> None:
    if not DATA_FILE.exists():
        sys.exit(f"[ERROR] whale_addresses.json not found at {DATA_FILE}")

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    whales = data["whales"]
    total = len(whales)

    print(f"🔍 Scanning {total} whale addresses for bot behaviour…\n")

    results: list[dict] = []
    errors: list[str] = []

    for i, whale in enumerate(whales, start=1):
        addr = whale["address"]
        label = whale.get("label") or "—"
        tier = whale.get("tier", "?")

        try:
            fills = fetch_fills(addr)
            orders = fetch_open_orders(addr)
            bot_score, signals = compute_bot_score(fills, len(orders))

            result = {
                "address": addr,
                "label": label,
                "tier": tier,
                "bot_score": bot_score,
                "verdict": "bot" if bot_score >= BOT_THRESHOLD else (
                    "suspicious" if bot_score >= SUSPICIOUS_THRESHOLD else "human"
                ),
                "signals": signals,
                "fills_returned": len(fills),
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            }
            results.append(result)

            if not bots_only or bot_score >= SUSPICIOUS_THRESHOLD:
                fpm = signals.get("fills_per_min", "?")
                oo = signals.get("open_orders", "?")
                print(
                    f"[{i:3d}/{total}]  {addr[:10]}…  {label:22s}  "
                    f"tier={tier:14s}  bot={bot_score:3d}  {_label(bot_score)}"
                    f"  fills={len(fills)}  orders={oo}  fpm={fpm}"
                )

        except Exception as exc:
            msg = f"[{i:3d}/{total}]  {addr[:10]}…  {label:22s}  ERROR: {exc}"
            print(msg)
            errors.append(addr)
            results.append({
                "address": addr,
                "label": label,
                "tier": tier,
                "bot_score": -1,
                "verdict": "error",
                "signals": {"error": str(exc)},
                "fills_returned": 0,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            })

        time.sleep(0.35)  # gentle rate-limiting

    # -- Summary --
    confirmed = [r for r in results if r["verdict"] == "bot"]
    suspicious = [r for r in results if r["verdict"] == "suspicious"]
    humans = [r for r in results if r["verdict"] == "human"]

    print(f"\n{'=' * 65}")
    print(f"SCAN COMPLETE  —  {len(confirmed)} bots | {len(suspicious)} suspicious | {len(humans)} human | {len(errors)} errors")

    if confirmed:
        print(f"\n🤖 CONFIRMED BOTS (score ≥ {BOT_THRESHOLD}):")
        for r in sorted(confirmed, key=lambda x: -x["bot_score"]):
            sigs = r["signals"]
            print(
                f"  {r['address']}  [{r['label']}]  score={r['bot_score']}"
                f"  fpm={sigs.get('fills_per_min','?')}  orders={sigs.get('open_orders','?')}"
                f"  zero_gap={sigs.get('zero_gap_pct','?')}%"
            )

    if suspicious:
        print(f"\n⚠️  SUSPICIOUS (score {SUSPICIOUS_THRESHOLD}–{BOT_THRESHOLD - 1}):")
        for r in sorted(suspicious, key=lambda x: -x["bot_score"]):
            sigs = r["signals"]
            print(
                f"  {r['address']}  [{r['label']}]  score={r['bot_score']}"
                f"  fpm={sigs.get('fills_per_min','?')}  orders={sigs.get('open_orders','?')}"
            )

    # -- Save full results --
    RESULTS_FILE.write_text(
        json.dumps(
            {
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "total": total,
                "confirmed_bots": len(confirmed),
                "suspicious": len(suspicious),
                "humans": len(humans),
                "errors": len(errors),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n💾 Full results saved → {RESULTS_FILE}")

    # -- Save exclusion list --
    if save_exclusions:
        exclusion_addresses = [r["address"] for r in confirmed]
        exclusion_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "description": "Addresses excluded from alerts — identified as bots or market makers",
            "threshold_used": BOT_THRESHOLD,
            "count": len(exclusion_addresses),
            "addresses": exclusion_addresses,
            "detail": [
                {"address": r["address"], "label": r["label"], "bot_score": r["bot_score"], "signals": r["signals"]}
                for r in confirmed
            ],
        }
        EXCLUSIONS_FILE.write_text(json.dumps(exclusion_data, indent=2), encoding="utf-8")
        print(f"🚫 Exclusion list ({len(exclusion_addresses)} addresses) saved → {EXCLUSIONS_FILE}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan whale addresses for bot/market-maker behaviour.")
    parser.add_argument(
        "--bots-only",
        action="store_true",
        help="Only print addresses scoring >= SUSPICIOUS_THRESHOLD (suppress clean humans)",
    )
    parser.add_argument(
        "--save-exclusions",
        action="store_true",
        help="Write confirmed bots to data/bot_exclusions.json for use in the monitor",
    )
    args = parser.parse_args()
    run_scan(bots_only=args.bots_only, save_exclusions=args.save_exclusions)
