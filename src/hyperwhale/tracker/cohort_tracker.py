"""Cohort tracker — computes aggregated sentiment per whale tier over time."""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from hyperwhale.data.database import Database
from hyperwhale.data.whale_registry import WhaleRegistry
from hyperwhale.models import (
    CohortSentiment,
    PositionSide,
    PositionSnapshot,
    WhaleTier,
)


class CohortTracker:
    """Computes and stores cohort-level sentiment (like HyperDash tiers but over time)."""

    def __init__(
        self,
        database: Database | None = None,
        registry: WhaleRegistry | None = None,
    ) -> None:
        self.db = database or Database()
        self.registry = registry or WhaleRegistry()

    def compute_sentiment(
        self,
        snapshots: dict[str, PositionSnapshot],
    ) -> list[CohortSentiment]:
        """Compute sentiment for each tier from the latest snapshots.

        Args:
            snapshots: Dict of address → latest PositionSnapshot.

        Returns:
            List of CohortSentiment, one per tier that has wallets.
        """
        # Group wallets by tier
        tier_data: dict[WhaleTier, list[PositionSnapshot]] = {}
        for addr, snapshot in snapshots.items():
            whale = self.registry.get(addr)
            if whale is None:
                continue
            tier = whale.tier
            tier_data.setdefault(tier, []).append(snapshot)

        results: list[CohortSentiment] = []
        now = datetime.utcnow()

        for tier, tier_snapshots in tier_data.items():
            total_long = 0.0
            total_short = 0.0
            in_profit = 0
            total_wallets = len(tier_snapshots)

            for snap in tier_snapshots:
                wallet_pnl = 0.0
                for pos in snap.positions:
                    if pos.side == PositionSide.LONG:
                        total_long += pos.notional_value
                    else:
                        total_short += pos.notional_value
                    wallet_pnl += pos.unrealized_pnl

                if wallet_pnl > 0:
                    in_profit += 1

            total_notional = total_long + total_short
            long_ratio = total_long / total_notional if total_notional > 0 else 0.5
            pct_profit = in_profit / total_wallets if total_wallets > 0 else 0.0

            sentiment = CohortSentiment(
                tier=tier,
                num_wallets=total_wallets,
                total_long_notional=total_long,
                total_short_notional=total_short,
                long_ratio=long_ratio,
                pct_in_profit=pct_profit,
                timestamp=now,
            )
            results.append(sentiment)

            logger.debug(
                f"Cohort {tier.value}: {total_wallets} wallets, "
                f"{sentiment.sentiment_label} (long ratio: {long_ratio:.1%})"
            )

        return results

    def compute_and_save(
        self,
        snapshots: dict[str, PositionSnapshot],
    ) -> list[CohortSentiment]:
        """Compute sentiment and persist to database."""
        sentiments = self.compute_sentiment(snapshots)
        for s in sentiments:
            self.db.save_cohort_sentiment(s)
        return sentiments
