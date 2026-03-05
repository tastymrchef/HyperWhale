import sqlite3
from pathlib import Path

db = Path(__file__).parent.parent / "data" / "hyperwhale.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row  # lets us access columns by name

tables = ["snapshots", "wallet_states", "positions", "wallet_baselines"]

for t in tables:
    print("=" * 60)
    print(f"TABLE: {t}")
    print("=" * 60)
    rows = con.execute(f"SELECT * FROM {t} LIMIT 2").fetchall()
    if not rows:
        print("  (empty)")
    for row in rows:
        for col in row.keys():
            print(f"  {col:25s} = {row[col]}")
        print()

con.close()
