import json, pathlib
data = json.loads(pathlib.Path('data/live_positions_snapshot.json').read_text(encoding='utf-8'))
wallets = data.get('wallets', [])

coins = {}
for w in wallets:
    for p in w.get('positions', []):
        if p.get('liq'):
            coin = p['coin']
            coins[coin] = coins.get(coin, 0) + 1

top = sorted(coins.items(), key=lambda x: -x[1])[:15]
print('Top coins with liq data:')
for c, n in top:
    print(f'  {c:12s}: {n} positions')

# BTC sample
print()
for w in wallets:
    for p in w.get('positions', []):
        if p.get('coin') == 'BTC' and p.get('liq'):
            print('BTC sample:', json.dumps(p, indent=2))
            break
    else:
        continue
    break
