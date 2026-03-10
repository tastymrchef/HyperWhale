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


SMART_MONEY_TIERS = {"apex", "whale", "shark", "dormant_whale"}

def load_wallet(con, address: str) -> dict | None:
    con.row_factory = sqlite3.Row

    # ── Latest snapshot from monitor (position_snapshots) ──────────────────
    snap = con.execute("""
        SELECT * FROM position_snapshots
        WHERE address = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (address,)).fetchone()
    if not snap:
        return None

    positions = json.loads(snap["positions_json"] or "[]")
    # sort by notional desc
    positions.sort(key=lambda p: float(p.get("notional_value") or 0), reverse=True)

    # ── AV history (all snapshots for this address) ─────────────────────────
    av_history = con.execute("""
        SELECT timestamp, account_value
        FROM position_snapshots
        WHERE address = ?
        ORDER BY timestamp ASC
    """, (address,)).fetchall()

    # ── Position history (last 20 snapshots, non-empty) ─────────────────────
    snap_history = con.execute("""
        SELECT timestamp, positions_json, account_value,
               total_margin_used, total_notional_position
        FROM position_snapshots
        WHERE address = ? AND positions_json != '[]' AND positions_json IS NOT NULL
        ORDER BY timestamp DESC LIMIT 20
    """, (address,)).fetchall()

    # ── Trade stats from trades table ───────────────────────────────────────
    trade_stats = con.execute("""
        SELECT
            SUM(CASE WHEN closed_pnl > 0 THEN 1 ELSE 0 END)  AS wins,
            SUM(CASE WHEN closed_pnl < 0 THEN 1 ELSE 0 END)  AS losses,
            SUM(CASE WHEN closed_pnl > 0 THEN closed_pnl ELSE 0 END) AS gross_profit,
            SUM(CASE WHEN closed_pnl < 0 THEN closed_pnl ELSE 0 END) AS gross_loss,
            SUM(closed_pnl)  AS total_realized_pnl,
            SUM(fee)         AS total_fees,
            COUNT(*)         AS total_trades
        FROM trades
        WHERE address = ? AND direction LIKE 'Close%'
    """, (address,)).fetchone()

    # ── 30-day trade stats ──────────────────────────────────────────────────
    trade_stats_30d = con.execute("""
        SELECT
            SUM(CASE WHEN closed_pnl > 0 THEN 1 ELSE 0 END)  AS wins,
            SUM(CASE WHEN closed_pnl < 0 THEN 1 ELSE 0 END)  AS losses,
            SUM(CASE WHEN closed_pnl > 0 THEN closed_pnl ELSE 0 END) AS gross_profit,
            SUM(CASE WHEN closed_pnl < 0 THEN closed_pnl ELSE 0 END) AS gross_loss,
            SUM(closed_pnl)  AS total_realized_pnl,
            SUM(fee)         AS total_fees,
            COUNT(*)         AS total_trades
        FROM trades
        WHERE address = ?
          AND direction LIKE 'Close%'
          AND timestamp >= datetime('now', '-30 days')
    """, (address,)).fetchone()

    # ── Total snapshots ─────────────────────────────────────────────────────
    snap_count = con.execute(
        "SELECT COUNT(*) FROM position_snapshots WHERE address=?", (address,)
    ).fetchone()[0]

    return {
        "snap":          dict(snap),
        "positions":     positions,
        "av_history":    [dict(r) for r in av_history],
        "snap_history":  [dict(r) for r in snap_history],
        "trade_stats":   dict(trade_stats),
        "trade_stats_30d": dict(trade_stats_30d),
        "snap_count":    snap_count,
    }


def render_html(address: str, data: dict) -> str:
    snap        = data["snap"]
    positions   = data["positions"]
    av_history  = data["av_history"]
    snap_count  = data["snap_count"]
    ts          = data["trade_stats"]
    ts30        = data["trade_stats_30d"]

    av           = float(snap.get("account_value") or 0)
    total_notl   = float(snap.get("total_notional_position") or 0)
    margin_used  = float(snap.get("total_margin_used") or 0)
    fetched      = (snap.get("timestamp") or "")[:19].replace("T", " ")

    # Tier/label from whale_addresses.json if available, else fallback
    tier  = "unknown"
    label = address[:16] + "..."
    score = 0
    try:
        import json as _json
        reg_path = Path(__file__).resolve().parent.parent / "data" / "whale_addresses.json"
        raw  = _json.loads(reg_path.read_text(encoding="utf-8"))
        # Structure: {"whales": [{address, label, tier, whale_score, ...}, ...]}
        whales_list = raw.get("whales", []) if isinstance(raw, dict) else raw
        reg  = {w["address"].lower(): w for w in whales_list if "address" in w}
        entry = reg.get(address.lower(), {})
        tier  = entry.get("tier", "unknown")
        label = entry.get("label") or label
        score = entry.get("whale_score", 0)
    except Exception as e:
        pass
    tier_col = TIER_COLOR.get(tier, "#8b949e")

    # Long / short totals
    long_total  = sum(float(p.get("notional_value") or 0) for p in positions if p.get("side") == "long")
    short_total = sum(float(p.get("notional_value") or 0) for p in positions if p.get("side") == "short")
    ls_total    = long_total + short_total
    long_pct    = (long_total / ls_total * 100) if ls_total else 0

    # AV chart data
    av_labels = json.dumps([r["timestamp"][:16].replace("T", " ") for r in av_history])
    av_values = json.dumps([round(float(r["account_value"] or 0), 2) for r in av_history])

    # Trade stats helpers
    def _ts(d, key): return d.get(key) or 0
    wins_all    = int(_ts(ts, "wins"));    losses_all  = int(_ts(ts, "losses"))
    wins_30d    = int(_ts(ts30, "wins"));  losses_30d  = int(_ts(ts30, "losses"))
    total_all   = wins_all + losses_all;   total_30d   = wins_30d + losses_30d
    wr_all      = (wins_all / total_all * 100) if total_all else None
    wr_30d      = (wins_30d / total_30d * 100) if total_30d else None
    rpnl_all    = _ts(ts, "total_realized_pnl")
    rpnl_30d    = _ts(ts30, "total_realized_pnl")
    gp_all      = _ts(ts, "gross_profit");  gl_all = _ts(ts, "gross_loss")
    gp_30d      = _ts(ts30, "gross_profit"); gl_30d = _ts(ts30, "gross_loss")
    fees_all    = _ts(ts, "total_fees")
    pf_all      = abs(gp_all / gl_all) if gl_all else None   # profit factor
    total_tracked = int(_ts(ts, "total_trades"))  # all trades (open+close) tracked in DB

    def wr_color(wr):
        if wr is None: return "#8b949e"
        return "#3fb950" if wr >= 55 else "#f0883e" if wr >= 45 else "#f85149"

    def wr_fmt(wr, wins, losses, n_tracked):
        if wr is None: return '<span style="color:#8b949e">—</span>'
        result = f'<span style="color:{wr_color(wr)};font-weight:700">{wr:.1f}%</span> <span style="color:#8b949e;font-size:11px">({wins}W / {losses}L)</span>'
        if n_tracked < 500:
            result += f' <span title="Only {n_tracked} trades tracked — history may be incomplete" style="color:#f0883e;font-size:10px;cursor:help">⚠ {n_tracked} trades</span>'
        return result

    # Current positions table
    pos_rows = ""
    if positions:
        for p in positions:
            side      = p.get("side", "")
            side_col  = "#3fb950" if side == "long" else "#f85149"
            lev_type  = p.get("leverage_type", "cross")
            lev_icon  = "⊕" if lev_type == "cross" else "✕"
            lev_color = "#8b949e" if lev_type == "cross" else "#f0883e"
            lev_title = "Cross margin" if lev_type == "cross" else "Isolated margin"
            coin      = p.get("coin", "")
            notional  = float(p.get("notional_value") or 0)
            upnl      = float(p.get("unrealized_pnl") or 0)
            entry     = p.get("entry_price")
            liq       = p.get("liquidation_price")
            lev       = p.get("leverage")
            liq_str   = f"${float(liq):,.4g}" if liq else "—"
            entry_str = f"${float(entry):,.4g}" if entry else "—"
            pos_rows += f"""
            <tr>
                <td class="mono">{coin}</td>
                <td style="color:{side_col};font-weight:600">{side.upper()}</td>
                <td>{fmt(notional)}</td>
                <td>{fmt_pnl(upnl)}</td>
                <td>{entry_str}</td>
                <td>{liq_str}</td>
                <td title="{lev_title}">{lev or '—'}x <span style="color:{lev_color}">{lev_icon}</span></td>
            </tr>"""
    else:
        pos_rows = '<tr><td colspan="7" style="text-align:center;color:#8b949e;padding:20px">No open positions</td></tr>'

    # Position history rows (from snap_history)
    hist_rows = ""
    for snap_row in data["snap_history"]:
        ts_label = snap_row["timestamp"][:16].replace("T", " ")
        hist_rows += f'<tr class="snap-header"><td colspan="5">{ts_label}  ·  AV {fmt(snap_row["account_value"])}</td></tr>'
        hist_positions = json.loads(snap_row["positions_json"] or "[]")
        hist_positions.sort(key=lambda p: float(p.get("notional_value") or 0), reverse=True)
        for p in hist_positions:
            side     = p.get("side", "")
            side_col = "#3fb950" if side == "long" else "#f85149"
            lev_type = p.get("leverage_type", "cross")
            lev_icon = "⊕" if lev_type == "cross" else "✕"
            lev_color = "#8b949e" if lev_type == "cross" else "#f0883e"
            hist_rows += f"""
            <tr>
                <td class="mono" style="padding-left:20px">{p.get('coin','')}</td>
                <td style="color:{side_col}">{side.upper()}</td>
                <td>{fmt(p.get('notional_value'))}</td>
                <td>{fmt_pnl(p.get('unrealized_pnl'))}</td>
                <td>{p.get('leverage') or '—'}x <span style="color:{lev_color}">{lev_icon}</span></td>
            </tr>"""

    short_addr = address[:8] + "..." + address[-6:]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="120">
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
.header-card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px 28px;display:flex;flex-wrap:wrap;gap:24px;align-items:center}}
.avatar{{width:56px;height:56px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:700;flex-shrink:0}}
.wallet-info h2{{font-size:20px;font-weight:700;margin-bottom:4px}}
.wallet-info .addr{{font-size:12px;color:#8b949e;font-family:monospace}}
.tier-badge{{padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}}
.stats-row{{display:flex;flex-wrap:wrap;gap:12px;margin-left:auto}}
.stat-pill{{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:10px 16px;text-align:center;min-width:110px}}
.stat-pill .val{{font-size:18px;font-weight:700;color:#e6edf3}}
.stat-pill .lbl{{font-size:11px;color:#8b949e;margin-top:2px}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:12px;overflow:hidden}}
.card-title{{padding:16px 20px;border-bottom:1px solid #30363d;font-size:14px;font-weight:600;color:#e6edf3;display:flex;align-items:center;gap:8px}}
.card-body{{padding:20px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:8px 12px;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d;white-space:nowrap}}
td{{padding:9px 12px;border-bottom:1px solid #21262d}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#1c2128}}
.mono{{font-family:monospace;font-size:12px}}
.snap-header td{{background:#1c2128;color:#8b949e;font-size:11px;padding:6px 12px;font-style:italic}}
.chart-wrap{{position:relative;height:220px}}
.bias-bar{{height:8px;border-radius:4px;background:#30363d;overflow:hidden;margin-top:8px}}
.bias-fill{{height:100%;border-radius:4px}}
.bias-labels{{display:flex;justify-content:space-between;font-size:11px;color:#8b949e;margin-top:4px}}
.placeholder{{padding:40px 20px;text-align:center;color:#8b949e;font-size:13px}}
.ext-link{{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:#58a6ff;padding:6px 12px;border:1px solid #30363d;border-radius:6px;margin-left:auto}}
.ext-link:hover{{background:#1c2128}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.three-col{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px}}
@media(max-width:700px){{.two-col,.three-col{{grid-template-columns:1fr}}}}
.pnl-panel{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}}
.pnl-box{{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:14px 16px}}
.pnl-box .pval{{font-size:16px;font-weight:700;color:#e6edf3;margin-bottom:4px}}
.pnl-box .plbl{{font-size:11px;color:#8b949e}}
.tab-btn{{background:none;border:none;color:#8b949e;font-size:12px;cursor:pointer;padding:4px 10px;border-radius:4px}}
.tab-btn.active{{background:#21262d;color:#e6edf3}}
</style>
</head>
<body>

<div class="topbar">
  <span class="back" onclick="history.back()">← Back</span>
  <h1>Wallet Profile</h1>
  <a class="ext-link" href="https://hypurrscan.io/address/{address}" target="_blank">
    View on Hypurrscan ↗
  </a>
</div>

<div class="page">

  <!-- HEADER CARD -->
  <div class="header-card">
    <div class="avatar" style="background:{tier_col}22;color:{tier_col}">{tier[0].upper() if tier != 'unknown' else '?'}</div>
    <div class="wallet-info">
      <h2>{label}</h2>
      <div class="addr">{address}</div>
      <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <span class="tier-badge" style="background:{tier_col}22;color:{tier_col}">{tier}</span>
        <span style="font-size:12px;color:#8b949e">Score: {score}</span>
        <span style="font-size:12px;color:#8b949e">· {snap_count} snapshots</span>
        <span style="font-size:12px;color:#8b949e">· Last updated {fetched}</span>
        {'<span style="font-size:11px;background:#3fb95022;color:#3fb950;padding:2px 8px;border-radius:10px;font-weight:600">⚡ Live ~2 min</span>' if tier in SMART_MONEY_TIERS else '<span style="font-size:11px;background:#8b949e22;color:#8b949e;padding:2px 8px;border-radius:10px">🕐 Hourly</span>'}
      </div>
    </div>
    <div class="stats-row">
      <div class="stat-pill">
        <div class="val">{fmt(av)}</div>
        <div class="lbl">Account Value</div>
      </div>
      <div class="stat-pill">
        <div class="val">{fmt(total_notl)}</div>
        <div class="lbl">Total Notional</div>
      </div>
      <div class="stat-pill">
        <div class="val" style="color:#3fb950">{fmt(long_total)}</div>
        <div class="lbl">Total Long</div>
      </div>
      <div class="stat-pill">
        <div class="val" style="color:#f85149">{fmt(short_total)}</div>
        <div class="lbl">Total Short</div>
      </div>
      <div class="stat-pill">
        <div class="val">{len(positions)}</div>
        <div class="lbl">Open Positions</div>
      </div>
    </div>
  </div>

  <!-- PnL STATS PANEL -->
  <div class="card">
    <div class="card-title">
      📊 Trade Performance
      <span style="margin-left:auto;display:flex;gap:4px">
        <span style="font-size:11px;color:#8b949e;align-self:center">All-time &nbsp;|&nbsp; 30d</span>
      </span>
    </div>
    <div class="card-body">
      <div class="pnl-panel">
        <div class="pnl-box">
          <div class="plbl">Win Rate (All-time)</div>
          <div class="pval" style="margin-top:6px">{wr_fmt(wr_all, wins_all, losses_all, total_tracked)}</div>
        </div>
        <div class="pnl-box">
          <div class="plbl">Win Rate (30d)</div>
          <div class="pval" style="margin-top:6px">{wr_fmt(wr_30d, wins_30d, losses_30d, total_tracked)}</div>
        </div>
        <div class="pnl-box">
          <div class="plbl">Realized PnL (All-time)</div>
          <div class="pval" style="margin-top:6px">{fmt_pnl(rpnl_all)}</div>
        </div>
        <div class="pnl-box">
          <div class="plbl">Realized PnL (30d)</div>
          <div class="pval" style="margin-top:6px">{fmt_pnl(rpnl_30d)}</div>
        </div>
        <div class="pnl-box">
          <div class="plbl">Gross Profit (All-time)</div>
          <div class="pval" style="color:#3fb950;margin-top:6px">{fmt(gp_all)}</div>
        </div>
        <div class="pnl-box">
          <div class="plbl">Gross Loss (All-time)</div>
          <div class="pval" style="color:#f85149;margin-top:6px">{fmt(gl_all)}</div>
        </div>
        <div class="pnl-box">
          <div class="plbl">Profit Factor</div>
          <div class="pval" style="margin-top:6px">{'<span style="color:#3fb950">'+f'{pf_all:.2f}x</span>' if pf_all and pf_all >= 1 else ('<span style="color:#f85149">'+f'{pf_all:.2f}x</span>' if pf_all else '—')}</div>
        </div>
        <div class="pnl-box">
          <div class="plbl">Total Fees Paid</div>
          <div class="pval" style="color:#f0883e;margin-top:6px">{fmt(fees_all)}</div>
        </div>
      </div>
    </div>
  </div>

  <!-- AV CHART + L/S BIAS -->
  <div class="two-col">
    <div class="card">
      <div class="card-title">📈 Account Value History</div>
      <div class="card-body">
        <div class="chart-wrap"><canvas id="avChart"></canvas></div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">⚖️ Long / Short Bias</div>
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
    <div class="card-title">📋 Current Open Positions</div>
    <div class="card-body" style="padding:0">
      <table>
        <thead>
          <tr><th>Coin</th><th>Side</th><th>Notional</th><th>Unrealised PnL</th><th>Entry</th><th>Liq Price</th><th>Leverage</th></tr>
        </thead>
        <tbody>{pos_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- POSITION HISTORY -->
  <div class="card">
    <div class="card-title">🕐 Position History <span style="font-size:11px;color:#8b949e;font-weight:400">last 20 snapshots</span></div>
    <div class="card-body" style="padding:0;max-height:400px;overflow-y:auto">
      <table>
        <thead>
          <tr><th>Coin</th><th>Side</th><th>Notional</th><th>uPnL</th><th>Leverage</th></tr>
        </thead>
        <tbody>{hist_rows if hist_rows else '<tr><td colspan="5" style="text-align:center;color:#8b949e;padding:20px">No history yet</td></tr>'}</tbody>
      </table>
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
      pointRadius: 2,
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
            "SELECT DISTINCT address FROM position_snapshots"
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
