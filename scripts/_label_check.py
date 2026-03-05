import json, pathlib

reg = json.loads(pathlib.Path('data/whale_addresses.json').read_text(encoding='utf-8'))
whales = reg.get('whales', {})
if isinstance(whales, dict):
    items = list(whales.items())
else:
    items = [(w['address'], w) for w in whales]

labelled = [(addr, w) for addr, w in items if w.get('label')]
print(f'Wallets with labels: {len(labelled)}')
for addr, w in labelled:
    print(f'  {addr}  tier={w["tier"]:12s}  score={w["whale_score"]}  label="{w["label"]}"')

print()
print(f'Total wallets in registry: {len(items)}')

# Also check the snapshot
snap = json.loads(pathlib.Path('data/live_positions_snapshot.json').read_text(encoding='utf-8'))
snap_labelled = [(w['address'], w.get('label',''), w.get('tier','')) for w in snap.get('wallets', []) if w.get('label')]
print(f'Wallets with labels in snapshot: {len(snap_labelled)}')
for addr, label, tier in snap_labelled[:20]:
    print(f'  {addr}  tier={tier:12s}  label="{label}"')
