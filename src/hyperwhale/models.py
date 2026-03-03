"""Pydantic data models for HyperWhale.

These models represent the core domain objects that flow through the system:
  API Response → Models → Database → Analytics → Alerts
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WhaleTier(str, Enum):
    """Wallet classification tier based on composite whale score."""
    APEX = "apex"                  # Score 75+ — elite traders ($10M+, active, big positions)
    WHALE = "whale"                # Score 55-74 — serious players
    DORMANT_WHALE = "dormant_whale"  # $50M+ account but no activity/positions
    SHARK = "shark"                # Score 35-54 — mid-tier active traders
    DOLPHIN = "dolphin"            # Score 20-34 — smaller but notable
    SKIP = "skip"                  # Score <20 or AV <$1M — not worth tracking


class PositionSide(str, Enum):
    """Long or short."""
    LONG = "long"
    SHORT = "short"


class TradeDirection(str, Enum):
    """Categorised trade direction."""
    OPEN_LONG = "Open Long"
    OPEN_SHORT = "Open Short"
    CLOSE_LONG = "Close Long"
    CLOSE_SHORT = "Close Short"


class EventType(str, Enum):
    """Types of position change events."""
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_INCREASED = "position_increased"
    POSITION_DECREASED = "position_decreased"
    LEVERAGE_CHANGED = "leverage_changed"
    NEW_COIN_ADDED = "new_coin_added"


# ---------------------------------------------------------------------------
# Core Data Models
# ---------------------------------------------------------------------------

class WhaleProfile(BaseModel):
    """A tracked whale wallet with composite scoring."""
    address: str = Field(..., description="Ethereum-style wallet address")
    label: str = Field(default="", description="Optional human-readable label (e.g., 'James Wynn')")
    tier: WhaleTier = Field(default=WhaleTier.SKIP, description="Classification tier")
    account_value: float = Field(default=0.0, description="Latest known account value in USD")
    is_active: bool = Field(default=True, description="Whether we are actively tracking this whale")
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    notes: str = Field(default="", description="Free-form notes about this whale")

    # --- Scoring fields ---
    whale_score: float = Field(default=0.0, description="Composite whale score (0-100)")
    account_score: float = Field(default=0.0, description="Account value sub-score (0-100)")
    position_score: float = Field(default=0.0, description="Position size sub-score (0-100)")
    activity_score: float = Field(default=0.0, description="Trading activity sub-score (0-100)")
    staking_score: float = Field(default=0.0, description="HYPE staking conviction sub-score (0-100)")
    staked_hype_tier: str = Field(default="none", description="Inferred staking tier: none / low / mid / high / elite")
    trade_count_30d: int = Field(default=0, description="Number of trades in last 30 days")
    total_notional: float = Field(default=0.0, description="Total open notional position value")


class Position(BaseModel):
    """A single perpetual position for a whale at a point in time."""
    address: str
    coin: str                                    # e.g., "BTC", "ETH"
    side: PositionSide
    size: float                                  # position size in contracts
    notional_value: float                        # position value in USD
    entry_price: float
    mark_price: float
    liquidation_price: Optional[float] = None
    leverage: float
    leverage_type: str = "cross"                 # "cross" or "isolated"
    unrealized_pnl: float = 0.0
    margin_used: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Trade(BaseModel):
    """A single fill/trade for a whale."""
    address: str
    coin: str
    side: str                                    # "B" (buy) or "A" (sell/ask)
    direction: TradeDirection
    price: float
    size: float
    notional_value: float                        # price * size
    closed_pnl: float = 0.0
    fee: float = 0.0
    is_crossed: bool = False                     # market order (crossed the spread)
    order_id: int = 0
    trade_id: int = 0
    tx_hash: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PositionSnapshot(BaseModel):
    """A complete snapshot of a whale's portfolio at a point in time."""
    address: str
    account_value: float
    total_margin_used: float
    total_notional_position: float
    withdrawable: float
    positions: list[Position] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PositionEvent(BaseModel):
    """A detected change in a whale's position."""
    address: str
    coin: str
    event_type: EventType
    old_size: float = 0.0
    new_size: float = 0.0
    size_change_pct: float = 0.0                 # percentage change
    old_leverage: float = 0.0
    new_leverage: float = 0.0
    notional_value: float = 0.0                  # current notional
    entry_price: float = 0.0                     # average entry price
    mark_price: float = 0.0                      # current mark price
    unrealized_pnl: float = 0.0                  # current unrealized PnL
    liquidation_price: Optional[float] = None    # liquidation price
    account_value: float = 0.0                   # whale's total account value at event time
    side: Optional[PositionSide] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @property
    def description(self) -> str:
        """Human-readable description of the event."""
        addr_short = f"{self.address[:6]}...{self.address[-4:]}"
        match self.event_type:
            case EventType.POSITION_OPENED:
                return (
                    f"🐋 {addr_short} opened a {self.side.value.upper()} "
                    f"on {self.coin} — ${self.notional_value:,.0f} at {self.new_leverage}x"
                )
            case EventType.POSITION_CLOSED:
                return f"🔴 {addr_short} closed their {self.coin} position (was ${self.notional_value:,.0f})"
            case EventType.POSITION_INCREASED:
                return (
                    f"📈 {addr_short} increased {self.coin} {self.side.value} "
                    f"by {self.size_change_pct:+.1f}% → ${self.notional_value:,.0f}"
                )
            case EventType.POSITION_DECREASED:
                return (
                    f"📉 {addr_short} decreased {self.coin} {self.side.value} "
                    f"by {self.size_change_pct:+.1f}% → ${self.notional_value:,.0f}"
                )
            case EventType.LEVERAGE_CHANGED:
                return (
                    f"⚙️ {addr_short} changed {self.coin} leverage: "
                    f"{self.old_leverage}x → {self.new_leverage}x"
                )
            case EventType.NEW_COIN_ADDED:
                return f"🆕 {addr_short} started trading {self.coin} for the first time"
            case _:
                return f"❓ {addr_short} — unknown event on {self.coin}"


# ---------------------------------------------------------------------------
# Cohort / Aggregated Models
# ---------------------------------------------------------------------------

class CohortSentiment(BaseModel):
    """Aggregated sentiment for a cohort tier at a point in time."""
    tier: WhaleTier
    num_wallets: int
    total_long_notional: float
    total_short_notional: float
    long_ratio: float                            # 0.0 to 1.0
    pct_in_profit: float                         # 0.0 to 1.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @property
    def sentiment_label(self) -> str:
        """Convert long ratio to a HyperDash-style sentiment label."""
        r = self.long_ratio
        if r >= 0.80:
            return "Ext Bullish"
        elif r >= 0.70:
            return "Very Bullish"
        elif r >= 0.60:
            return "Bullish"
        elif r >= 0.55:
            return "Slightly Bullish"
        elif r >= 0.45:
            return "Neutral"
        elif r >= 0.40:
            return "Bit Bearish"
        elif r >= 0.30:
            return "Bearish"
        elif r >= 0.20:
            return "Very Bearish"
        else:
            return "Ext Bearish"


# ---------------------------------------------------------------------------
# Analytics Output Models
# ---------------------------------------------------------------------------

class AnomalyAlert(BaseModel):
    """An anomaly detected for a whale."""
    address: str
    metric_name: str                             # e.g., "position_size", "leverage"
    current_value: float
    baseline_mean: float
    baseline_std: float
    sigma_score: float                           # how many σ away
    description: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class WalletCorrelation(BaseModel):
    """Correlation between two wallets."""
    address_a: str
    address_b: str
    pearson_r: float                             # -1 to 1
    timing_correlation: float = 0.0              # 0 to 1
    coin_overlap: float = 0.0                    # Jaccard similarity 0 to 1
    avg_lag_seconds: float = 0.0                 # leader-follower lag
    leader: Optional[str] = None                 # which address leads
    window_days: int = 14
    sample_count: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
