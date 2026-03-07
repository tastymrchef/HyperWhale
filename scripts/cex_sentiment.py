"""
cex_sentiment.py — Fetch CEX top-trader sentiment and generate comparison report.

Pulls the following from Binance and Bybit public APIs (no auth required):
  • Top-trader Long/Short account ratio   (who is long vs short among big accounts)
  • Open Interest                          (total money in futures)
  • Funding Rate                           (market pressure signal)

Compares against HyperLiquid whale bias from the current snapshot.

Coins fetched: top 15 coins by HL whale activity (from live_positions_snapshot.json)
               with fallback mapping to CEX symbols (e.g. HYPE has no CEX listing)

Output:
  data/cex_sentiment.json      — raw data for other scripts
  reports/cex_sentiment.html   — interactive HTML comparison report

Usage:
    cd C:\\Users\\Sahil\\HyperLiquid
    .venv\\Scripts\\python.exe scripts\\cex_sentiment.py
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT          = Path(__file__).resolve().parent.parent
SNAPSHOT_FILE = ROOT / "data" / "live_positions_snapshot.json"
OUT_JSON      = ROOT / "data" / "cex_sentiment.json"
OUT_HTML      = ROOT / "reports" / "cex_sentiment.html"
DB_PATH       = ROOT / "data" / "hyperwhale.db"

# ---------------------------------------------------------------------------
# Exchange endpoints (all public, no API key)
# ---------------------------------------------------------------------------

BINANCE_BASE  = "https://fapi.binance.com"
BYBIT_BASE    = "https://api.bybit.com"

# Coins that exist on HL but NOT on Binance/Bybit futures — skip CEX fetch
CEX_SKIP = {"HYPE", "PURR", "NEIRO", "FRIEND", "MON", "BLAST", "RENDER",
            "PUMP", "FARTCOIN", "LIT", "XPL", "PAXG", "ASTER"}

# Some coins use different symbols on CEX
CEX_SYMBOL_MAP = {
    "BTC":   "BTCUSDT",
    "ETH":   "ETHUSDT",
    "SOL":   "SOLUSDT",
    "ARB":   "ARBUSDT",
    "AVAX":  "AVAXUSDT",
    "LINK":  "LINKUSDT",
    "DOGE":  "DOGEUSDT",
    "XRP":   "XRPUSDT",
    "ADA":   "ADAUSDT",
    "MATIC": "MATICUSDT",
    "DOT":   "DOTUSDT",
    "LTC":   "LTCUSDT",
    "ATOM":  "ATOMUSDT",
    "UNI":   "UNIUSDT",
    "NEAR":  "NEARUSDT",
    "SUI":   "SUIUSDT",
    "APT":   "APTUSDT",
    "INJ":   "INJUSDT",
    "TIA":   "TIAUSDT",
    "WIF":   "WIFUSDT",
    "BONK":  "BONKUSDT",
    "PEPE":  "PEPEUSDT",
    "OP":    "OPUSDT",
    "SEI":   "SEIUSDT",
    "TRX":   "TRXUSDT",
    "BNB":   "BNBUSDT",
    "TON":   "TONUSDT",
    "JTO":   "JTOUSDT",
    "PYTH":  "PYTHUSDT",
    "W":     "WUSDT",
    "ENA":   "ENAUSDT",
    "ZEC":   "ZECUSDT",
    "TRUMP": "TRUMPUSDT",
    "AAVE":  "AAVEUSDT",
    "CRV":   "CRVUSDT",
    "LDO":   "LDOUSDT",
    "ICP":   "ICPUSDT",
    "FIL":   "FILUSDT",
    "GRT":   "GRTUSDT",
    "EIGEN": "EIGENUSDT",
    "PENGU": "PENGUUSDT",
    "MOVE":  "MOVEUSDT",
    "USUAL": "USUALUSDT",
    "FTM":   "FTMUSDT",
    "SNX":   "SNXUSDT",
    "COMP":  "COMPUSDT",
    "MKR":   "MKRUSDT",
}

# Bybit uses same symbol format but period param differs
BYBIT_SYMBOL_MAP = CEX_SYMBOL_MAP  # same USDT linear symbols

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def get(url: str, params: dict, retries: int = 3) -> dict | list | None:
    for attempt in range(retries):
        try:
            r = httpx.get(url, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                print(f"  [WARN] {url} failed: {e}")
                return None
            time.sleep(1.5 ** attempt)
    return None

# ---------------------------------------------------------------------------
# Binance fetchers
# ---------------------------------------------------------------------------

def binance_top_ls(symbol: str) -> dict | None:
    """Top-trader long/short account ratio (big accounts only)."""
    data = get(f"{BINANCE_BASE}/futures/data/topLongShortAccountRatio",
               {"symbol": symbol, "period": "1h", "limit": 1})
    if data and len(data) > 0:
        d = data[0]
        return {
            "long_pct":  round(float(d["longAccount"]) * 100, 1),
            "short_pct": round(float(d["shortAccount"]) * 100, 1),
            "ratio":     round(float(d["longShortRatio"]), 3),
        }
    return None

def binance_global_ls(symbol: str) -> dict | None:
    """Global (all traders) long/short ratio for comparison."""
    data = get(f"{BINANCE_BASE}/futures/data/globalLongShortAccountRatio",
               {"symbol": symbol, "period": "1h", "limit": 1})
    if data and len(data) > 0:
        d = data[0]
        return {
            "long_pct":  round(float(d["longAccount"]) * 100, 1),
            "short_pct": round(float(d["shortAccount"]) * 100, 1),
        }
    return None

def binance_oi(symbol: str) -> dict | None:
    """Open interest (total notional in futures)."""
    data = get(f"{BINANCE_BASE}/futures/data/openInterestHist",
               {"symbol": symbol, "period": "1h", "limit": 1})
    if data and len(data) > 0:
        d = data[0]
        return {
            "oi_contracts": float(d["sumOpenInterest"]),
            "oi_usd":       float(d["sumOpenInterestValue"]),
        }
    return None

def binance_funding(symbol: str) -> dict | None:
    """Current funding rate + mark price."""
    data = get(f"{BINANCE_BASE}/fapi/v1/premiumIndex", {"symbol": symbol})
    if data and "lastFundingRate" in data:
        fr = float(data["lastFundingRate"]) * 100  # convert to %
        return {
            "funding_rate": round(fr, 5),
            "mark_price":   float(data["markPrice"]),
        }
    return None

# ---------------------------------------------------------------------------
# Bybit fetchers
# ---------------------------------------------------------------------------

def bybit_top_ls(symbol: str) -> dict | None:
    """Bybit top-trader long/short buy/sell ratio."""
    data = get(f"{BYBIT_BASE}/v5/market/account-ratio",
               {"category": "linear", "symbol": symbol, "period": "1h", "limit": 1})
    if data and data.get("retCode") == 0:
        lst = data["result"]["list"]
        if lst:
            d = lst[0]
            buy = round(float(d["buyRatio"]) * 100, 1)
            sell = round(float(d["sellRatio"]) * 100, 1)
            return {"long_pct": buy, "short_pct": sell}
    return None

def bybit_oi(symbol: str) -> dict | None:
    """Bybit open interest (latest 1h bucket)."""
    data = get(f"{BYBIT_BASE}/v5/market/open-interest",
               {"category": "linear", "symbol": symbol, "intervalTime": "1h", "limit": 1})
    if data and data.get("retCode") == 0:
        lst = data["result"]["list"]
        if lst:
            return {"oi_contracts": float(lst[0]["openInterest"])}
    return None

def bybit_funding(symbol: str) -> dict | None:
    """Bybit current funding rate."""
    data = get(f"{BYBIT_BASE}/v5/market/tickers",
               {"category": "linear", "symbol": symbol})
    if data and data.get("retCode") == 0:
        lst = data["result"]["list"]
        if lst:
            fr = float(lst[0].get("fundingRate", 0)) * 100
            return {
                "funding_rate": round(fr, 5),
                "mark_price":   float(lst[0].get("markPrice", 0)),
            }
    return None

# ---------------------------------------------------------------------------
# HL whale bias from snapshot
# ---------------------------------------------------------------------------

def hl_bias_by_coin(snapshot: dict) -> dict[str, dict]:
    """Compute HL whale net L/S bias per coin from snapshot."""
    coin_L: dict[str, float] = defaultdict(float)
    coin_S: dict[str, float] = defaultdict(float)
    coin_wallets: dict[str, set] = defaultdict(set)

    for w in snapshot.get("wallets", []):
        tier = (w.get("tier") or "").lower()
        if tier not in ("apex", "whale", "shark", "dolphin", "dormant_whale"):
            continue
        for p in w.get("positions", []):
            coin = p["coin"]
            ntl  = abs(float(p.get("notional", 0)))
            if p["side"] == "long":
                coin_L[coin] += ntl
            else:
                coin_S[coin] += ntl
            coin_wallets[coin].add(w["address"])

    result = {}
    for coin in set(list(coin_L.keys()) + list(coin_S.keys())):
        L = coin_L[coin]
        S = coin_S[coin]
        tot = L + S
        if tot == 0:
            continue
        result[coin] = {
            "long_pct":   round(L / tot * 100, 1),
            "short_pct":  round(S / tot * 100, 1),
            "long_usd":   round(L),
            "short_usd":  round(S),
            "total_usd":  round(tot),
            "wallet_count": len(coin_wallets[coin]),
        }
    return result

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

# DDL is minimal here — full schema lives in store_snapshot.py
_CEX_BIAS_DDL = """
CREATE TABLE IF NOT EXISTS cex_bias (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at            TEXT NOT NULL,
    coin                  TEXT NOT NULL,
    mark_price            REAL,
    bn_top_long_pct       REAL,
    bn_all_long_pct       REAL,
    bn_funding_rate       REAL,
    bn_oi_usd             REAL,
    by_top_long_pct       REAL,
    by_funding_rate       REAL,
    by_oi_usd             REAL
);
CREATE INDEX IF NOT EXISTS idx_cex_bias_coin    ON cex_bias(coin);
CREATE INDEX IF NOT EXISTS idx_cex_bias_fetched ON cex_bias(fetched_at);
"""


def store_cex_bias(results: dict, fetched_at: str) -> int:
    """Append one row per coin into cex_bias table. Returns number of rows written."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(_CEX_BIAS_DDL)

    rows = []
    for coin, d in results.items():
        bn  = d.get("binance", {})
        by  = d.get("bybit",   {})

        bn_top  = bn.get("top_traders") or {}
        bn_all  = bn.get("all_traders") or {}
        bn_fund = bn.get("funding")     or {}
        bn_oi   = bn.get("open_interest") or {}

        by_top  = by.get("top_traders") or {}
        by_fund = by.get("funding")     or {}
        by_oi   = by.get("open_interest") or {}

        rows.append((
            fetched_at,
            coin,
            bn_fund.get("mark_price"),
            bn_top.get("long_pct"),
            bn_all.get("long_pct"),
            bn_fund.get("funding_rate"),
            bn_oi.get("oi_usd"),
            by_top.get("long_pct"),
            by_fund.get("funding_rate"),
            by_oi.get("oi_usd"),
        ))

    con.executemany(
        """INSERT INTO cex_bias
           (fetched_at, coin, mark_price,
            bn_top_long_pct, bn_all_long_pct, bn_funding_rate, bn_oi_usd,
            by_top_long_pct, by_funding_rate, by_oi_usd)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    con.commit()
    con.close()
    return len(rows)


def main() -> None:
    print("=" * 60)
    print("CEX Sentiment Fetcher")
    print("=" * 60)

    # Load snapshot
    if not SNAPSHOT_FILE.exists():
        raise SystemExit(f"[ERROR] {SNAPSHOT_FILE} not found — run fetch_snapshot.py first")
    snap = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))

    # Get top coins from HL snapshot (top 15 by wallet count)
    top_coins_raw = snap.get("top_coins", {})
    top_coins = [c for c, _ in sorted(top_coins_raw.items(), key=lambda x: -x[1])[:15]
                 if c not in CEX_SKIP]
    print(f"\nTop HL coins to fetch: {', '.join(top_coins)}\n")

    # HL whale bias
    hl_bias = hl_bias_by_coin(snap)

    # Fetch CEX data per coin
    results = {}
    for coin in top_coins:
        cex_sym = CEX_SYMBOL_MAP.get(coin)
        if not cex_sym:
            print(f"  {coin:8s}  — no CEX symbol mapping, skipping")
            continue

        print(f"  Fetching {coin:8s} ({cex_sym})…", end="  ")

        bn_top   = binance_top_ls(cex_sym)
        bn_glob  = binance_global_ls(cex_sym)
        bn_oi    = binance_oi(cex_sym)
        bn_fund  = binance_funding(cex_sym)
        time.sleep(0.3)  # respect rate limits

        by_top   = bybit_top_ls(cex_sym)
        by_oi    = bybit_oi(cex_sym)
        by_fund  = bybit_funding(cex_sym)
        time.sleep(0.3)

        hl = hl_bias.get(coin, {})

        results[coin] = {
            "coin":      coin,
            "cex_sym":   cex_sym,
            "hl":        hl,
            "binance": {
                "top_traders": bn_top,
                "all_traders": bn_glob,
                "open_interest": bn_oi,
                "funding": bn_fund,
            },
            "bybit": {
                "top_traders": by_top,
                "open_interest": by_oi,
                "funding": by_fund,
            },
        }

        # Quick print
        hl_l = hl.get("long_pct", 0)
        bn_l = bn_top["long_pct"] if bn_top else 0
        by_l = by_top["long_pct"] if by_top else 0
        fr   = bn_fund["funding_rate"] if bn_fund else 0
        print(f"HL={hl_l:.0f}%L  BN_top={bn_l:.0f}%L  BY={by_l:.0f}%L  FR={fr:+.4f}%")

    # Save JSON
    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "coins": results,
    }
    OUT_JSON.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\n✅ Saved JSON → {OUT_JSON}")

    # Persist to DB
    n = store_cex_bias(results, output["fetched_at"])
    print(f"✅ Stored {n} coin rows → hyperwhale.db (cex_bias table)")

    # Generate HTML report
    generate_html(output)
    print(f"✅ Saved HTML → {OUT_HTML}")


# ---------------------------------------------------------------------------
# HTML Report Generator
# ---------------------------------------------------------------------------

def _fmt_usd(v: float) -> str:
    if v >= 1e9: return f"${v/1e9:.2f}B"
    if v >= 1e6: return f"${v/1e6:.1f}M"
    if v >= 1e3: return f"${v/1e3:.1f}K"
    return f"${v:.0f}"

def _bias_label(long_pct: float) -> tuple[str, str]:
    """Returns (label, color) based on long %."""
    bias = long_pct - 50  # -50 to +50
    if   bias >=  25: return "STRONG LONG",  "#52e07c"
    elif bias >=  10: return "LEAN LONG",    "#a8f0c0"
    elif bias >=  -5: return "NEUTRAL",      "#8b949e"
    elif bias >= -20: return "LEAN SHORT",   "#f0a8a8"
    else:             return "STRONG SHORT", "#e05252"

def _fr_color(fr: float) -> str:
    if fr > 0.02:  return "#e05252"   # longs paying — bearish pressure
    if fr > 0:     return "#e09852"
    if fr > -0.02: return "#52a8e0"
    return "#52e07c"                   # shorts paying — bullish pressure

def generate_html(data: dict) -> None:
    coins   = data["coins"]
    fetched = data["fetched_at"][:19].replace("T", " ") + " UTC"

    rows_html = ""
    for coin, d in coins.items():
        hl   = d.get("hl", {})
        bn   = d.get("binance", {})
        by   = d.get("bybit", {})

        hl_l   = hl.get("long_pct", 0)
        hl_s   = hl.get("short_pct", 0)
        hl_tot = hl.get("total_usd", 0)
        hl_wc  = hl.get("wallet_count", 0)
        hl_lab, hl_col = _bias_label(hl_l)

        bn_top  = bn.get("top_traders") or {}
        bn_glob = bn.get("all_traders") or {}
        bn_oi   = bn.get("open_interest") or {}
        bn_fund = bn.get("funding") or {}

        by_top  = by.get("top_traders") or {}
        by_oi   = by.get("open_interest") or {}
        by_fund = by.get("funding") or {}

        bn_l   = bn_top.get("long_pct", 0)
        bn_s   = bn_top.get("short_pct", 0)
        bn_gl  = bn_glob.get("long_pct", 0)
        bn_lab, bn_col = _bias_label(bn_l)

        by_l   = by_top.get("long_pct", 0)
        by_s   = by_top.get("short_pct", 0)
        by_lab, by_col = _bias_label(by_l)

        bn_fr  = bn_fund.get("funding_rate", 0)
        by_fr  = by_fund.get("funding_rate", 0)
        mp     = bn_fund.get("mark_price") or by_fund.get("mark_price", 0)
        bn_oi_usd = bn_oi.get("oi_usd", 0)

        # Divergence highlight — HL vs Binance top traders
        hl_vs_bn = hl_l - bn_l
        div_color = ""
        div_label = ""
        if abs(hl_vs_bn) >= 20:
            if hl_vs_bn > 0:
                div_color = "#2a1a00"
                div_label = f"⚡ HL whales {hl_vs_bn:+.0f}% MORE LONG than Binance tops"
            else:
                div_color = "#1a002a"
                div_label = f"⚡ HL whales {hl_vs_bn:+.0f}% MORE SHORT than Binance tops"

        def bar(l_pct, s_pct, width=160):
            lw = round(l_pct / 100 * width)
            sw = width - lw
            return (
                f'<div style="display:flex;width:{width}px;height:10px;border-radius:3px;overflow:hidden;">'
                f'<div style="width:{lw}px;background:#52e07c;"></div>'
                f'<div style="width:{sw}px;background:#e05252;"></div>'
                f'</div>'
            )

        rows_html += f"""
        <tr style="background:{div_color or '#0d1117'};" class="coin-row" data-coin="{coin}">
          <td style="padding:10px 14px;font-size:14px;font-weight:700;color:#c9d1d9;white-space:nowrap;">
            {coin}
            {'<div style="font-size:10px;color:#FFD700;margin-top:2px;">' + div_label + '</div>' if div_label else ''}
          </td>
          <td style="padding:10px 14px;font-size:11px;color:#8b949e;">
            {'$' + f'{mp:,.0f}' if mp else '—'}
          </td>

          <!-- HL Whales -->
          <td style="padding:10px 14px;">
            <div style="color:{hl_col};font-size:12px;font-weight:700;">{hl_lab}</div>
            {bar(hl_l, hl_s)}
            <div style="font-size:11px;color:#8b949e;margin-top:3px;">{hl_l:.0f}%L · {hl_s:.0f}%S · {hl_wc} wallets · {_fmt_usd(hl_tot)}</div>
          </td>

          <!-- Binance Top Traders -->
          <td style="padding:10px 14px;">
            {'<div style="color:' + bn_col + ';font-size:12px;font-weight:700;">' + bn_lab + '</div>' + bar(bn_l, bn_s) + '<div style="font-size:11px;color:#8b949e;margin-top:3px;">' + f'{bn_l:.0f}%L · {bn_s:.0f}%S (all:{bn_gl:.0f}%L)' + '</div>' if bn_l else '<span style="color:#444;font-size:11px;">No data</span>'}
          </td>

          <!-- Bybit Top Traders -->
          <td style="padding:10px 14px;">
            {'<div style="color:' + by_col + ';font-size:12px;font-weight:700;">' + by_lab + '</div>' + bar(by_l, by_s) + '<div style="font-size:11px;color:#8b949e;margin-top:3px;">' + f'{by_l:.0f}%L · {by_s:.0f}%S' + '</div>' if by_l else '<span style="color:#444;font-size:11px;">No data</span>'}
          </td>

          <!-- Funding Rate -->
          <td style="padding:10px 14px;text-align:center;">
            <div style="color:{_fr_color(bn_fr)};font-size:13px;font-weight:700;">{f'{bn_fr:+.4f}%' if bn_fr else '—'}</div>
            <div style="font-size:10px;color:#555;">Binance</div>
            <div style="color:{_fr_color(by_fr)};font-size:12px;font-weight:600;margin-top:2px;">{f'{by_fr:+.4f}%' if by_fr else '—'}</div>
            <div style="font-size:10px;color:#555;">Bybit</div>
          </td>

          <!-- Open Interest -->
          <td style="padding:10px 14px;text-align:right;font-size:12px;color:#8b949e;">
            {_fmt_usd(bn_oi_usd) if bn_oi_usd else '—'}
          </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CEX Sentiment — HyperWhale</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{
  background: #0d1117; color: #c9d1d9;
  font-family: 'Segoe UI', sans-serif; min-height: 100vh;
}}
#header {{
  padding: 18px 28px 10px;
  border-bottom: 1px solid #21262d;
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 12px;
}}
#header h1 {{ font-size: 20px; font-weight: 800; color: #fff; }}
#header .sub {{ font-size: 12px; color: #666; }}
#legend {{
  display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
  padding: 10px 28px; border-bottom: 1px solid #21262d;
  font-size: 11px; color: #8b949e;
}}
.leg {{ display: flex; align-items: center; gap: 5px; }}
.leg-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
#filter-bar {{
  display: flex; align-items: center; gap: 10px; padding: 10px 28px;
  border-bottom: 1px solid #21262d; flex-wrap: wrap;
}}
.filter-btn {{
  background: #161b22; border: 1px solid #21262d; color: #8b949e;
  border-radius: 5px; padding: 4px 12px; font-size: 12px; cursor: pointer;
}}
.filter-btn.active, .filter-btn:hover {{
  background: #388bfd22; border-color: #388bfd; color: #fff;
}}
#table-wrap {{
  overflow-x: auto; padding: 0 0 40px 0;
}}
table {{
  width: 100%; border-collapse: collapse; min-width: 900px;
}}
thead th {{
  padding: 10px 14px; font-size: 11px; font-weight: 700;
  color: #8b949e; text-align: left; text-transform: uppercase;
  letter-spacing: .5px; border-bottom: 1px solid #21262d;
  background: #0d1117; position: sticky; top: 0; z-index: 1;
}}
.coin-row {{ border-bottom: 1px solid #161b22; transition: background .15s; }}
.coin-row:hover {{ background: #161b22 !important; }}
.coin-row.hidden {{ display: none; }}
#explain-box {{
  margin: 16px 28px;
  background: #161b22; border: 1px solid #21262d; border-radius: 6px;
  padding: 14px 18px; font-size: 12px; color: #8b949e; line-height: 1.7;
}}
#explain-box strong {{ color: #c9d1d9; }}
</style>
</head>
<body>

<div id="header">
  <div>
    <h1>📊 CEX Sentiment vs HL Whales</h1>
    <div class="sub">HyperLiquid whale bias compared with Binance &amp; Bybit top-trader positioning</div>
  </div>
  <div class="sub">Updated: {fetched}</div>
</div>

<div id="explain-box">
  <strong>How to read this:</strong>
  <strong>HL Whales</strong> = all tracked wallets on HyperLiquid (apex/whale/shark/dolphin).
  <strong>Binance Top Traders</strong> = accounts with the largest positions on Binance Futures (public endpoint, no auth).
  <strong>Bybit</strong> = same concept on Bybit.
  <strong>Funding Rate</strong> = negative means shorts pay longs (bullish pressure), positive means longs pay shorts (bearish pressure).
  <strong>⚡ Divergence</strong> = highlighted when HL whales differ from Binance top traders by 20%+ — potential edge signal.
</div>

<div id="filter-bar">
  <span style="font-size:11px;color:#555;font-weight:600;">SHOW:</span>
  <button class="filter-btn active" data-filter="all">ALL</button>
  <button class="filter-btn" data-filter="diverge">⚡ DIVERGENCE ONLY</button>
  <button class="filter-btn" data-filter="hl-long">HL LONG BIAS</button>
  <button class="filter-btn" data-filter="hl-short">HL SHORT BIAS</button>
</div>

<div id="legend">
  <div class="leg"><div class="leg-dot" style="background:#52e07c"></div> Long</div>
  <div class="leg"><div class="leg-dot" style="background:#e05252"></div> Short</div>
  <div class="leg" style="color:#FFD700"><div class="leg-dot" style="background:#FFD700"></div> ⚡ Divergence ≥20%</div>
  <div class="leg">Funding <span style="color:#52e07c;margin-left:4px;">negative = bullish</span> · <span style="color:#e05252;margin-left:4px;">positive = bearish</span></div>
</div>

<div id="table-wrap">
<table>
  <thead>
    <tr>
      <th>Coin</th>
      <th>Mark Price</th>
      <th>🐋 HL Whales</th>
      <th>🟡 Binance Top Traders</th>
      <th>🟠 Bybit Top Traders</th>
      <th>Funding Rate</th>
      <th>BN Open Interest</th>
    </tr>
  </thead>
  <tbody id="tbody">
    {rows_html}
  </tbody>
</table>
</div>

<script>
document.querySelectorAll('.filter-btn').forEach(function(btn) {{
  btn.addEventListener('click', function() {{
    document.querySelectorAll('.filter-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    btn.classList.add('active');
    var f = btn.dataset.filter;
    document.querySelectorAll('.coin-row').forEach(function(row) {{
      var coin = row.dataset.coin;
      var bg   = row.style.background;
      var hlLong  = parseFloat(row.querySelector('td:nth-child(3) div')?.textContent) || 0;
      var isDivg  = bg && bg !== 'rgb(13, 17, 23)' && bg !== '';
      if (f === 'all') {{
        row.classList.remove('hidden');
      }} else if (f === 'diverge') {{
        row.classList.toggle('hidden', !isDivg);
      }} else if (f === 'hl-long') {{
        var label = row.querySelector('td:nth-child(3) div')?.textContent || '';
        row.classList.toggle('hidden', !(label.includes('LONG')));
      }} else if (f === 'hl-short') {{
        var label = row.querySelector('td:nth-child(3) div')?.textContent || '';
        row.classList.toggle('hidden', !(label.includes('SHORT')));
      }}
    }});
  }});
}});
</script>
</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
