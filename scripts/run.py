# run.py  --  fetch snapshot then generate bubble map
import subprocess, sys, os

BASE   = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable

steps = [
    ("Fetching snapshot...",        [PYTHON, os.path.join(BASE, "fetch_snapshot.py")]),
    ("Storing to database...",      [PYTHON, os.path.join(BASE, "store_snapshot.py")]),
    ("Building bubble map...",      [PYTHON, os.path.join(BASE, "bubble_map.py")]),
    ("Generating wallet profiles...", [PYTHON, os.path.join(BASE, "wallet_profile.py"), "--all"]),
    ("Building liquidation heatmap...", [PYTHON, os.path.join(BASE, "liq_heatmap.py")]),
]

for msg, cmd in steps:
    print(msg)
    result = subprocess.run(cmd, cwd=os.path.dirname(BASE))
    if result.returncode != 0:
        print("ERROR: step failed, aborting.")
        sys.exit(result.returncode)

print("Done.")
