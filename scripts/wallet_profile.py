"""
wallet_profile.py  --  Generate a standalone HTML profile page for one wallet.

Reads all history for the given address from hyperwhale.db and writes
reports/wallet_<short_addr>.html

Usage:
    python scripts/wallet_profile.py --address 0xefffa330cbae8d916ad1d33f0eeb16cfa711fa91
    python scripts/wallet_profile.py --all        # regenerate every wallet that has positions
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT        = Path(__file__).resolve().parent.parent
DB_PATH     = ROOT / "data" / "hyperwhale.db"
REPORTS_DIR = ROOT / "reports"

TIER_COLOR = {
    "apex":          "#FFD700",
    "whale":         "#4C8EDA",
    "shark":         "#2EC4B6",
    "dolphin":       "#48BB78",
    "dormant_whale": "#6E7681",
    "dormant":       "#6E7681",
}

def fmt(n):
    if n is None: return "—"
    n = float(n)
    if abs(n) >= 1_000_000: return f"${n/1_000_000:,.2f}M"
    if abs(n) >= 1_000:     return f"${n/1_000:,.1f}K"
    return f"${n:,.2f}"

def fmt_pnl(n):
    if n is None: return "—"
    n = float(n)
    sign = "+" if n >= 0 else ""
    color = "#3fb950" if n >= 0 else "#f85149"
    if abs(n) >= 1_000_000: v = f"{sign}${abs(n)/1_000_000:,.2f}M"
    elif abs(n) >= 1_000:   v = f"{sign}${abs(n)/1_000:,.1f}K"
    else:                   v = f"{sign}${abs(n):,.2f}"
    return f'<span style="color:{color}">{v}</span>'


def load_wallet(con, address: str) -> dict | None:
    con.row_factory = sqlite3.Row

    # Latest wallet state
    ws = con.execute("""
        SELECT * FROM wallet_states
        WHERE address = ?
        ORDER BY fetched_at DESC LIMIT 1
    """, (address,)).fetchone()
    if not ws:
        return None

    # Current positions (latest snapshot)
    positions = con.execute("""
        SELECT p.* FROM positions p
        JOIN wallet_states ws ON p.wallet_state_id = ws.id
        WHERE p.address = ?
          AND ws.snapshot_id = (SELECT MAX(snapshot_id) FROM wallet_states WHERE address = ?)
        ORDER BY p.notional DESC
    """, (address, address)).fetchall()

    # AV history across all snapshots
    av_history = con.execute("""
        SELECT fetched_at, account_value
        FROM wallet_states
        WHERE address = ?
        ORDER BY fetched_at ASC
    """, (address,)).fetchall()

    # Position history — previous snapshots (not current)
    pos_history = con.execute("""
        SELECT p.coin, p.side, p.notional, p.upnl, p.leverage, p.entry, ws.fetched_at, ws.snapshot_id
        FROM positions p
        JOIN wallet_states ws ON p.wallet_state_id = ws.id
        WHERE p.address = ?
        ORDER BY ws.fetched_at DESC, p.notional DESC
    """, (address,)).fetchall()

    # Total snapshots seen
    snap_count = con.execute(
        "SELECT COUNT(*) FROM wallet_states WHERE address=?", (address,)
    ).fetchone()[0]

    return {
        "ws":          ws,
        "positions":   [dict(r) for r in positions],
        "av_history":  [dict(r) for r in av_history],
        "pos_history": [dict(r) for r in pos_history],
        "snap_count":  snap_count,
    }


def render_html(address: str, data: dict) -> str:
    ws         = data["ws"]
    positions  = data["positions"]
    av_history = data["av_history"]
    snap_count = data["snap_count"]

    label      = ws["label"] or address[:16] + "..."
    tier       = ws["tier"] or "unknown"
    score      = ws["whale_score"] or 0
    av         = ws["account_value"] or 0
    tier_col   = TIER_COLOR.get(tier, "#8b949e")
    fetched    = ws["fetched_at"][:19].replace("T", " ") if ws["fetched_at"] else "—"

    # Long / short totals from current positions
    long_total  = sum(p["notional"] for p in positions if p["side"] == "long")
    short_total = sum(p["notional"] for p in positions if p["side"] == "short")
    total_notl  = long_total + short_total
    long_pct    = (long_total / total_notl * 100) if total_notl else 0

    # AV chart data
    av_labels = json.dumps([r["fetched_at"][:16].replace("T", " ") for r in av_history])
    av_values = json.dumps([round(r["account_value"] or 0, 2) for r in av_history])

    # Current positions table rows
    pos_rows = ""
    if positions:
        for p in positions:
            side_col = "#3fb950" if p["side"] == "long" else "#f85149"
            pos_rows += f"""
            <tr>
                <td class="mono">{p['coin']}</td>
                <td style="color:{side_col};font-weight:600">{(p['side'] or '').upper()}</td>
                <td>{fmt(p['notional'])}</td>
                <td>{fmt_pnl(p['upnl'])}</td>
                <td>{p['entry'] or '—'}</td>
                <td>{p['liq'] or '—'}</td>
                <td>{p['leverage'] or '—'}x</td>
            </tr>"""
    else:
        pos_rows = '<tr><td colspan="7" style="text-align:center;color:#8b949e">No open positions</td></tr>'

    # Position history table (last 30 rows, grouped by snapshot)
    hist_rows = ""
    seen_snaps = {}
    for p in data["pos_history"][:50]:
        snap_id = p["snapshot_id"]
        ts = p["fetched_at"][:16].replace("T", " ") if p["fetched_at"] else "—"
        if snap_id not in seen_snaps:
            seen_snaps[snap_id] = ts
            hist_rows += f'<tr class="snap-header"><td colspan="5">{ts}</td></tr>'
        side_col = "#3fb950" if p["side"] == "long" else "#f85149"
        hist_rows += f"""
        <tr>
            <td class="mono" style="padding-left:20px">{p['coin']}</td>
            <td style="color:{side_col}">{(p['side'] or '').upper()}</td>
            <td>{fmt(p['notional'])}</td>
            <td>{fmt_pnl(p['upnl'])}</td>
            <td>{p['leverage'] or '—'}x</td>
        </tr>"""

    short_addr = address[:8] + "..." + address[-6:]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HyperWhale — {label}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{background:#0d1117;color:#c9d1d9;font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}}
a{{color:#58a6ff;text-decoration:none}}
a:hover{{text-decoration:underline}}

.topbar{{background:#161b22;border-bottom:1px solid #30363d;padding:14px 28px;display:flex;align-items:center;gap:16px}}
.topbar .back{{color:#8b949e;font-size:13px;cursor:pointer}}
.topbar .back:hover{{color:#c9d1d9}}
.topbar h1{{font-size:18px;font-weight:600;flex:1}}

.page{{max-width:1100px;margin:0 auto;padding:28px 20px;display:grid;gap:20px}}

/* header card */
.header-card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px 28px;display:flex;flex-wrap:wrap;gap:24px;align-items:center}}
.avatar{{width:56px;height:56px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:700;flex-shrink:0}}
.wallet-info h2{{font-size:20px;font-weight:700;margin-bottom:4px}}
.wallet-info .addr{{font-size:12px;color:#8b949e;font-family:monospace}}
.tier-badge{{padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}}
.stats-row{{display:flex;flex-wrap:wrap;gap:12px;margin-left:auto}}
.stat-pill{{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:10px 16px;text-align:center;min-width:110px}}
.stat-pill .val{{font-size:18px;font-weight:700;color:#e6edf3}}
.stat-pill .lbl{{font-size:11px;color:#8b949e;margin-top:2px}}

/* section cards */
.card{{background:#161b22;border:1px solid #30363d;border-radius:12px;overflow:hidden}}
.card-title{{padding:16px 20px;border-bottom:1px solid #30363d;font-size:14px;font-weight:600;color:#e6edf3;display:flex;align-items:center;gap:8px}}
.card-body{{padding:20px}}

/* tables */
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:8px 12px;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d;white-space:nowrap}}
td{{padding:9px 12px;border-bottom:1px solid #21262d}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#1c2128}}
.mono{{font-family:monospace;font-size:12px}}
.snap-header td{{background:#1c2128;color:#8b949e;font-size:11px;padding:6px 12px;font-style:italic}}

/* chart */
.chart-wrap{{position:relative;height:220px}}

/* long/short bar */
.bias-bar{{height:8px;border-radius:4px;background:#30363d;overflow:hidden;margin-top:8px}}
.bias-fill{{height:100%;border-radius:4px;background:linear-gradient(90deg,#f85149 0%,#3fb950 100%)}}
.bias-labels{{display:flex;justify-content:space-between;font-size:11px;color:#8b949e;margin-top:4px}}

/* placeholder */
.placeholder{{padding:40px 20px;text-align:center;color:#8b949e;font-size:13px}}
.placeholder .icon{{font-size:32px;margin-bottom:8px}}

/* external link */
.ext-link{{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:#58a6ff;padding:6px 12px;border:1px solid #30363d;border-radius:6px;margin-left:auto}}
.ext-link:hover{{background:#1c2128}}

/* grid layout */
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
@media(max-width:700px){{.two-col{{grid-template-columns:1fr}}}}
</style>
</head>
<body>

<div class="topbar">
  <span class="back" onclick="history.back()"> Back</span>
  <h1>Wallet Profile</h1>
  <a class="ext-link" href="https://hypurrscan.io/address/{address}" target="_blank">
    View on Hypurrscan 
  </a>
</div>

<div class="page">

  <!-- HEADER CARD -->
  <div class="header-card">
    <div class="avatar" style="background:{tier_col}22;color:{tier_col}">{tier[0].upper()}</div>
    <div class="wallet-info">
      <h2>{label}</h2>
      <div class="addr">{address}</div>
      <div style="margin-top:8px;display:flex;gap:8px;align-items:center">
        <span class="tier-badge" style="background:{tier_col}22;color:{tier_col}">{tier}</span>
        <span style="font-size:12px;color:#8b949e">Score: {score}</span>
        <span style="font-size:12px;color:#8b949e">  {snap_count} snapshots tracked</span>
        <span style="font-size:12px;color:#8b949e">  Last seen {fetched}</span>
      </div>
    </div>
    <div class="stats-row">
      <div class="stat-pill">
        <div class="val">{fmt(av)}</div>
        <div class="lbl">Account Value</div>
      </div>
      <div class="stat-pill">
        <div class="val">{fmt(long_total)}</div>
        <div class="lbl">Total Long</div>
      </div>
      <div class="stat-pill">
        <div class="val">{fmt(short_total)}</div>
        <div class="lbl">Total Short</div>
      </div>
      <div class="stat-pill">
        <div class="val">{len(positions)}</div>
        <div class="lbl">Open Positions</div>
      </div>
    </div>
  </div>

  <!-- AV CHART + BIAS -->
  <div class="two-col">
    <div class="card">
      <div class="card-title"> Account Value History</div>
      <div class="card-body">
        <div class="chart-wrap">
          <canvas id="avChart"></canvas>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-title"> Long / Short Bias</div>
      <div class="card-body" style="padding-top:28px">
        <div style="font-size:32px;font-weight:700;text-align:center;color:#e6edf3">{long_pct:.0f}% Long</div>
        <div style="font-size:13px;color:#8b949e;text-align:center;margin-bottom:16px">{100-long_pct:.0f}% Short</div>
        <div class="bias-bar">
          <div class="bias-fill" style="width:{long_pct}%;background:#3fb950"></div>
        </div>
        <div class="bias-labels"><span>Short</span><span>Long</span></div>
        <div style="margin-top:24px;display:grid;grid-template-columns:1fr 1fr;gap:12px;text-align:center">
          <div style="background:#3fb95011;border:1px solid #3fb95033;border-radius:8px;padding:12px">
            <div style="color:#3fb950;font-size:16px;font-weight:700">{fmt(long_total)}</div>
            <div style="color:#8b949e;font-size:11px;margin-top:2px">Long Notional</div>
          </div>
          <div style="background:#f8514911;border:1px solid #f8514933;border-radius:8px;padding:12px">
            <div style="color:#f85149;font-size:16px;font-weight:700">{fmt(short_total)}</div>
            <div style="color:#8b949e;font-size:11px;margin-top:2px">Short Notional</div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- CURRENT POSITIONS -->
  <div class="card">
    <div class="card-title"> Current Open Positions</div>
    <div class="card-body" style="padding:0">
      <table>
        <thead>
          <tr>
            <th>Coin</th><th>Side</th><th>Notional</th>
            <th>Unrealised PnL</th><th>Entry</th><th>Liq Price</th><th>Leverage</th>
          </tr>
        </thead>
        <tbody>{pos_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- POSITION HISTORY -->
  <div class="card">
    <div class="card-title"> Position History  <span style="font-size:11px;color:#8b949e;font-weight:400">across snapshots</span></div>
    <div class="card-body" style="padding:0;max-height:400px;overflow-y:auto">
      <table>
        <thead>
          <tr><th>Coin</th><th>Side</th><th>Notional</th><th>uPnL</th><th>Leverage</th></tr>
        </thead>
        <tbody>{hist_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- COMING SOON -->
  <div class="two-col">
    <div class="card">
      <div class="card-title"> Anomaly Detection</div>
      <div class="placeholder">
        <div class="icon"></div>
        Available once 7+ days of data is collected.<br>Will show σ-score vs this wallet's own baseline.
      </div>
    </div>
    <div class="card">
      <div class="card-title"> Correlated Wallets</div>
      <div class="placeholder">
        <div class="icon"></div>
        Available once correlation engine is built.<br>Will show wallets that move with this one.
      </div>
    </div>
  </div>

</div>

<script>
var avLabels = {av_labels};
var avValues = {av_values};

var ctx = document.getElementById('avChart').getContext('2d');
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: avLabels,
    datasets: [{{
      data: avValues,
      borderColor: '#4C8EDA',
      backgroundColor: 'rgba(76,142,218,0.08)',
      borderWidth: 2,
      pointRadius: 3,
      pointBackgroundColor: '#4C8EDA',
      fill: true,
      tension: 0.3
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color:'#8b949e', maxRotation:30, font:{{size:10}} }}, grid:{{ color:'#21262d' }} }},
      y: {{
        ticks: {{ color:'#8b949e', font:{{size:10}},
          callback: function(v) {{
            if(v>=1e6) return '$'+(v/1e6).toFixed(1)+'M';
            if(v>=1e3) return '$'+(v/1e3).toFixed(0)+'K';
            return '$'+v;
          }}
        }},
        grid:{{ color:'#21262d' }}
      }}
    }}
  }}
}});
</script>
</body>
</html>"""


def generate(address: str, db_path: Path = DB_PATH) -> Path:
    con = sqlite3.connect(db_path)
    data = load_wallet(con, address)
    con.close()

    if not data:
        print(f"[wallet_profile] No data found for {address}")
        return None

    html   = render_html(address, data)
    slug   = address[:10].lower()
    out    = REPORTS_DIR / f"wallet_{slug}.html"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[wallet_profile] {address[:16]}...  ->  {out.name}")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", help="Single wallet address")
    parser.add_argument("--all", action="store_true", help="Generate for all wallets with positions")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    db_path = Path(args.db)
    con = sqlite3.connect(db_path)

    if args.all:
        addresses = [r[0] for r in con.execute(
            "SELECT DISTINCT address FROM positions"
        ).fetchall()]
        con.close()
        print(f"[wallet_profile] Generating {len(addresses)} profiles...")
        for addr in addresses:
            generate(addr, db_path)
    elif args.address:
        con.close()
        generate(args.address, db_path)
    else:
        con.close()
        parser.print_help()


if __name__ == "__main__":
    main()
