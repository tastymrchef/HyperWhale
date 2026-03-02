"""HyperWhale Dashboard — FastAPI web server.

Run with:
    python -m hyperwhale.dashboard.app
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from hyperwhale.data.collector import HyperliquidCollector
from hyperwhale.data.database import Database
from hyperwhale.data.whale_registry import WhaleRegistry

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="HyperWhale", docs_url="/docs")

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Shared instances (created on startup)
db: Database | None = None
registry: WhaleRegistry | None = None
collector: HyperliquidCollector | None = None


@app.on_event("startup")
async def startup():
    global db, registry, collector
    db = Database()
    registry = WhaleRegistry()
    collector = HyperliquidCollector()
    logger.info(f"Dashboard started — tracking {registry.count} whales")


@app.on_event("shutdown")
async def shutdown():
    if collector:
        collector.close()


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/api/whales")
async def get_whales():
    """Return all tracked whales with their profiles."""
    whales = []
    for w in sorted(registry.whales.values(), key=lambda w: w.account_value, reverse=True):
        # Try to get latest snapshot for live position data
        snapshot = db.get_latest_snapshot(w.address)
        positions = []
        if snapshot and snapshot.positions:
            for p in snapshot.positions:
                positions.append({
                    "coin": p.coin,
                    "side": p.side.value,
                    "size": p.size,
                    "notional_value": p.notional_value,
                    "entry_price": p.entry_price,
                    "mark_price": p.mark_price,
                    "leverage": p.leverage,
                    "unrealized_pnl": p.unrealized_pnl,
                })

        whales.append({
            "address": w.address,
            "address_short": f"{w.address[:6]}...{w.address[-4:]}",
            "label": w.label or None,
            "tier": w.tier.value,
            "account_value": w.account_value,
            "whale_score": w.whale_score,
            "account_score": w.account_score,
            "position_score": w.position_score,
            "activity_score": w.activity_score,
            "trade_count_30d": w.trade_count_30d,
            "is_active": w.is_active,
            "positions": positions,
            "position_count": len(positions),
            "total_notional": sum(p["notional_value"] for p in positions),
            "total_pnl": sum(p["unrealized_pnl"] for p in positions),
        })
    return {"whales": whales}


@app.get("/api/events")
async def get_events(limit: int = 50):
    """Return recent position events."""
    events = db.get_recent_events(limit=limit)
    # Add emoji and description
    for e in events:
        addr = e["address"]
        e["address_short"] = f"{addr[:6]}...{addr[-4:]}"
        et = e["event_type"]
        if et == "position_opened":
            e["emoji"] = "🐋"
            e["color"] = "#22c55e"
        elif et == "position_closed":
            e["emoji"] = "🔴"
            e["color"] = "#ef4444"
        elif et == "position_increased":
            e["emoji"] = "📈"
            e["color"] = "#22c55e"
        elif et == "position_decreased":
            e["emoji"] = "📉"
            e["color"] = "#f97316"
        elif et == "leverage_changed":
            e["emoji"] = "⚙️"
            e["color"] = "#a78bfa"
        elif et == "new_coin_added":
            e["emoji"] = "🆕"
            e["color"] = "#38bdf8"
        else:
            e["emoji"] = "❓"
            e["color"] = "#94a3b8"
    return {"events": events}


@app.get("/api/stats")
async def get_stats():
    """Return dashboard statistics."""
    counts = db.get_counts()
    whale_list = list(registry.whales.values())
    active_whales = [w for w in whale_list if w.is_active]
    total_value = sum(w.account_value for w in active_whales)

    # Tier breakdown
    tier_counts = {}
    for w in active_whales:
        tier = w.tier.value.upper()
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    return {
        "total_whales": len(active_whales),
        "total_tracked_value": total_value,
        "total_snapshots": counts["snapshots"],
        "total_trades": counts["trades"],
        "total_events": counts["events"],
        "tier_breakdown": tier_counts,
    }


@app.get("/api/market")
async def get_market():
    """Return top asset mid-prices from Hyperliquid."""
    try:
        mids = collector.get_all_mids()
        top = sorted(mids.items(), key=lambda x: float(x[1]), reverse=True)[:20]
        return {
            "total_assets": len(mids),
            "top_assets": [{"coin": k, "price": float(v)} for k, v in top],
        }
    except Exception as e:
        return {"error": str(e), "total_assets": 0, "top_assets": []}


@app.get("/api/whale/{address}")
async def get_whale_detail(address: str):
    """Return detailed info for a specific whale."""
    whale = registry.get(address)
    if not whale:
        return {"error": "Whale not found"}

    snapshot = db.get_latest_snapshot(address)
    positions = []
    if snapshot:
        for p in snapshot.positions:
            positions.append({
                "coin": p.coin,
                "side": p.side.value,
                "size": p.size,
                "notional_value": p.notional_value,
                "entry_price": p.entry_price,
                "mark_price": p.mark_price,
                "leverage": p.leverage,
                "unrealized_pnl": p.unrealized_pnl,
                "margin_used": p.margin_used,
            })

    return {
        "address": whale.address,
        "label": whale.label,
        "tier": whale.tier.value,
        "account_value": whale.account_value,
        "whale_score": whale.whale_score,
        "account_score": whale.account_score,
        "position_score": whale.position_score,
        "activity_score": whale.activity_score,
        "trade_count_30d": whale.trade_count_30d,
        "positions": positions,
        "snapshot_count": db.get_snapshot_count(address),
        "trade_count": db.get_trade_count(address),
    }


@app.get("/api/poll")
async def poll_now():
    """Trigger a single poll cycle and return results."""
    from hyperwhale.tracker.position_monitor import PositionMonitor
    monitor = PositionMonitor(collector=collector, database=db, registry=registry)
    events = monitor.poll_once()
    return {
        "events_detected": len(events),
        "events": [
            {
                "address_short": f"{e.address[:6]}...{e.address[-4:]}",
                "coin": e.coin,
                "event_type": e.event_type.value,
                "description": e.description,
            }
            for e in events
        ],
    }


@app.post("/api/discover")
async def run_discovery(min_av: float = 1_000_000, max_new: int = 200):
    """Trigger a whale discovery run from the dashboard."""
    from hyperwhale.data.discovery import WhaleDiscovery

    progress_log: list[str] = []

    def on_progress(msg: str):
        progress_log.append(msg)

    discovery = WhaleDiscovery(registry, collector, on_progress=on_progress)
    result = discovery.discover(
        min_account_value=min_av,
        leaderboard=True,
        vaults=True,
        max_new=max_new,
    )

    return {
        "candidates_found": result.candidates_found,
        "roles_filtered": result.roles_filtered,
        "below_minimum": result.below_minimum,
        "api_errors": result.api_errors,
        "whales_added": result.whales_added,
        "whales_updated": result.whales_updated,
        "duration_seconds": result.duration_seconds,
        "total_whales": registry.count,
        "progress_log": progress_log,
    }


# ---------------------------------------------------------------------------
# Serve the dashboard HTML
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the main dashboard page."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>HyperWhale — static/index.html not found</h1>")


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.info("Starting HyperWhale Dashboard on http://localhost:8000")

    uvicorn.run(
        "hyperwhale.dashboard.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
