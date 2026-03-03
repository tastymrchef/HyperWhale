"""
cluster_map.py — Live whale position cluster map.

Fetches current positions for all tracked whales (excluding bots) and renders
an interactive Plotly scatter chart showing:

  X-axis : Net directional bias  (-100% = pure short ↔ +100% = pure long)
  Y-axis : Total open notional (USD)
  Bubble : Sized by account value
  Color  : Tier (APEX=gold, WHALE=blue, SHARK=teal, DOLPHIN=green, SKIP=grey)
  Anomaly: Red ring around bubbles whose single largest position > $5M

Usage:
    cd C:\\Users\\Sahil\\HyperLiquid
    .venv\\Scripts\\python.exe scripts\\cluster_map.py

    # Custom output path:
    .venv\\Scripts\\python.exe scripts\\cluster_map.py --out reports/cluster_today.html

    # Change anomaly threshold:
    .venv\\Scripts\\python.exe scripts\\cluster_map.py --anomaly-threshold 3000000
"""

from __future__ import annotations

import argparse
import json
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "whale_addresses.json"
EXCLUSIONS_FILE = ROOT / "data" / "bot_exclusions.json"
DEFAULT_OUT = ROOT / "reports" / "cluster_map.html"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://api.hyperliquid.xyz/info"
DEFAULT_ANOMALY_THRESHOLD = 5_000_000   # $5M single position = anomaly ring

TIER_COLORS = {
    "apex":          "#FFD700",   # gold
    "whale":         "#4C8EDA",   # blue
    "dormant_whale": "#8A8A9A",   # grey-blue
    "shark":         "#2EC4B6",   # teal
    "dolphin":       "#48BB78",   # green
    "skip":          "#A0AEC0",   # light grey
}

TIER_ORDER = ["apex", "whale", "shark", "dolphin", "dormant_whale", "skip"]

TIER_EMOJI = {
    "apex":          "💎",
    "whale":         "🐋",
    "dormant_whale": "😴",
    "shark":         "🦈",
    "dolphin":       "🐬",
    "skip":          "·",
}

# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _post(payload: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            r = httpx.post(BASE_URL, json=payload, timeout=20)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                time.sleep(5)
            elif attempt == retries - 1:
                raise
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def fetch_state(address: str) -> dict:
    return _post({"type": "clearinghouseState", "user": address})


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def collect(whales: list[dict], excluded: set[str]) -> list[dict]:
    rows = []
    total = len(whales)

    for i, whale in enumerate(whales, start=1):
        addr = whale["address"]
        label = whale.get("label") or ""
        tier = whale.get("tier", "skip").lower()

        if addr.lower() in excluded:
            print(f"[{i:3d}/{total}]  {addr[:12]}…  SKIPPED (bot)")
            continue

        try:
            state = fetch_state(addr)
            ms = state.get("marginSummary", {})
            av = float(ms.get("accountValue", 0))
            positions = state.get("assetPositions", [])

            long_notional = 0.0
            short_notional = 0.0
            max_single = 0.0
            pos_details = []

            for ap in positions:
                p = ap.get("position", {})
                szi = float(p.get("szi", 0))
                pv = abs(float(p.get("positionValue", 0)))
                coin = p.get("coin", "?")
                upnl = float(p.get("unrealizedPnl", 0))
                entry = float(p.get("entryPx", 0))
                liq = p.get("liquidationPx")
                lev = p.get("leverage", {}).get("value", 1)

                if szi > 0:
                    long_notional += pv
                elif szi < 0:
                    short_notional += pv

                if pv > max_single:
                    max_single = pv

                pos_details.append({
                    "coin": coin,
                    "side": "LONG" if szi > 0 else "SHORT",
                    "notional": pv,
                    "upnl": upnl,
                    "entry": entry,
                    "liq": liq,
                    "leverage": lev,
                })

            total_notional = long_notional + short_notional

            # Net bias: +100 = fully long, -100 = fully short, 0 = balanced / flat
            if total_notional > 0:
                net_bias = ((long_notional - short_notional) / total_notional) * 100
            else:
                net_bias = 0.0

            rows.append({
                "address": addr,
                "label": label,
                "tier": tier,
                "account_value": av,
                "long_notional": long_notional,
                "short_notional": short_notional,
                "total_notional": total_notional,
                "net_bias": net_bias,
                "max_single_position": max_single,
                "whale_score": whale.get("whale_score", 0),
                "positions": pos_details,
                "is_flat": total_notional == 0,
            })

            direction = (
                "FLAT" if total_notional == 0
                else f"{'LONG' if net_bias > 0 else 'SHORT'} {abs(net_bias):.0f}%"
            )
            print(
                f"[{i:3d}/{total}]  {addr[:12]}…  {label or tier:22s}  "
                f"AV=${av:>12,.0f}  ntl=${total_notional:>12,.0f}  {direction}"
            )

        except Exception as exc:
            print(f"[{i:3d}/{total}]  {addr[:12]}…  ERROR: {exc}")

        time.sleep(0.25)

    return rows


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

def _fmt_usd(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:.1f}K"
    return f"${v:.0f}"


def _build_hover(row: dict) -> str:
    tier_em = TIER_EMOJI.get(row["tier"], "·")
    label = row["label"] or row["address"][:14] + "…"
    lines = [
        f"<b>{tier_em} {label}</b>  [{row['tier'].upper()}]",
        f"Score: {row['whale_score']:.0f}  |  AV: {_fmt_usd(row['account_value'])}",
        f"Net bias: {row['net_bias']:+.1f}%  ({'LONG' if row['net_bias'] > 0 else 'SHORT' if row['net_bias'] < 0 else 'FLAT'})",
        f"Long: {_fmt_usd(row['long_notional'])}  |  Short: {_fmt_usd(row['short_notional'])}",
        "─────────────────",
    ]
    # Top positions
    top = sorted(row["positions"], key=lambda p: -p["notional"])[:5]
    for p in top:
        upnl_str = f"  uPnL: {_fmt_usd(p['upnl'])}" if p["upnl"] != 0 else ""
        lines.append(f"  {p['side']:5s} {p['coin']:6s}  {_fmt_usd(p['notional'])} @ {p['leverage']}x{upnl_str}")
    if not top:
        lines.append("  <i>No open positions</i>")
    lines.append(f"<a href='https://app.hyperliquid.xyz/explorer/address/{row['address']}'>🔗 Explorer</a>")
    return "<br>".join(lines)


def build_chart(rows: list[dict], anomaly_threshold: float, generated_at: str) -> str:
    """Returns full HTML string of the interactive Plotly chart."""

    # Separate flat wallets — show them on X=0, Y=0 as tiny grey dots
    active = [r for r in rows if not r["is_flat"]]
    flat = [r for r in rows if r["is_flat"]]

    # Build one trace per tier (for legend grouping)
    traces_js = []

    for tier in TIER_ORDER:
        tier_rows = [r for r in active if r["tier"] == tier]
        if not tier_rows:
            continue

        color = TIER_COLORS.get(tier, "#999")
        name = f"{TIER_EMOJI.get(tier, '')} {tier.replace('_', ' ').title()}"

        xs = [r["net_bias"] for r in tier_rows]
        ys = [r["total_notional"] for r in tier_rows]
        # Bubble size: sqrt-scale of AV, min 8 max 60
        sizes = [max(8, min(60, (r["account_value"] ** 0.42) / 400)) for r in tier_rows]
        texts = [r["label"] or r["address"][:10] + "…" for r in tier_rows]
        hovers = [_build_hover(r) for r in tier_rows]

        # Anomaly rings — separate trace with red border
        anomaly_rows = [r for r in tier_rows if r["max_single_position"] >= anomaly_threshold]
        if anomaly_rows:
            axs = [r["net_bias"] for r in anomaly_rows]
            ays = [r["total_notional"] for r in anomaly_rows]
            asizes = [max(8, min(60, (r["account_value"] ** 0.42) / 400)) + 8 for r in anomaly_rows]
            traces_js.append(f"""{{
  x: {json.dumps(axs)},
  y: {json.dumps(ays)},
  mode: 'markers',
  marker: {{ size: {json.dumps(asizes)}, color: 'rgba(0,0,0,0)',
             line: {{ color: '#FF4136', width: 2.5 }} }},
  hoverinfo: 'skip',
  showlegend: false,
  name: 'anomaly_ring'
}}""")

        traces_js.append(f"""{{
  x: {json.dumps(xs)},
  y: {json.dumps(ys)},
  mode: 'markers+text',
  name: {json.dumps(name)},
  text: {json.dumps(texts)},
  textposition: 'top center',
  textfont: {{ size: 9, color: '#ccc' }},
  customdata: {json.dumps(hovers)},
  hovertemplate: '%{{customdata}}<extra></extra>',
  marker: {{
    size: {json.dumps(sizes)},
    color: {json.dumps([color] * len(tier_rows))},
    opacity: 0.85,
    line: {{ color: 'rgba(255,255,255,0.3)', width: 1 }}
  }}
}}""")

    # Flat wallets trace
    if flat:
        flat_hovers = [_build_hover(r) for r in flat]
        flat_texts = [r["label"] or r["address"][:10] + "…" for r in flat]
        traces_js.append(f"""{{
  x: {json.dumps([0.0] * len(flat))},
  y: {json.dumps([0.0] * len(flat))},
  mode: 'markers',
  name: '😴 Flat / No Positions',
  text: {json.dumps(flat_texts)},
  customdata: {json.dumps(flat_hovers)},
  hovertemplate: '%{{customdata}}<extra></extra>',
  marker: {{
    size: 8,
    color: '#555',
    opacity: 0.5,
    symbol: 'x'
  }}
}}""")

    traces_str = ",\n".join(traces_js)

    # Stats for subtitle
    n_active = len(active)
    n_flat = len(flat)
    n_long = sum(1 for r in active if r["net_bias"] > 10)
    n_short = sum(1 for r in active if r["net_bias"] < -10)
    n_neutral = n_active - n_long - n_short
    n_anomaly = sum(1 for r in rows if r["max_single_position"] >= anomaly_threshold)
    total_long_ntl = sum(r["long_notional"] for r in rows)
    total_short_ntl = sum(r["short_notional"] for r in rows)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>HyperWhale — Cluster Map</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  body {{ margin: 0; background: #0d1117; color: #e6edf3; font-family: 'Segoe UI', sans-serif; }}
  #header {{ padding: 18px 24px 6px; }}
  h1 {{ margin: 0; font-size: 22px; color: #58a6ff; letter-spacing: 1px; }}
  .sub {{ font-size: 13px; color: #8b949e; margin-top: 4px; }}
  .stats {{ display: flex; gap: 28px; padding: 10px 24px; font-size: 13px; border-bottom: 1px solid #21262d; }}
  .stat {{ display: flex; flex-direction: column; }}
  .stat-val {{ font-size: 20px; font-weight: 700; color: #e6edf3; }}
  .stat-lbl {{ color: #8b949e; font-size: 11px; margin-top: 2px; }}
  .long  {{ color: #3fb950; }}
  .short {{ color: #f85149; }}
  .anomaly {{ color: #FF4136; }}
  #chart {{ width: 100%; height: calc(100vh - 160px); }}
  .legend-note {{ padding: 4px 24px 8px; font-size: 11px; color: #555; }}
</style>
</head>
<body>
<div id="header">
  <h1>🐋 HyperWhale — Live Cluster Map</h1>
  <div class="sub">Generated {generated_at} UTC &nbsp;·&nbsp; {len(rows)} wallets tracked (bots excluded)</div>
</div>
<div class="stats">
  <div class="stat"><span class="stat-val">{n_active}</span><span class="stat-lbl">Active</span></div>
  <div class="stat"><span class="stat-val">{n_flat}</span><span class="stat-lbl">Flat / Waiting</span></div>
  <div class="stat"><span class="stat-val long">{n_long}</span><span class="stat-lbl">Net Long (&gt;10%)</span></div>
  <div class="stat"><span class="stat-val short">{n_short}</span><span class="stat-lbl">Net Short (&gt;10%)</span></div>
  <div class="stat"><span class="stat-val">{n_neutral}</span><span class="stat-lbl">Neutral</span></div>
  <div class="stat"><span class="stat-val anomaly">{n_anomaly}</span><span class="stat-lbl">Anomalies (≥${anomaly_threshold/1e6:.0f}M pos)</span></div>
  <div class="stat"><span class="stat-val long">{_fmt_usd(total_long_ntl)}</span><span class="stat-lbl">Total Long Notional</span></div>
  <div class="stat"><span class="stat-val short">{_fmt_usd(total_short_ntl)}</span><span class="stat-lbl">Total Short Notional</span></div>
</div>
<div id="chart"></div>
<div class="legend-note">
  Bubble size = account value &nbsp;·&nbsp; 
  X-axis = net directional bias (−100% pure short ↔ +100% pure long) &nbsp;·&nbsp; 
  <span style="color:#FF4136">⬤ red ring</span> = single position ≥ ${_fmt_usd(anomaly_threshold)} (anomaly)
  &nbsp;·&nbsp; Flat wallets shown as × at origin
</div>
<script>
const traces = [
  {traces_str}
];

const layout = {{
  paper_bgcolor: '#0d1117',
  plot_bgcolor: '#161b22',
  font: {{ color: '#e6edf3', size: 11 }},
  xaxis: {{
    title: {{ text: 'Net Directional Bias  (← Short  |  Long →)', font: {{ size: 13 }} }},
    range: [-110, 110],
    zeroline: true,
    zerolinecolor: '#30363d',
    zerolinewidth: 2,
    gridcolor: '#21262d',
    ticksuffix: '%',
  }},
  yaxis: {{
    title: {{ text: 'Total Open Notional (USD)', font: {{ size: 13 }} }},
    tickprefix: '$',
    tickformat: '.2s',
    gridcolor: '#21262d',
    type: 'log',
  }},
  legend: {{
    bgcolor: '#161b22',
    bordercolor: '#30363d',
    borderwidth: 1,
    x: 1.01, y: 1,
    xanchor: 'left',
  }},
  hoverlabel: {{
    bgcolor: '#161b22',
    bordercolor: '#30363d',
    font: {{ size: 12, color: '#e6edf3' }},
    align: 'left',
  }},
  margin: {{ t: 10, b: 60, l: 80, r: 200 }},
  shapes: [
    // Zero line shading hints
    {{ type: 'rect', x0: -110, x1: 0, y0: 0, y1: 1, yref: 'paper',
       fillcolor: 'rgba(248,81,73,0.03)', line: {{ width: 0 }} }},
    {{ type: 'rect', x0: 0, x1: 110, y0: 0, y1: 1, yref: 'paper',
       fillcolor: 'rgba(63,185,80,0.03)', line: {{ width: 0 }} }},
  ],
  annotations: [
    {{ x: -55, y: 1.02, xref: 'x', yref: 'paper', text: '← BEARS', showarrow: false,
       font: {{ color: '#f85149', size: 12 }} }},
    {{ x: 55, y: 1.02, xref: 'x', yref: 'paper', text: 'BULLS →', showarrow: false,
       font: {{ color: '#3fb950', size: 12 }} }},
  ],
}};

const config = {{
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['lasso2d', 'select2d'],
  toImageButtonOptions: {{ format: 'png', filename: 'hyperwhale_cluster_map', scale: 2 }},
}};

Plotly.newPlot('chart', traces, layout, config);
</script>
</body>
</html>"""

    return html


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate live whale cluster map.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output HTML path")
    parser.add_argument(
        "--anomaly-threshold", type=float, default=DEFAULT_ANOMALY_THRESHOLD,
        help="Single position size (USD) that earns a red anomaly ring (default: $5M)"
    )
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open in browser")
    args = parser.parse_args()

    # Load data
    if not DATA_FILE.exists():
        raise SystemExit(f"[ERROR] {DATA_FILE} not found")

    whales = json.loads(DATA_FILE.read_text(encoding="utf-8"))["whales"]

    excluded: set[str] = set()
    if EXCLUSIONS_FILE.exists():
        exc_data = json.loads(EXCLUSIONS_FILE.read_text(encoding="utf-8"))
        excluded = {a.lower() for a in exc_data.get("addresses", [])}
        print(f"Loaded {len(excluded)} bot exclusions\n")

    print(f"Fetching live positions for {len(whales)} whales…\n")
    rows = collect(whales, excluded)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    html = build_chart(rows, args.anomaly_threshold, generated_at)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"\n✅ Cluster map saved → {args.out}")

    if not args.no_open:
        webbrowser.open(args.out.as_uri())
        print("🌐 Opening in browser…")


if __name__ == "__main__":
    main()
