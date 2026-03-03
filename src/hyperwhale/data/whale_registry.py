"""Whale address registry — manages the list of tracked wallets."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from hyperwhale.models import WhaleProfile, WhaleTier
from hyperwhale.scoring import WhaleScorer


# Default path for the whale list
DEFAULT_WHALE_FILE = Path(__file__).resolve().parents[3] / "data" / "whale_addresses.json"

# Shared scorer instance
_scorer = WhaleScorer()


class WhaleRegistry:
    """In-memory registry of tracked whale wallets, backed by a JSON file."""

    def __init__(self, filepath: Optional[Path] = None) -> None:
        self.filepath = filepath or DEFAULT_WHALE_FILE
        self.whales: dict[str, WhaleProfile] = {}  # address → profile
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load whale addresses from JSON file."""
        if not self.filepath.exists():
            logger.warning(f"Whale file not found at {self.filepath} — starting empty")
            return

        with open(self.filepath, "r") as f:
            raw = json.load(f)

        for entry in raw.get("whales", []):
            addr = entry["address"].lower()
            account_value = entry.get("account_value", 0.0)
            total_notional = entry.get("total_notional", 0.0)
            trade_count_30d = entry.get("trade_count_30d", 0)
            staking_discount_stored = entry.get("staking_score", 0.0)  # stored sub-score, not re-fetched

            # Re-score on load to pick up any config changes
            result = _scorer.score(
                account_value=account_value,
                total_notional=total_notional,
                trade_count_30d=trade_count_30d,
            )

            self.whales[addr] = WhaleProfile(
                address=addr,
                label=entry.get("label", ""),
                notes=entry.get("notes", ""),
                account_value=account_value,
                tier=result.tier,
                whale_score=result.whale_score,
                account_score=result.account_score,
                position_score=result.position_score,
                activity_score=result.activity_score,
                staking_score=entry.get("staking_score", 0.0),
                staked_hype_tier=entry.get("staked_hype_tier", "none"),
                trade_count_30d=trade_count_30d,
                total_notional=total_notional,
            )

        logger.info(f"Loaded {len(self.whales)} whale addresses from {self.filepath}")

    def save(self) -> None:
        """Persist current whale list back to JSON."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "whales": [
                {
                    "address": w.address,
                    "label": w.label,
                    "tier": w.tier.value,
                    "account_value": w.account_value,
                    "whale_score": w.whale_score,
                    "account_score": w.account_score,
                    "position_score": w.position_score,
                    "activity_score": w.activity_score,
                    "staking_score": w.staking_score,
                    "staked_hype_tier": w.staked_hype_tier,
                    "trade_count_30d": w.trade_count_30d,
                    "total_notional": w.total_notional,
                    "notes": w.notes,
                }
                for w in self.whales.values()
            ]
        }
        with open(self.filepath, "w") as f:
            json.dump(payload, f, indent=2)
        logger.info(f"Saved {len(self.whales)} whales to {self.filepath}")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, address: str, label: str = "", notes: str = "") -> WhaleProfile:
        """Add a whale to the registry."""
        addr = address.lower()
        if addr in self.whales:
            logger.debug(f"Whale {addr} already in registry")
            return self.whales[addr]

        profile = WhaleProfile(address=addr, label=label, notes=notes)
        self.whales[addr] = profile
        logger.info(f"Added whale: {addr} ({label or 'unlabeled'})")
        return profile

    def remove(self, address: str) -> None:
        """Remove a whale from the registry."""
        addr = address.lower()
        self.whales.pop(addr, None)

    def get(self, address: str) -> Optional[WhaleProfile]:
        """Get a whale profile by address."""
        return self.whales.get(address.lower())

    def rescore(
        self,
        address: str,
        account_value: float,
        total_notional: float = 0.0,
        trade_count_30d: int = 0,
        last_trade_time: Optional[datetime] = None,
        staking_discount: float = 0.0,
    ) -> None:
        """Re-score a whale with fresh data and update all fields.

        This is the primary method for updating a whale after fetching
        new data from the API. It replaces the old update_account_value().

        Args:
            staking_discount: activeStakingDiscount from userFees API (0.0 = no staking).
        """
        addr = address.lower()
        if addr not in self.whales:
            return

        result = _scorer.score(
            account_value=account_value,
            total_notional=total_notional,
            trade_count_30d=trade_count_30d,
            last_trade_time=last_trade_time,
            staking_discount=staking_discount,
        )

        whale = self.whales[addr]
        whale.account_value = account_value
        whale.total_notional = total_notional
        whale.trade_count_30d = trade_count_30d
        whale.tier = result.tier
        whale.whale_score = result.whale_score
        whale.account_score = result.account_score
        whale.position_score = result.position_score
        whale.activity_score = result.activity_score
        whale.staking_score = result.staking_score
        whale.staked_hype_tier = result.staked_hype_tier
        whale.last_updated = datetime.utcnow()

    def update_account_value(self, address: str, value: float) -> None:
        """Legacy compat — re-score with just account value."""
        self.rescore(address, account_value=value)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def active_addresses(self) -> list[str]:
        """Return list of addresses we are actively tracking."""
        return [w.address for w in self.whales.values() if w.is_active]

    def by_tier(self, tier: WhaleTier) -> list[WhaleProfile]:
        """Get all whales in a specific tier."""
        return [w for w in self.whales.values() if w.tier == tier]

    @property
    def count(self) -> int:
        return len(self.whales)

    def __repr__(self) -> str:
        tier_counts = {}
        for w in self.whales.values():
            tier_counts[w.tier.value] = tier_counts.get(w.tier.value, 0) + 1
        return f"WhaleRegistry({self.count} whales: {tier_counts})"
