"""
Fetch historical fills for a list of whale wallets from Jan 1, 2025 to now.
Stores results as JSON per wallet in whale_activity_analysis/data/.

Usage: python fetch_whale_fills.py
"""
import os
import json
import time
from datetime import datetime, timezone
import httpx

# --- Config ---
WHALE_FILE = "data/whale_addresses.json"
DATA_DIR = "data"
START_DATE = datetime(2025, 1, 1, tzinfo=timezone.utc)
END_DATE = datetime.now(timezone.utc)
API_URL = "https://api.hyperliquid.xyz/info"
RATE_LIMIT_DELAY = 0.5  # seconds between requests

os.makedirs(DATA_DIR, exist_ok=True)

# --- Load whale addresses ---
with open(WHALE_FILE, "r") as f:
    whales = json.load(f)["whales"]
addresses = [w["address"] for w in whales]

# --- Fetch fills for each whale ---
client = httpx.Client(timeout=30.0)
for addr in addresses:
    out_path = os.path.join(DATA_DIR, f"{addr}.fills.json")
    if os.path.exists(out_path):
        print(f"[SKIP] {addr} (already fetched)")
        continue
    print(f"[FETCH] {addr}")
    start_ms = int(START_DATE.timestamp() * 1000)
    end_ms = int(END_DATE.timestamp() * 1000)
    try:
        resp = client.post(API_URL, json={
            "type": "userFillsByTime",
            "user": addr,
            "startTime": start_ms,
            "endTime": end_ms
        })
        resp.raise_for_status()
        fills = resp.json()
        with open(out_path, "w") as outf:
            json.dump(fills, outf)
        print(f"  Got {len(fills)} fills")
    except Exception as e:
        print(f"  ERROR: {e}")
    time.sleep(RATE_LIMIT_DELAY)
client.close()
print("Done.")
