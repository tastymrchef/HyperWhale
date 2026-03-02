"""
Fetch historical fills for all whale wallets from Jan 1, 2025 to now.
Paginates backwards in time to collect up to MAX_FILLS per wallet.
Stores results as JSON per wallet in whale_activity_analysis/data/.

Usage: python fetch_whale_fills.py
       python fetch_whale_fills.py --refetch   # overwrite existing files
"""
import os
import sys
import json
import time
from datetime import datetime, timezone
import httpx

# --- Config ---
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
WHALE_FILE  = os.path.join(SCRIPT_DIR, "..", "data", "whale_addresses.json")
DATA_DIR    = os.path.join(SCRIPT_DIR, "data")
START_DATE  = datetime(2025, 1, 1, tzinfo=timezone.utc)
END_DATE    = datetime.now(timezone.utc)
API_URL     = "https://api.hyperliquid.xyz/info"
PAGE_DELAY  = 0.5   # seconds between every API request (rate-limit safety)
MAX_FILLS   = 10_000  # stop collecting once we have this many fills per wallet
PAGE_SIZE   = 2_000   # Hyperliquid hard cap per request

REFETCH = "--refetch" in sys.argv  # pass --refetch to overwrite existing files

os.makedirs(DATA_DIR, exist_ok=True)


def fetch_fills_paginated(client: httpx.Client, addr: str) -> list:
    """
    Walk backwards in time from END_DATE to START_DATE, fetching pages of
    up to PAGE_SIZE fills each time, until we have MAX_FILLS or reach START_DATE.
    Returns a deduplicated list sorted oldest-first.
    """
    start_ms = int(START_DATE.timestamp() * 1000)
    end_ms   = int(END_DATE.timestamp() * 1000)
    all_fills: list = []
    seen_tids: set  = set()
    page = 1

    while True:
        print(f"    page {page} | window {_fmt_ms(start_ms)} -> {_fmt_ms(end_ms)}", flush=True)
        try:
            resp = client.post(API_URL, json={
                "type":      "userFillsByTime",
                "user":      addr,
                "startTime": start_ms,
                "endTime":   end_ms,
            })
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            print(f"    HTTP {e.response.status_code} — stopping pagination")
            break
        except Exception as e:
            print(f"    ERROR: {e} — stopping pagination")
            break

        page_fills = resp.json()
        if not page_fills:
            print(f"    no more fills — done")
            break

        # Deduplicate by tid (trade ID)
        new_fills = [f for f in page_fills if f["tid"] not in seen_tids]
        for f in new_fills:
            seen_tids.add(f["tid"])
        all_fills.extend(new_fills)

        print(f"    +{len(new_fills)} new fills (total so far: {len(all_fills)})", flush=True)

        # Stop if we've hit our cap
        if len(all_fills) >= MAX_FILLS:
            print(f"    reached MAX_FILLS={MAX_FILLS} cap — stopping")
            break

        # Stop if this page was smaller than PAGE_SIZE (no more data)
        if len(page_fills) < PAGE_SIZE:
            print(f"    last page (< {PAGE_SIZE} fills) — done")
            break

        # Move the window backwards: new end = oldest fill's timestamp - 1ms
        oldest_time = min(f["time"] for f in page_fills)
        if oldest_time <= start_ms:
            print(f"    reached START_DATE — done")
            break
        end_ms = oldest_time - 1
        page  += 1
        time.sleep(PAGE_DELAY)

    # Sort oldest-first for easier time-series analysis
    all_fills.sort(key=lambda f: f["time"])
    return all_fills


def _fmt_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


# --- Load whale addresses ---
with open(WHALE_FILE, "r") as f:
    whales = json.load(f)["whales"]
addresses = [w["address"] for w in whales]
print(f"Loaded {len(addresses)} whale addresses")
print(f"Date range: {START_DATE.date()} -> {END_DATE.date()}")
print(f"Max fills per wallet: {MAX_FILLS}")
print()

# --- Fetch fills for each whale ---
client = httpx.Client(timeout=30.0)
for i, addr in enumerate(addresses, 1):
    out_path = os.path.join(DATA_DIR, f"{addr}.fills.json")
    if os.path.exists(out_path) and not REFETCH:
        # Peek at existing file — skip only if it has actual fills
        try:
            with open(out_path) as f:
                existing = json.load(f)
            n = len(existing)
            if n > 0:
                earliest = _fmt_ms(min(x["time"] for x in existing))
                latest   = _fmt_ms(max(x["time"] for x in existing))
                print(f"[{i:3d}/{len(addresses)}] SKIP {addr}  ({n} fills, {earliest} -> {latest})")
                continue  # only skip if we actually have data
            else:
                print(f"[{i:3d}/{len(addresses)}] RETRY {addr}  (empty file from previous 429)")
        except Exception:
            print(f"[{i:3d}/{len(addresses)}] RETRY {addr}  (unreadable file)")
        # fall through to fetch

    print(f"[{i:3d}/{len(addresses)}] FETCH {addr}")
    fills = fetch_fills_paginated(client, addr)
    with open(out_path, "w") as outf:
        json.dump(fills, outf)
    date_range = ""
    if fills:
        date_range = f"  {_fmt_ms(fills[0]['time'])} -> {_fmt_ms(fills[-1]['time'])}"
    print(f"  => Saved {len(fills)} fills{date_range}")
    time.sleep(PAGE_DELAY)

client.close()
print("\nDone.")
