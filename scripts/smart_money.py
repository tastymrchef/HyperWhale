"""
smart_money.py  --  Generate the Smart Money dashboard HTML page.

Reads apex + whale wallets from hyperwhale.db and whale_addresses.json,
produces reports/smart_money.html with:
  - Aggregate summary bar (total notional, L/S %, top coins)
  - Per-wallet cards sorted by total notional (most active first)
  - Each card links to the existing wallet_XXXX.html detail page
  - Auto-refreshes every 120 seconds

Usage:
    python scripts/smart_money.py
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT        = Path(__file__).resolve().parent.parent
DB_PATH     = ROOT / "data" / "hyperwhale.db"
WHALE_FILE  = ROOT / "data" / "whale_addresses.json"
REPORTS_DIR = ROOT / "reports"
OUTPUT      = REPORTS_DIR / "smart_money.html"

SMART_MONEY_TIERS = {"apex", "whale", "shark"}

TIER_COLOR = {
    "apex":  "#FFD700",
    "whale": "#4C8EDA",
    "shark": "#2EC4B6",
}

TIER_BADGE_BG = {
    "apex":  "rgba(255,215,0,0.15)",
    "whale": "rgba(76,142,218,0.15)",
    "shark": "rgba(46,196,182,0.12)",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt(n, decimals=2):
    if n is None:
        return "—"
    n = float(n)
    if abs(n) >= 1_000_000:
        return f"${n / 1_000_000:,.{decimals}f}M"
    if abs(n) >= 1_000:
        return f"${n / 1_000:,.1f}K"
    return f"${n:,.2f}"

def fmt_pct(n):
    if n is None:
        return "—"
    return f"{float(n):.1f}%"

def fmt_score(n):
    if n is None:
        return "—"
    return f"{float(n):.1f}"

def pnl_color(n):
    return "#3fb950" if float(n or 0) >= 0 else "#f85149"

def side_color(side):
    return "#3fb950" if side == "long" else "#f85149"

def short_addr(addr):
    return f"{addr[:6]}...{addr[-4:]}"

def wallet_page(addr):
    return f"wallet_{addr[:10]}.html"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_registry() -> dict[str, dict]:
    """Load apex+whale wallets from whale_addresses.json keyed by address."""
    data = json.loads(WHALE_FILE.read_text(encoding="utf-8"))
    return {
        w["address"].lower(): w
        for w in data["whales"]
        if w.get("tier") in SMART_MONEY_TIERS
    }

def load_wallet_data(con: sqlite3.Connection, addresses: list[str]) -> dict[str, dict]:
    """Load latest snapshot data for each wallet from DB."""
    con.row_factory = sqlite3.Row
    result = {}

    for addr in addresses:
        # Latest wallet state from hourly snapshots
        ws = con.execute("""
            SELECT * FROM wallet_states
            WHERE address = ?
            ORDER BY fetched_at DESC LIMIT 1
        """, (addr,)).fetchone()

        if not ws:
            continue

        # Current positions
        positions = con.execute("""
            SELECT p.* FROM positions p
            JOIN wallet_states wst ON p.wallet_state_id = wst.id
            WHERE p.address = ?
              AND wst.snapshot_id = (
                  SELECT MAX(snapshot_id) FROM wallet_states WHERE address = ?
              )
            ORDER BY p.notional DESC
        """, (addr, addr)).fetchall()

        # Recent events (last 5)
        events = con.execute("""
            SELECT event_type, coin, side, old_size, new_size,
                   size_change_pct, notional_value, timestamp
            FROM events
            WHERE address = ?
            ORDER BY timestamp DESC LIMIT 5
        """, (addr,)).fetchall()

        result[addr] = {
            "ws":       dict(ws),
            "positions": [dict(p) for p in positions],
            "events":    [dict(e) for e in events],
        }

    return result

# ---------------------------------------------------------------------------
# Aggregate calculations
# ---------------------------------------------------------------------------

def calc_aggregates(wallets: list[dict]) -> dict:
    """Calculate aggregate stats across all smart money wallets."""
    total_long   = 0.0
    total_short  = 0.0
    coin_longs   = defaultdict(float)
    coin_shorts  = defaultdict(float)
    total_av     = 0.0
    wallets_with_positions = 0

    for w in wallets:
        total_av += w["db"]["ws"].get("account_value") or 0
        positions = w["db"]["positions"]
        if positions:
            wallets_with_positions += 1
        for p in positions:
            notional = float(p.get("notional") or 0)
            side     = p.get("side", "")
            coin     = p.get("coin", "")
            if side == "long":
                total_long += notional
                coin_longs[coin] += notional
            elif side == "short":
                total_short += notional
                coin_shorts[coin] += notional

    total_notional = total_long + total_short
    long_pct  = (total_long  / total_notional * 100) if total_notional else 0
    short_pct = (total_short / total_notional * 100) if total_notional else 0

    # Top coins by total notional
    all_coins = set(coin_longs.keys()) | set(coin_shorts.keys())
    coin_stats = []
    for coin in all_coins:
        l = coin_longs.get(coin, 0)
        s = coin_shorts.get(coin, 0)
        t = l + s
        coin_stats.append({
            "coin":       coin,
            "total":      t,
            "long":       l,
            "short":      s,
            "long_pct":   (l / t * 100) if t else 0,
        })
    coin_stats.sort(key=lambda x: x["total"], reverse=True)

    return {
        "total_av":               total_av,
        "total_notional":         total_notional,
        "total_long":             total_long,
        "total_short":            total_short,
        "long_pct":               long_pct,
        "short_pct":              short_pct,
        "top_coins":              coin_stats[:10],
        "wallets_with_positions": wallets_with_positions,
        "wallet_count":           len(wallets),
    }

# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def render_coin_sentiment(pct: float) -> str:
    if pct >= 70:
        return '<span style="color:#3fb950">🟢 BULL</span>'
    elif pct >= 55:
        return '<span style="color:#8fd19e">🟡 SLIGHT BULL</span>'
    elif pct >= 45:
        return '<span style="color:#8b949e">⚪ NEUTRAL</span>'
    elif pct >= 30:
        return '<span style="color:#f0883e">🟡 SLIGHT BEAR</span>'
    else:
        return '<span style="color:#f85149">🔴 BEAR</span>'

def render_summary(agg: dict, generated_at: str) -> str:
    lp  = agg["long_pct"]
    sp  = agg["short_pct"]
    bar_long  = f"{lp:.1f}%"
    bar_short = f"{sp:.1f}%"

    # Top coins table rows
    coin_rows = ""
    for c in agg["top_coins"]:
        sentiment = render_coin_sentiment(c["long_pct"])
        coin_rows += f"""
        <tr>
          <td style="font-weight:600;color:#e6edf3">{c['coin']}</td>
          <td style="color:#8b949e">{fmt(c['total'])}</td>
          <td>
            <div style="display:flex;align-items:center;gap:6px">
              <span style="color:#3fb950">{c['long_pct']:.0f}%L</span>
              <div style="flex:1;height:6px;background:#21262d;border-radius:3px;min-width:80px">
                <div style="width:{c['long_pct']:.1f}%;height:100%;background:#3fb950;border-radius:3px"></div>
              </div>
              <span style="color:#f85149">{100-c['long_pct']:.0f}%S</span>
            </div>
          </td>
          <td>{sentiment}</td>
        </tr>"""

    overall_sentiment = render_coin_sentiment(lp)

    return f"""
    <div class="summary-card">
      <div class="summary-header">
        <div>
          <div class="summary-title">🧠 Smart Money Overview</div>
          <div class="summary-sub">
            {agg['wallets_with_positions']} of {agg['wallet_count']} wallets have open positions
            &nbsp;·&nbsp; Updated: {generated_at}
          </div>
        </div>
        <div style="text-align:right">
          <div style="font-size:1.5rem;font-weight:700;color:#e6edf3">{fmt(agg['total_notional'])}</div>
          <div style="color:#8b949e;font-size:0.85rem">Total Notional</div>
        </div>
      </div>

      <div class="summary-stats">
        <div class="stat-box">
          <div class="stat-label">Total AV</div>
          <div class="stat-value">{fmt(agg['total_av'])}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">Long Exposure</div>
          <div class="stat-value" style="color:#3fb950">{fmt(agg['total_long'])}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">Short Exposure</div>
          <div class="stat-value" style="color:#f85149">{fmt(agg['total_short'])}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">Overall Sentiment</div>
          <div class="stat-value" style="font-size:1rem">{overall_sentiment}</div>
        </div>
      </div>

      <!-- L/S Bar -->
      <div style="margin:16px 0 8px">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px;font-size:0.85rem">
          <span style="color:#3fb950">LONG {bar_long}</span>
          <span style="color:#f85149">SHORT {bar_short}</span>
        </div>
        <div style="height:10px;background:#21262d;border-radius:5px;overflow:hidden">
          <div style="width:{bar_long};height:100%;background:linear-gradient(90deg,#3fb950,#2ea043);border-radius:5px"></div>
        </div>
      </div>

      <!-- Top Coins -->
      <div style="margin-top:20px">
        <div style="color:#8b949e;font-size:0.8rem;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">Top Coins by Notional</div>
        <table class="coin-table">
          <thead>
            <tr>
              <th>Coin</th><th>Notional</th><th>L/S Split</th><th>Sentiment</th>
            </tr>
          </thead>
          <tbody>{coin_rows}</tbody>
        </table>
      </div>
    </div>"""

def render_wallet_table(wallets: list[dict]) -> str:
    """Render a sortable table of all wallets — click row to go to detail page."""
    rows = ""
    for w in wallets:
        addr      = w["address"]
        reg       = w["reg"]
        ws        = w["db"]["ws"]
        positions = w["db"]["positions"]
        tier      = reg.get("tier", "shark")
        label     = reg.get("label") or ws.get("label") or short_addr(addr)
        score     = reg.get("whale_score", 0)
        av        = float(ws.get("account_value") or 0)
        total_notl = float(ws.get("total_notional") or 0)
        margin_used = float(ws.get("margin_used") or 0)
        margin_ratio = (margin_used / av * 100) if av else 0
        fetched   = (ws.get("fetched_at") or "")[:16].replace("T", " ")

        long_total  = sum(float(p.get("notional") or 0) for p in positions if p.get("side") == "long")
        short_total = sum(float(p.get("notional") or 0) for p in positions if p.get("side") == "short")
        ls_total    = long_total + short_total
        long_pct    = (long_total / ls_total * 100) if ls_total else 0

        tier_col = TIER_COLOR.get(tier, "#8b949e")
        tier_bg  = TIER_BADGE_BG.get(tier, "rgba(139,148,158,0.12)")
        detail   = wallet_page(addr)

        # Coins being traded (compact)
        coins = " ".join(
            f'<span style="color:{"#3fb950" if p.get("side")=="long" else "#f85149"};font-size:0.78rem">{p.get("coin")}</span>'
            for p in positions[:6]
        ) or '<span style="color:#484f58">—</span>'

        # L/S mini bar
        if ls_total > 0:
            ls_cell = f"""
            <div style="display:flex;align-items:center;gap:5px;min-width:110px">
              <span style="color:#3fb950;font-size:0.75rem;width:28px">{long_pct:.0f}%</span>
              <div style="flex:1;height:5px;background:#21262d;border-radius:3px">
                <div style="width:{long_pct:.1f}%;height:100%;background:#3fb950;border-radius:3px"></div>
              </div>
              <span style="color:#f85149;font-size:0.75rem;width:28px;text-align:right">{100-long_pct:.0f}%</span>
            </div>"""
        else:
            ls_cell = '<span style="color:#484f58">—</span>'

        margin_color = "#f85149" if margin_ratio > 70 else "#f0883e" if margin_ratio > 40 else "#3fb950"

        rows += f"""
        <tr class="wallet-row" onclick="window.location='{detail}'" style="cursor:pointer">
          <td>
            <div style="display:flex;align-items:center;gap:8px">
              <span class="badge" style="background:{tier_bg};color:{tier_col}">{tier.upper()}</span>
              <span style="color:#e6edf3;font-weight:600">{label}</span>
              <span style="color:#484f58;font-size:0.75rem">{short_addr(addr)}</span>
            </div>
          </td>
          <td style="color:#e6edf3;font-weight:600" data-val="{av:.0f}">{fmt(av)}</td>
          <td style="color:#e6edf3;font-weight:600" data-val="{total_notl:.0f}">{fmt(total_notl)}</td>
          <td>{ls_cell}</td>
          <td style="color:{margin_color}" data-val="{margin_ratio:.1f}">{margin_ratio:.1f}%</td>
          <td style="color:#8b949e" data-val="{score:.1f}">{score:.1f}</td>
          <td>{coins}</td>
          <td style="color:#484f58;font-size:0.78rem">{len(positions)}</td>
          <td style="color:#484f58;font-size:0.75rem">{fetched}</td>
        </tr>"""

    return f"""
    <table class="wallet-table" id="walletTable">
      <thead>
        <tr>
          <th onclick="sortTable(0)">Wallet ↕</th>
          <th onclick="sortTable(1)">AV ↕</th>
          <th onclick="sortTable(2)">Notional ↕</th>
          <th>L / S Split</th>
          <th onclick="sortTable(4)">Margin% ↕</th>
          <th onclick="sortTable(5)">Score ↕</th>
          <th>Open Coins</th>
          <th onclick="sortTable(7)"># Pos ↕</th>
          <th>Updated</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>"""

def render_html(wallets: list[dict], agg: dict, generated_at: str) -> str:
    summary_html = render_summary(agg, generated_at)
    table_html   = render_wallet_table(wallets)
    wallet_count = agg["wallet_count"]
    active_count = agg["wallets_with_positions"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="120">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>🧠 Smart Money — HyperWhale</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background: #0d1117;
      color: #c9d1d9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
      font-size: 14px;
      min-height: 100vh;
    }}

    /* Nav */
    .nav {{
      background: #161b22;
      border-bottom: 1px solid #21262d;
      padding: 12px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    .nav-brand {{
      font-size: 1.1rem;
      font-weight: 700;
      color: #e6edf3;
      text-decoration: none;
    }}
    .nav-links {{ display: flex; gap: 20px; }}
    .nav-links a {{
      color: #8b949e;
      text-decoration: none;
      font-size: 0.88rem;
      transition: color 0.2s;
    }}
    .nav-links a:hover {{ color: #e6edf3; }}
    .nav-links a.active {{ color: #58a6ff; }}
    .refresh-badge {{
      font-size: 0.78rem;
      color: #484f58;
      background: #21262d;
      padding: 3px 8px;
      border-radius: 20px;
    }}

    /* Layout */
    .container {{
      max-width: 1300px;
      margin: 0 auto;
      padding: 24px 20px;
    }}

    .page-title {{
      font-size: 1.4rem;
      font-weight: 700;
      color: #e6edf3;
      margin-bottom: 4px;
    }}
    .page-sub {{
      color: #8b949e;
      font-size: 0.88rem;
      margin-bottom: 20px;
    }}

    /* Summary Card */
    .summary-card {{
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 10px;
      padding: 20px 24px;
      margin-bottom: 24px;
    }}
    .summary-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 16px;
    }}
    .summary-title {{
      font-size: 1.1rem;
      font-weight: 700;
      color: #e6edf3;
    }}
    .summary-sub {{
      color: #8b949e;
      font-size: 0.82rem;
      margin-top: 4px;
    }}
    .summary-stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }}
    .stat-box {{
      background: #0d1117;
      border: 1px solid #21262d;
      border-radius: 8px;
      padding: 12px 14px;
    }}
    .stat-label {{
      color: #8b949e;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 4px;
    }}
    .stat-value {{
      font-size: 1.15rem;
      font-weight: 700;
      color: #e6edf3;
    }}

    /* Coin Table */
    .coin-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }}
    .coin-table th {{
      color: #484f58;
      text-align: left;
      padding: 6px 10px;
      border-bottom: 1px solid #21262d;
      font-weight: 500;
      text-transform: uppercase;
      font-size: 0.75rem;
      letter-spacing: 0.5px;
    }}
    .coin-table td {{
      padding: 8px 10px;
      border-bottom: 1px solid #161b22;
      color: #8b949e;
    }}
    .coin-table tbody tr:hover {{ background: #161b22; }}

    /* Wallet Grid */
    .wallet-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(580px, 1fr));
      gap: 16px;
    }}

    /* Wallet Card */
    .wallet-card {{
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 10px;
      padding: 16px 18px;
      transition: border-color 0.2s;
    }}
    .wallet-card:hover {{ border-color: #388bfd; }}

    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 12px;
    }}
    .wallet-label {{
      font-size: 1rem;
      font-weight: 700;
      color: #e6edf3;
      text-decoration: none;
    }}
    .wallet-label:hover {{ color: #58a6ff; }}

    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 20px;
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.5px;
    }}

    .card-stats {{
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 4px;
    }}
    .mini-stat {{ min-width: 70px; }}
    .mini-label {{
      color: #484f58;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }}
    .mini-value {{
      color: #e6edf3;
      font-weight: 600;
      font-size: 0.88rem;
      margin-top: 2px;
    }}

    /* Positions Table */
    .pos-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }}
    .pos-table th {{
      color: #484f58;
      text-align: left;
      padding: 5px 8px;
      border-bottom: 1px solid #21262d;
      font-weight: 500;
      text-transform: uppercase;
      font-size: 0.72rem;
      letter-spacing: 0.3px;
    }}
    .pos-table td {{
      padding: 7px 8px;
      border-bottom: 1px solid #0d1117;
    }}
    .pos-table tbody tr:last-child td {{ border-bottom: none; }}
    .pos-table tbody tr:hover {{ background: #1c2128; }}

    /* Events */
    .events-section {{
      margin-top: 12px;
      padding-top: 10px;
      border-top: 1px solid #21262d;
    }}
    .events-title {{
      color: #484f58;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 6px;
    }}
    .event-row {{
      display: flex;
      gap: 8px;
      align-items: center;
      padding: 3px 0;
    }}

    .detail-link {{
      color: #388bfd;
      text-decoration: none;
      font-size: 0.82rem;
    }}
    .detail-link:hover {{ text-decoration: underline; }}

    /* Wallet Table */
    .wallet-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 10px;
      overflow: hidden;
    }}
    .wallet-table th {{
      background: #1c2128;
      color: #8b949e;
      text-align: left;
      padding: 10px 14px;
      border-bottom: 1px solid #21262d;
      font-weight: 500;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }}
    .wallet-table th:hover {{ color: #e6edf3; }}
    .wallet-table td {{
      padding: 10px 14px;
      border-bottom: 1px solid #0d1117;
      vertical-align: middle;
    }}
    .wallet-row:last-child td {{ border-bottom: none; }}
    .wallet-row:hover {{ background: #1c2128 !important; }}

    /* Section divider */
    .section-header {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 0 0 14px;
    }}
    .section-title {{
      font-size: 1rem;
      font-weight: 600;
      color: #e6edf3;
    }}
    .section-count {{
      color: #8b949e;
      font-size: 0.82rem;
      background: #21262d;
      padding: 2px 8px;
      border-radius: 12px;
    }}
  </style>
</head>
<body>

<nav class="nav">
  <a href="smart_money.html" class="nav-brand">🐋 HyperWhale</a>
  <div class="nav-links">
    <a href="smart_money.html" class="active">Smart Money</a>
    <a href="bubble_map.html">Bubble Map</a>
    <a href="cex_sentiment.html">CEX Sentiment</a>
    <a href="liq_heatmap.html">Liq Heatmap</a>
  </div>
  <span class="refresh-badge">⟳ auto-refresh 2 min</span>
</nav>

<div class="container">
  <div class="page-title">🧠 Smart Money Dashboard</div>
  <div class="page-sub">
    Tracking {wallet_count} apex, whale &amp; shark wallets &nbsp;·&nbsp;
    {active_count} currently have open positions &nbsp;·&nbsp;
    Data updates every ~2 min
  </div>

  {summary_html}

  <div class="section-header">
    <div class="section-title">All Tracked Wallets</div>
    <div class="section-count">{wallet_count} wallets · click column headers to sort · click row for detail</div>
  </div>

  <div style="overflow-x:auto">
    {table_html}
  </div>
</div>

<script>
function sortTable(col) {{
  const table = document.getElementById('walletTable');
  const tbody = table.querySelector('tbody');
  const rows  = Array.from(tbody.querySelectorAll('tr'));
  const asc   = table.dataset.sortCol == col && table.dataset.sortDir == 'asc';
  rows.sort((a, b) => {{
    const aCell = a.cells[col];
    const bCell = b.cells[col];
    const aVal  = aCell.dataset.val !== undefined ? parseFloat(aCell.dataset.val) : aCell.innerText.trim();
    const bVal  = bCell.dataset.val !== undefined ? parseFloat(bCell.dataset.val) : bCell.innerText.trim();
    if (typeof aVal === 'number') return asc ? aVal - bVal : bVal - aVal;
    return asc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
  }});
  rows.forEach(r => tbody.appendChild(r));
  table.dataset.sortCol = col;
  table.dataset.sortDir = asc ? 'desc' : 'asc';
}}
</script>

</body>
</html>"""

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)

    # 1. Load registry (apex + whale only)
    registry = load_registry()
    if not registry:
        print("[WARN] No apex/whale wallets found in whale_addresses.json")
        return

    print(f"Loaded {len(registry)} apex+whale wallets from registry")

    # 2. Load DB data
    con = sqlite3.connect(str(DB_PATH))
    db_data = load_wallet_data(con, list(registry.keys()))
    con.close()

    print(f"Loaded DB data for {len(db_data)} wallets")

    # 3. Build wallet list — merge registry + DB, only wallets with DB data
    wallets = []
    for addr, reg in registry.items():
        if addr not in db_data:
            continue
        ws = db_data[addr]["ws"]
        total_notional = float(ws.get("total_notional") or 0)
        wallets.append({
            "address":       addr,
            "reg":           reg,
            "db":            db_data[addr],
            "total_notional": total_notional,
        })

    # Sort by total notional descending (most active first)
    wallets.sort(key=lambda w: w["total_notional"], reverse=True)

    print(f"Rendering {len(wallets)} wallet cards")

    # 4. Calculate aggregates
    agg = calc_aggregates(wallets)

    # 5. Render HTML
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = render_html(wallets, agg, generated_at)

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Written → {OUTPUT}")
    print(f"  Wallets: {agg['wallet_count']}  |  With positions: {agg['wallets_with_positions']}")
    print(f"  Total notional: {fmt(agg['total_notional'])}  |  L/S: {agg['long_pct']:.1f}% / {agg['short_pct']:.1f}%")


if __name__ == "__main__":
    main()
