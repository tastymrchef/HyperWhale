"""HyperWhale — main entry point.

Usage:
    python -m hyperwhale discover               Discover whales from leaderboard + vaults
    python -m hyperwhale discover --min-av=5M   Only wallets with $5M+ account value
    python -m hyperwhale discover --max=50      Cap at 50 new wallets
    python -m hyperwhale discover --new-only    Skip refreshing existing wallets
    python -m hyperwhale monitor                Start continuous position monitoring
    python -m hyperwhale monitor --once         Single poll cycle (for testing)
    python -m hyperwhale rescore-all            Re-fetch staking for every whale and re-score
    python -m hyperwhale status                 Show tracked whales and DB stats
    python -m hyperwhale test-api               Quick API connectivity test
"""

from __future__ import annotations

import sys
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.table import Table as RichTable

console = Console()


def cmd_test_api() -> None:
    """Quick test to verify Hyperliquid API connectivity."""
    from hyperwhale.data.collector import HyperliquidCollector

    console.print("\n[bold cyan]🔌 Testing Hyperliquid API connection...[/bold cyan]\n")
    collector = HyperliquidCollector()

    try:
        mids = collector.get_all_mids()
        console.print(f"[green]✓ API is reachable — got {len(mids)} asset mid-prices[/green]")

        # Show top 10 by price
        table = RichTable(title="Top 10 Assets by Mid Price")
        table.add_column("Coin", style="cyan")
        table.add_column("Mid Price", justify="right", style="green")

        sorted_mids = sorted(mids.items(), key=lambda x: float(x[1]), reverse=True)
        for coin, price in sorted_mids[:10]:
            table.add_row(coin, f"${float(price):,.2f}")

        console.print(table)
        collector.close()

    except Exception as e:
        console.print(f"[red]✗ API connection failed: {e}[/red]")
        sys.exit(1)


def cmd_discover() -> None:
    """Discover whale addresses from leaderboard + vault depositors."""
    from hyperwhale.data.collector import HyperliquidCollector
    from hyperwhale.data.whale_registry import WhaleRegistry
    from hyperwhale.data.discovery import WhaleDiscovery

    console.print("\n[bold cyan]🔍 Discovering whales...[/bold cyan]\n")

    registry = WhaleRegistry()
    collector = HyperliquidCollector()

    # Progress callback — prints to console
    def on_progress(msg: str) -> None:
        console.print(f"  [dim]{msg}[/dim]")

    discovery = WhaleDiscovery(registry, collector, on_progress=on_progress)

    # Parse CLI flags
    min_av = 1_000_000  # default $1M minimum
    max_new = 200       # default cap
    skip_existing = False

    for arg in sys.argv[2:]:
        if arg.startswith("--min-av="):
            min_av = float(arg.split("=")[1].replace(",", "").replace("_", ""))
        elif arg.startswith("--max="):
            max_new = int(arg.split("=")[1])
        elif arg == "--refresh":
            skip_existing = False  # refresh existing wallets too
        elif arg == "--new-only":
            skip_existing = True

    console.print(f"  Min AV: [bold]${min_av:,.0f}[/bold]  Max new: [bold]{max_new}[/bold]  "
                  f"Skip existing: [bold]{skip_existing}[/bold]\n")

    result = discovery.discover(
        min_account_value=min_av,
        leaderboard=True,
        vaults=True,
        skip_existing=skip_existing,
        max_new=max_new,
    )

    collector.close()

    # Summary table
    table = RichTable(title="Discovery Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="bold")
    table.add_row("Candidates found", str(result.candidates_found))
    table.add_row("Roles filtered (vaults/sub)", str(result.roles_filtered))
    table.add_row("Below minimum AV", str(result.below_minimum))
    table.add_row("API errors", str(result.api_errors))
    table.add_row("[green]New whales added[/green]", f"[green]{result.whales_added}[/green]")
    table.add_row("Existing updated", str(result.whales_updated))
    table.add_row("Duration", f"{result.duration_seconds}s")
    console.print(table)

    console.print(f"\n[bold green]Registry now has {registry.count} whales[/bold green]\n")

    # Show tier distribution
    from hyperwhale.models import WhaleTier
    for tier in WhaleTier:
        count = len(registry.by_tier(tier))
        if count > 0:
            console.print(f"  {tier.value.upper():>15s}: {count}")


def cmd_monitor(once: bool = False) -> None:
    """Start position monitoring."""
    from hyperwhale.alerts.telegram import TelegramAlerter
    from hyperwhale.tracker.position_monitor import PositionMonitor

    monitor = PositionMonitor()

    # Register Telegram alerter if credentials are configured in .env
    alerter = TelegramAlerter(registry=monitor.registry)
    if alerter._enabled:
        monitor.on_event(alerter)
        alerter.send_startup_message(whale_count=monitor.registry.count)
        console.print("[green]Telegram alerts enabled[/green]")
    else:
        console.print("[yellow]Telegram alerts disabled — set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in .env[/yellow]")

    if once:
        console.print("\n[bold cyan]🐋 Running single poll cycle...[/bold cyan]\n")
        events = monitor.poll_once()
        console.print(f"\n[bold green]Done — {len(events)} events detected[/bold green]")
        alerter.close()
    else:
        console.print("\n[bold cyan]🐋 Starting continuous monitoring...[/bold cyan]\n")
        try:
            monitor.run()
        finally:
            alerter.close()


def cmd_rescore_all() -> None:
    """Re-fetch staking discount for every whale in the registry and re-score."""
    from hyperwhale.data.collector import HyperliquidCollector
    from hyperwhale.data.whale_registry import WhaleRegistry

    registry = WhaleRegistry()
    collector = HyperliquidCollector()

    total = registry.count
    console.print(f"\n[bold cyan]♻  Re-scoring {total} whales with live staking data...[/bold cyan]\n")

    updated = 0
    errors = 0

    for i, whale in enumerate(list(registry.whales.values()), 1):
        addr = whale.address
        try:
            staking_discount = collector.get_staking_discount(addr)
            registry.rescore(
                address=addr,
                account_value=whale.account_value,
                total_notional=whale.total_notional,
                trade_count_30d=whale.trade_count_30d,
                staking_discount=staking_discount,
            )
            updated += 1

            tier_str = whale.staked_hype_tier
            if tier_str != "none":
                console.print(
                    f"  [{i}/{total}] [green]{addr[:10]}...[/green]  "
                    f"staking=[bold yellow]{tier_str}[/bold yellow]  "
                    f"discount={staking_discount:.1%}  score={whale.whale_score:.1f}"
                )
        except Exception as e:
            errors += 1
            logger.warning(f"Failed to rescore {addr}: {e}")

    registry.save()
    collector.close()

    console.print(f"\n[bold green]Done — {updated} whales rescored, {errors} errors.[/bold green]")
    console.print(f"[dim]Registry saved to {registry.filepath}[/dim]\n")

    # Print staking tier distribution
    from collections import Counter
    tiers = Counter(w.staked_hype_tier for w in registry.whales.values())
    console.print("[bold]Staking tier breakdown:[/bold]")
    for tier, count in sorted(tiers.items(), key=lambda x: x[0]):
        console.print(f"  {tier:>8s}: {count}")


def cmd_status() -> None:
    """Show current tracker status."""
    from hyperwhale.data.database import Database
    from hyperwhale.data.whale_registry import WhaleRegistry

    registry = WhaleRegistry()
    db = Database()

    # Whale table
    table = RichTable(title="🐋 HyperWhale — Tracked Wallets")
    table.add_column("Address", style="cyan")
    table.add_column("Label", style="green")
    table.add_column("Tier", style="yellow")
    table.add_column("Score", justify="right", style="bold")
    table.add_column("Account Value", justify="right")
    table.add_column("A / P / Act", justify="right", style="dim")
    table.add_column("Active", justify="center")

    for whale in sorted(
        registry.whales.values(), key=lambda w: w.whale_score, reverse=True
    ):
        table.add_row(
            f"{whale.address[:6]}...{whale.address[-4:]}",
            whale.label or "—",
            whale.tier.value.upper(),
            f"{whale.whale_score:.0f}",
            f"${whale.account_value:,.0f}" if whale.account_value > 0 else "—",
            f"{whale.account_score:.0f}/{whale.position_score:.0f}/{whale.activity_score:.0f}",
            "✓" if whale.is_active else "✗",
        )

    console.print(table)

    # DB stats
    counts = db.get_counts()
    console.print(f"\n[dim]Database: {counts}[/dim]\n")


def main() -> None:
    """CLI router."""
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<dim>{time:HH:mm:ss}</dim> | {message}")

    if len(sys.argv) < 2:
        console.print(__doc__)
        sys.exit(0)

    command = sys.argv[1].lower()

    if command == "test-api":
        cmd_test_api()
    elif command == "discover":
        cmd_discover()
    elif command == "monitor":
        once = "--once" in sys.argv
        cmd_monitor(once=once)
    elif command == "rescore-all":
        cmd_rescore_all()
    elif command == "status":
        cmd_status()
    else:
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
