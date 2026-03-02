"""Find whale addresses with active positions using Hyperliquid API."""

import json
import httpx

API = "https://api.hyperliquid.xyz/info"
client = httpx.Client(timeout=15)

# Strategy 1: Get vault details and check depositors
print("=== Strategy 1: Check HLP Vault depositors ===")
resp = client.post(API, json={"type": "vaultDetails", "vaultAddress": "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"})
vault = resp.json()

# Get top depositors from the vault
followers = vault.get("followers", [])
print(f"Found {len(followers)} vault depositors")

# Sort by deposit amount and check the top ones
depositor_addrs = []
for f in sorted(followers, key=lambda x: float(x.get("vaultEquity", "0")), reverse=True)[:30]:
    addr = f.get("user", "")
    equity = float(f.get("vaultEquity", "0"))
    if equity > 50000:  # Only large depositors
        depositor_addrs.append((addr, equity))
        print(f"  Depositor: {addr[:12]}...  vault equity: ${equity:,.0f}")

# Now check which depositors also have active perp positions
print("\n=== Strategy 2: Check top depositors for active positions ===")
found = []
for addr, vault_eq in depositor_addrs[:20]:
    try:
        resp2 = client.post(API, json={"type": "clearinghouseState", "user": addr})
        data = resp2.json()
        ms = data.get("marginSummary", {})
        av = float(ms.get("accountValue", "0"))
        positions = data.get("assetPositions", [])
        if len(positions) > 0:
            found.append((addr, av, len(positions)))
            print(f"  ✓ {addr[:12]}...  AV: ${av:,.0f}  Positions: {len(positions)}")
            for pos in positions[:3]:
                p = pos.get("position", {})
                coin = p.get("coin", "?")
                szi = p.get("szi", "?")
                upnl = float(p.get("unrealizedPnl", "0"))
                print(f"      {coin:>8}  size={szi}  uPNL=${upnl:,.2f}")
        else:
            print(f"  - {addr[:12]}...  AV: ${av:,.0f}  (no positions)")
    except Exception as e:
        print(f"  ✗ {addr[:12]}... ERROR: {e}")

print(f"\n=== FOUND {len(found)} WHALES WITH ACTIVE POSITIONS ===")
for addr, av, n in found:
    print(f'    "{addr}",  # ${av:,.0f}, {n} positions')

# Save to a file for use in seed_whales.json
if found:
    output = {"whales": []}
    for addr, av, n in found:
        output["whales"].append({
            "address": addr,
            "label": None,
            "notes": f"Found via HLP vault depositor scan. AV: ${av:,.0f}, {n} positions",
        })
    with open("data/discovered_whales.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved {len(found)} addresses to data/discovered_whales.json")

client.close()
