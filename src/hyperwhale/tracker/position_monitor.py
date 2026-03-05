"""Position monitor — continuously polls whale positions and detects changes.

This is the main loop that drives Phase 1 of HyperWhale:
  1. Poll each whale's positions from Hyperliquid API
  2. Save snapshots to database
  3. Run change detection
  4. Log/alert on significant events
"""

from __future__ import annotations

import time
from datetime import datetime

from loguru import logger
from rich.console import Console
from rich.table import Table as RichTable

from hyperwhale.config import settings
from hyperwhale.data.collector import HyperliquidCollector
from hyperwhale.data.database import Database
from hyperwhale.data.whale_registry import WhaleRegistry
from hyperwhale.tracker.change_detector import ChangeDetector
from hyperwhale.models import PositionEvent


console = Console()


class PositionMonitor:
    """Continuously monitors whale positions and detects changes."""

    def __init__(
        self,
        collector: HyperliquidCollector | None = None,
        database: Database | None = None,
        registry: WhaleRegistry | None = None,
        change_detector: ChangeDetector | None = None,
    ) -> None:
        self.collector = collector or HyperliquidCollector()
        self.db = database or Database()
        self.registry = registry or WhaleRegistry()
        self.detector = change_detector or ChangeDetector()

        # Callbacks for events (alerts, dashboard, etc.)
        self._event_callbacks: list = []

        logger.info(
            f"PositionMonitor initialized — tracking {self.registry.count} whales"
        )

    def on_event(self, callback) -> None:
        """Register a callback that receives PositionEvent objects."""
        self._event_callbacks.append(callback)

    def _notify(self, event: PositionEvent) -> None:
        """Notify all registered callbacks about an event."""
        for cb in self._event_callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    # ------------------------------------------------------------------
    # Single poll cycle
    # ------------------------------------------------------------------

    def poll_once(self) -> list[PositionEvent]:
        """Poll all tracked whales once and return detected events."""
        addresses = self.registry.active_addresses
        if not addresses:
            logger.warning("No active whale addresses to monitor")
            return []

        all_events: list[PositionEvent] = []
        errors = 0

        for addr in addresses:
            try:
                # 1. Fetch current snapshot from API
                new_snapshot = self.collector.fetch_position_snapshot(addr)

                # 2. Update whale profile with latest account value
                self.registry.update_account_value(addr, new_snapshot.account_value)

                # 3. Get previous snapshot from DB
                old_snapshot = self.db.get_latest_snapshot(addr)

                # 4. Save new snapshot
                self.db.save_snapshot(new_snapshot)

                # 5. Detect changes
                events = self.detector.detect(old_snapshot, new_snapshot)

                # 6. Save events and notify
                for event in events:
                    self.db.save_event(event)
                    self._notify(event)

                all_events.extend(events)

                # 7. Fetch and save recent trades
                try:
                    # Get trades from the last hour
                    since_ms = int((datetime.utcnow().timestamp() - 3600) * 1000)
                    trades = self.collector.fetch_recent_trades(addr, since_ms=since_ms)
                    if trades:
                        saved = self.db.save_trades(trades)
                        if saved > 0:
                            logger.debug(f"Saved {saved} new trades for {addr[:10]}...")
                except Exception as e:
                    logger.debug(f"Trade fetch error for {addr[:10]}...: {e}")

            except Exception as e:
                errors += 1
                logger.error(f"Error polling {addr[:10]}...: {e}")

            # Small delay between requests to be respectful to API
            time.sleep(0.2)

        logger.info(
            f"Poll complete — {len(addresses)} whales, "
            f"{len(all_events)} events, {errors} errors"
        )
        return all_events

    # ------------------------------------------------------------------
    # Continuous monitoring loop
    # ------------------------------------------------------------------

    def run(self, interval: int | None = None) -> None:
        """Run the monitor in a continuous loop.

        Args:
            interval: Seconds between poll cycles. Defaults to config value.
        """
        interval = interval or settings.poll_interval_top_whales
        logger.info(f"Starting position monitor — polling every {interval}s")

        # Print initial status
        self._print_status()

        cycle = 0
        try:
            while True:
                cycle += 1
                logger.info(f"--- Poll cycle {cycle} ---")

                # Reload registry from disk every 60 cycles so that score/tier
                # updates written by run.py (e.g. new staking data) take effect
                # without restarting the monitor process.
                if cycle % 60 == 0:
                    logger.info("Reloading whale registry from disk…")
                    self.registry.reload()

                events = self.poll_once()

                # Print events to console
                for event in events:
                    console.print(f"  {event.description}")

                time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Monitor stopped by user")
            self.collector.close()

    # ------------------------------------------------------------------
    # Status display
    # ------------------------------------------------------------------

    def _print_status(self) -> None:
        """Print a status table showing tracked whales."""
        table = RichTable(title="🐋 HyperWhale — Tracked Wallets")
        table.add_column("Address", style="cyan")
        table.add_column("Label", style="green")
        table.add_column("Tier", style="yellow")
        table.add_column("Account Value", justify="right")

        for whale in self.registry.whales.values():
            if whale.is_active:
                table.add_row(
                    f"{whale.address[:6]}...{whale.address[-4:]}",
                    whale.label or "—",
                    whale.tier.value.upper(),
                    f"${whale.account_value:,.0f}" if whale.account_value > 0 else "—",
                )

        console.print(table)
        console.print()


# ---------------------------------------------------------------------------
# Run directly: python -m hyperwhale.tracker.position_monitor
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logger.remove()
    logger.add(sys.stderr, level="INFO")

    monitor = PositionMonitor()

    if "--once" in sys.argv:
        # Single poll for testing
        events = monitor.poll_once()
        console.print(f"\n[bold green]Done — {len(events)} events detected[/bold green]")
    else:
        # Continuous monitoring
        monitor.run()
