"""SQLite database layer for persisting whale data.

Stores position snapshots, trades, and events as time-series data.
Uses SQLAlchemy Core (not ORM) for simplicity and speed.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import sqlalchemy as sa
from loguru import logger
from sqlalchemy import create_engine, MetaData, Table, Column, text

from hyperwhale.config import settings
from hyperwhale.models import (
    Position,
    PositionEvent,
    PositionSnapshot,
    Trade,
    CohortSentiment,
)


metadata = MetaData()

# ---------------------------------------------------------------------------
# Table Definitions
# ---------------------------------------------------------------------------

position_snapshots_table = Table(
    "position_snapshots",
    metadata,
    Column("id", sa.Integer, primary_key=True, autoincrement=True),
    Column("address", sa.String, nullable=False, index=True),
    Column("account_value", sa.Float),
    Column("total_margin_used", sa.Float),
    Column("total_notional_position", sa.Float),
    Column("withdrawable", sa.Float),
    Column("positions_json", sa.Text),  # JSON-serialized list of positions
    Column("timestamp", sa.DateTime, nullable=False, index=True),
)

trades_table = Table(
    "trades",
    metadata,
    Column("id", sa.Integer, primary_key=True, autoincrement=True),
    Column("address", sa.String, nullable=False, index=True),
    Column("coin", sa.String, nullable=False),
    Column("side", sa.String),
    Column("direction", sa.String),
    Column("price", sa.Float),
    Column("size", sa.Float),
    Column("notional_value", sa.Float),
    Column("closed_pnl", sa.Float),
    Column("fee", sa.Float),
    Column("is_crossed", sa.Boolean),
    Column("order_id", sa.BigInteger),
    Column("trade_id", sa.BigInteger, unique=True),
    Column("tx_hash", sa.String),
    Column("timestamp", sa.DateTime, nullable=False, index=True),
)

events_table = Table(
    "events",
    metadata,
    Column("id", sa.Integer, primary_key=True, autoincrement=True),
    Column("address", sa.String, nullable=False, index=True),
    Column("coin", sa.String),
    Column("event_type", sa.String),
    Column("old_size", sa.Float),
    Column("new_size", sa.Float),
    Column("size_change_pct", sa.Float),
    Column("old_leverage", sa.Float),
    Column("new_leverage", sa.Float),
    Column("notional_value", sa.Float),
    Column("side", sa.String),
    Column("timestamp", sa.DateTime, nullable=False, index=True),
)

cohort_sentiment_table = Table(
    "cohort_sentiment",
    metadata,
    Column("id", sa.Integer, primary_key=True, autoincrement=True),
    Column("tier", sa.String, nullable=False),
    Column("num_wallets", sa.Integer),
    Column("total_long_notional", sa.Float),
    Column("total_short_notional", sa.Float),
    Column("long_ratio", sa.Float),
    Column("pct_in_profit", sa.Float),
    Column("timestamp", sa.DateTime, nullable=False, index=True),
)


# ---------------------------------------------------------------------------
# Database Manager
# ---------------------------------------------------------------------------

class Database:
    """Manages SQLite database for HyperWhale data storage."""

    def __init__(self, url: Optional[str] = None) -> None:
        self.url = url or settings.database_url
        # Ensure data directory exists for SQLite
        if self.url.startswith("sqlite:///"):
            db_path = Path(self.url.replace("sqlite:///", ""))
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(self.url, echo=False)
        metadata.create_all(self.engine)
        logger.info(f"Database initialized: {self.url}")

    # ------------------------------------------------------------------
    # Position Snapshots
    # ------------------------------------------------------------------

    def save_snapshot(self, snapshot: PositionSnapshot) -> None:
        """Save a position snapshot to the database."""
        positions_json = json.dumps(
            [p.model_dump(mode="json") for p in snapshot.positions],
            default=str,
        )
        with self.engine.begin() as conn:
            conn.execute(
                position_snapshots_table.insert().values(
                    address=snapshot.address,
                    account_value=snapshot.account_value,
                    total_margin_used=snapshot.total_margin_used,
                    total_notional_position=snapshot.total_notional_position,
                    withdrawable=snapshot.withdrawable,
                    positions_json=positions_json,
                    timestamp=snapshot.timestamp,
                )
            )

    def get_latest_snapshot(self, address: str) -> Optional[PositionSnapshot]:
        """Get the most recent snapshot for a whale."""
        with self.engine.connect() as conn:
            result = conn.execute(
                position_snapshots_table.select()
                .where(position_snapshots_table.c.address == address)
                .order_by(position_snapshots_table.c.timestamp.desc())
                .limit(1)
            ).fetchone()

        if result is None:
            return None

        positions_raw = json.loads(result.positions_json) if result.positions_json else []
        positions = [Position(**p) for p in positions_raw]

        return PositionSnapshot(
            address=result.address,
            account_value=result.account_value,
            total_margin_used=result.total_margin_used,
            total_notional_position=result.total_notional_position,
            withdrawable=result.withdrawable,
            positions=positions,
            timestamp=result.timestamp,
        )

    def get_snapshots(
        self,
        address: str,
        since: Optional[datetime] = None,
        limit: int = 1000,
    ) -> list[PositionSnapshot]:
        """Get historical snapshots for a whale."""
        query = (
            position_snapshots_table.select()
            .where(position_snapshots_table.c.address == address)
        )
        if since:
            query = query.where(position_snapshots_table.c.timestamp >= since)
        query = query.order_by(position_snapshots_table.c.timestamp.desc()).limit(limit)

        with self.engine.connect() as conn:
            rows = conn.execute(query).fetchall()

        snapshots = []
        for row in rows:
            positions_raw = json.loads(row.positions_json) if row.positions_json else []
            positions = [Position(**p) for p in positions_raw]
            snapshots.append(
                PositionSnapshot(
                    address=row.address,
                    account_value=row.account_value,
                    total_margin_used=row.total_margin_used,
                    total_notional_position=row.total_notional_position,
                    withdrawable=row.withdrawable,
                    positions=positions,
                    timestamp=row.timestamp,
                )
            )
        return snapshots

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def save_trades(self, trades: list[Trade]) -> int:
        """Save trades to the database (skips duplicates by trade_id)."""
        saved = 0
        with self.engine.begin() as conn:
            for trade in trades:
                try:
                    conn.execute(
                        trades_table.insert().values(
                            address=trade.address,
                            coin=trade.coin,
                            side=trade.side,
                            direction=trade.direction.value,
                            price=trade.price,
                            size=trade.size,
                            notional_value=trade.notional_value,
                            closed_pnl=trade.closed_pnl,
                            fee=trade.fee,
                            is_crossed=trade.is_crossed,
                            order_id=trade.order_id,
                            trade_id=trade.trade_id,
                            tx_hash=trade.tx_hash,
                            timestamp=trade.timestamp,
                        )
                    )
                    saved += 1
                except sa.exc.IntegrityError:
                    pass  # duplicate trade_id — skip
        return saved

    def get_trades(
        self,
        address: str,
        since: Optional[datetime] = None,
        coin: Optional[str] = None,
        limit: int = 2000,
    ) -> list[Trade]:
        """Get trades for a whale, optionally filtered."""
        query = trades_table.select().where(trades_table.c.address == address)
        if since:
            query = query.where(trades_table.c.timestamp >= since)
        if coin:
            query = query.where(trades_table.c.coin == coin)
        query = query.order_by(trades_table.c.timestamp.desc()).limit(limit)

        with self.engine.connect() as conn:
            rows = conn.execute(query).fetchall()

        return [
            Trade(
                address=row.address,
                coin=row.coin,
                side=row.side,
                direction=row.direction,
                price=row.price,
                size=row.size,
                notional_value=row.notional_value,
                closed_pnl=row.closed_pnl,
                fee=row.fee,
                is_crossed=row.is_crossed,
                order_id=row.order_id,
                trade_id=row.trade_id,
                tx_hash=row.tx_hash,
                timestamp=row.timestamp,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def save_event(self, event: PositionEvent) -> None:
        """Save a position change event."""
        with self.engine.begin() as conn:
            conn.execute(
                events_table.insert().values(
                    address=event.address,
                    coin=event.coin,
                    event_type=event.event_type.value,
                    old_size=event.old_size,
                    new_size=event.new_size,
                    size_change_pct=event.size_change_pct,
                    old_leverage=event.old_leverage,
                    new_leverage=event.new_leverage,
                    notional_value=event.notional_value,
                    side=event.side.value if event.side else None,
                    timestamp=event.timestamp,
                )
            )

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        """Get the most recent events as dicts."""
        query = (
            events_table.select()
            .order_by(events_table.c.timestamp.desc())
            .limit(limit)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [
            {
                "address": row.address,
                "coin": row.coin,
                "event_type": row.event_type,
                "old_size": row.old_size,
                "new_size": row.new_size,
                "size_change_pct": row.size_change_pct,
                "notional_value": row.notional_value,
                "side": row.side,
                "old_leverage": row.old_leverage,
                "new_leverage": row.new_leverage,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Cohort Sentiment
    # ------------------------------------------------------------------

    def save_cohort_sentiment(self, sentiment: CohortSentiment) -> None:
        """Save a cohort sentiment snapshot."""
        with self.engine.begin() as conn:
            conn.execute(
                cohort_sentiment_table.insert().values(
                    tier=sentiment.tier.value,
                    num_wallets=sentiment.num_wallets,
                    total_long_notional=sentiment.total_long_notional,
                    total_short_notional=sentiment.total_short_notional,
                    long_ratio=sentiment.long_ratio,
                    pct_in_profit=sentiment.pct_in_profit,
                    timestamp=sentiment.timestamp,
                )
            )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_snapshot_count(self, address: Optional[str] = None) -> int:
        """Count total snapshots, optionally for a specific address."""
        query = sa.select(sa.func.count()).select_from(position_snapshots_table)
        if address:
            query = query.where(position_snapshots_table.c.address == address)
        with self.engine.connect() as conn:
            return conn.execute(query).scalar() or 0

    def get_trade_count(self, address: Optional[str] = None) -> int:
        """Count total trades, optionally for a specific address."""
        query = sa.select(sa.func.count()).select_from(trades_table)
        if address:
            query = query.where(trades_table.c.address == address)
        with self.engine.connect() as conn:
            return conn.execute(query).scalar() or 0

    def get_event_count(self) -> int:
        """Count total events."""
        query = sa.select(sa.func.count()).select_from(events_table)
        with self.engine.connect() as conn:
            return conn.execute(query).scalar() or 0

    def get_counts(self) -> dict:
        """Get counts for all tables."""
        return {
            "snapshots": self.get_snapshot_count(),
            "trades": self.get_trade_count(),
            "events": self.get_event_count(),
        }
