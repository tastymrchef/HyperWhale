"""Change detector — compares consecutive position snapshots to detect events."""

from __future__ import annotations

from loguru import logger

from hyperwhale.config import settings
from hyperwhale.models import (
    EventType,
    Position,
    PositionEvent,
    PositionSide,
    PositionSnapshot,
)


class ChangeDetector:
    """Detects meaningful changes between two consecutive position snapshots.

    Compares old vs new snapshot for the same whale and generates PositionEvent
    objects for each significant change.
    """

    def __init__(self, min_change_pct: float | None = None) -> None:
        self.min_change_pct = min_change_pct or settings.min_position_change_pct

    def detect(
        self,
        old_snapshot: PositionSnapshot | None,
        new_snapshot: PositionSnapshot,
    ) -> list[PositionEvent]:
        """Compare two snapshots and return a list of position events.

        Args:
            old_snapshot: Previous snapshot (None if first snapshot for this whale).
            new_snapshot: Current snapshot just fetched from API.

        Returns:
            List of detected PositionEvent objects.
        """
        events: list[PositionEvent] = []

        if old_snapshot is None:
            # First snapshot for this whale — silently baseline, no alerts.
            # We don't know what changed vs before we started tracking,
            # so firing POSITION_OPENED for everything would be a false flood.
            logger.debug(
                f"First snapshot for {new_snapshot.address[:10]}... — "
                f"baselined {len(new_snapshot.positions)} positions, no alerts"
            )
            return events

        # Build lookup dicts: coin → Position
        old_positions = {p.coin: p for p in old_snapshot.positions}
        new_positions = {p.coin: p for p in new_snapshot.positions}

        all_coins = set(old_positions.keys()) | set(new_positions.keys())

        for coin in all_coins:
            old_pos = old_positions.get(coin)
            new_pos = new_positions.get(coin)

            if old_pos is None and new_pos is not None:
                # --- New position opened ---
                events.append(
                    PositionEvent(
                        address=new_snapshot.address,
                        coin=coin,
                        event_type=EventType.POSITION_OPENED,
                        new_size=new_pos.size,
                        new_leverage=new_pos.leverage,
                        notional_value=new_pos.notional_value,
                        entry_price=new_pos.entry_price,
                        mark_price=new_pos.mark_price,
                        unrealized_pnl=new_pos.unrealized_pnl,
                        liquidation_price=new_pos.liquidation_price,
                        account_value=new_snapshot.account_value,
                        side=new_pos.side,
                        timestamp=new_snapshot.timestamp,
                    )
                )

                # Also check if this is a brand new coin for this whale
                events.append(
                    PositionEvent(
                        address=new_snapshot.address,
                        coin=coin,
                        event_type=EventType.NEW_COIN_ADDED,
                        new_size=new_pos.size,
                        notional_value=new_pos.notional_value,
                        side=new_pos.side,
                        timestamp=new_snapshot.timestamp,
                    )
                )

            elif old_pos is not None and new_pos is None:
                # --- Position closed ---
                events.append(
                    PositionEvent(
                        address=new_snapshot.address,
                        coin=coin,
                        event_type=EventType.POSITION_CLOSED,
                        old_size=old_pos.size,
                        new_size=0.0,
                        size_change_pct=-100.0,
                        old_leverage=old_pos.leverage,
                        notional_value=old_pos.notional_value,
                        entry_price=old_pos.entry_price,
                        mark_price=old_pos.mark_price,
                        unrealized_pnl=old_pos.unrealized_pnl,
                        account_value=new_snapshot.account_value,
                        side=old_pos.side,
                        timestamp=new_snapshot.timestamp,
                    )
                )

            elif old_pos is not None and new_pos is not None:
                # --- Position exists in both snapshots — check for changes ---
                coin_events = self._compare_positions(
                    old_pos, new_pos, new_snapshot.address, new_snapshot.timestamp
                )
                events.extend(coin_events)

        if events:
            logger.info(
                f"Detected {len(events)} events for {new_snapshot.address[:10]}..."
            )

        return events

    def _compare_positions(
        self,
        old: Position,
        new: Position,
        address: str,
        timestamp,
    ) -> list[PositionEvent]:
        """Compare two positions on the same coin and detect changes."""
        events: list[PositionEvent] = []

        # Size change
        if old.size > 0:
            size_change_pct = ((new.size - old.size) / old.size) * 100
        else:
            size_change_pct = 100.0 if new.size > 0 else 0.0

        if abs(size_change_pct) >= self.min_change_pct:
            event_type = (
                EventType.POSITION_INCREASED
                if size_change_pct > 0
                else EventType.POSITION_DECREASED
            )
            events.append(
                PositionEvent(
                    address=address,
                    coin=new.coin,
                    event_type=event_type,
                    old_size=old.size,
                    new_size=new.size,
                    size_change_pct=size_change_pct,
                    old_leverage=old.leverage,
                    new_leverage=new.leverage,
                    notional_value=new.notional_value,
                    entry_price=new.entry_price,
                    mark_price=new.mark_price,
                    unrealized_pnl=new.unrealized_pnl,
                    liquidation_price=new.liquidation_price,
                    side=new.side,
                    timestamp=timestamp,
                )
            )

        # Leverage change (only if significant — more than 1x difference)
        if abs(new.leverage - old.leverage) >= 1.0:
            events.append(
                PositionEvent(
                    address=address,
                    coin=new.coin,
                    event_type=EventType.LEVERAGE_CHANGED,
                    old_size=old.size,
                    new_size=new.size,
                    old_leverage=old.leverage,
                    new_leverage=new.leverage,
                    notional_value=new.notional_value,
                    entry_price=new.entry_price,
                    mark_price=new.mark_price,
                    unrealized_pnl=new.unrealized_pnl,
                    liquidation_price=new.liquidation_price,
                    side=new.side,
                    timestamp=timestamp,
                )
            )

        return events
