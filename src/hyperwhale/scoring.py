"""Whale Scoring System — composite scoring for wallet classification.

Two-layer classification:
  Layer 1 (hard rules): $50M+ with no activity → DORMANT_WHALE, <$1M → SKIP
  Layer 2 (score-based): weighted composite of account + position + activity

Score formula:
  whale_score = 0.60 × account_score + 0.20 × position_score + 0.20 × activity_score
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from hyperwhale.constants import (
    SCORE_WEIGHT_ACCOUNT,
    SCORE_WEIGHT_POSITION,
    SCORE_WEIGHT_ACTIVITY,
    SCORE_WEIGHT_STAKING,
    ACCOUNT_SCORE_BREAKPOINTS,
    POSITION_SCORE_BREAKPOINTS,
    ACTIVITY_SCORE_BREAKPOINTS,
    STAKING_SCORE_BREAKPOINTS,
    STAKING_TIER_LABELS,
    RECENCY_BONUS_24H,
    RECENCY_BONUS_7D,
    TIER_CUTOFF_APEX,
    TIER_CUTOFF_WHALE,
    TIER_CUTOFF_SHARK,
    TIER_CUTOFF_DOLPHIN,
    DORMANT_WHALE_THRESHOLD,
    MIN_ACCOUNT_VALUE,
)
from hyperwhale.models import WhaleTier


@dataclass
class ScoreResult:
    """Output of the scoring pipeline for a single wallet."""
    tier: WhaleTier
    whale_score: float          # composite 0-100
    account_score: float        # sub-score 0-100
    position_score: float       # sub-score 0-100
    activity_score: float       # sub-score 0-100
    staking_score: float = 0.0  # sub-score 0-100 (HYPE staking conviction)
    staked_hype_tier: str = "none"  # inferred label: none/low/mid/high/elite


def _lookup_breakpoint(
    value: float,
    breakpoints: list[tuple[float, int]],
    floor_zero: bool = False,
) -> float:
    """Map a value to a sub-score using a sorted-descending breakpoint table.

    Args:
        value: The input value to score.
        breakpoints: List of (threshold, score) pairs, sorted descending by threshold.
        floor_zero: If True, return 0.0 for values below the lowest breakpoint instead
                    of linearly interpolating.  Use this for binary-style scores like
                    staking where sub-threshold values should earn nothing.
    """
    for threshold, score in breakpoints:
        if value >= threshold:
            return float(score)

    if floor_zero:
        return 0.0

    # Below the lowest breakpoint → linear interpolation 0-20
    lowest_threshold = breakpoints[-1][0] if breakpoints else 1_000_000
    if lowest_threshold <= 0:
        return 0.0
    ratio = min(value / lowest_threshold, 1.0)
    return round(ratio * 20.0, 1)


class WhaleScorer:
    """Computes composite whale scores and assigns tiers.

    Usage:
        scorer = WhaleScorer()
        result = scorer.score(
            account_value=12_500_000,
            total_notional=8_000_000,
            trade_count_30d=45,
            last_trade_time=datetime.utcnow() - timedelta(hours=3),
        )
        print(result.tier, result.whale_score)
    """

    # ------------------------------------------------------------------
    # Sub-score calculators
    # ------------------------------------------------------------------

    @staticmethod
    def account_score(account_value: float) -> float:
        """Score based on total account value (equity)."""
        return _lookup_breakpoint(account_value, ACCOUNT_SCORE_BREAKPOINTS)

    @staticmethod
    def position_score(total_notional: float) -> float:
        """Score based on total open notional position value."""
        return _lookup_breakpoint(total_notional, POSITION_SCORE_BREAKPOINTS)

    @staticmethod
    def activity_score(
        trade_count_30d: int,
        last_trade_time: Optional[datetime] = None,
    ) -> float:
        """Score based on trading frequency + recency bonus.

        The recency bonus rewards wallets that traded very recently,
        making the system responsive to *current* activity.
        """
        # Base score from trade count
        base = _lookup_breakpoint(float(trade_count_30d), ACTIVITY_SCORE_BREAKPOINTS)

        # Recency bonus
        bonus = 0.0
        if last_trade_time is not None:
            # Handle both naive and aware datetimes
            now = datetime.now(timezone.utc)
            if last_trade_time.tzinfo is None:
                last_trade_time = last_trade_time.replace(tzinfo=timezone.utc)
            age = now - last_trade_time
            if age < timedelta(hours=24):
                bonus = RECENCY_BONUS_24H
            elif age < timedelta(days=7):
                bonus = RECENCY_BONUS_7D

        return min(base + bonus, 100.0)

    @staticmethod
    def staking_score(active_staking_discount: float) -> tuple[float, str]:
        """Score based on HYPE staking conviction (via fee discount proxy).

        Args:
            active_staking_discount: The activeStakingDiscount from userFees API
                (e.g. 0.03 = 3% discount). Pass 0.0 if unavailable.

        Returns:
            Tuple of (sub-score 0-100, tier label: none/low/mid/high/elite).
        """
        score = _lookup_breakpoint(
            active_staking_discount, STAKING_SCORE_BREAKPOINTS, floor_zero=True
        )

        # Derive human-readable tier
        tier = "none"
        for label, threshold in sorted(STAKING_TIER_LABELS.items(), key=lambda x: -x[1]):
            if label == "none":
                continue
            if active_staking_discount >= threshold:
                tier = label
                break

        return score, tier

    # ------------------------------------------------------------------
    # Composite score + classification
    # ------------------------------------------------------------------

    def score(
        self,
        account_value: float,
        total_notional: float = 0.0,
        trade_count_30d: int = 0,
        last_trade_time: Optional[datetime] = None,
        staking_discount: float = 0.0,
    ) -> ScoreResult:
        """Compute the full composite score and classify a wallet.

        This is the main entry point. It applies:
          1. Hard rules (dormant whale, minimum account value)
          2. Sub-score calculation (account + position + activity + staking)
          3. Weighted composite
          4. Tier assignment from score cutoffs

        Args:
            staking_discount: activeStakingDiscount from userFees API (0.0–0.1+).
                              Pass 0.0 if unavailable — gracefully treated as no staking.
        """
        st_score, st_tier = self.staking_score(staking_discount)

        # --- Layer 1: Hard rules ---
        if account_value < MIN_ACCOUNT_VALUE:
            a_score = self.account_score(account_value)
            p_score = self.position_score(total_notional)
            act_score = self.activity_score(trade_count_30d, last_trade_time)
            composite = round(
                SCORE_WEIGHT_ACCOUNT * a_score
                + SCORE_WEIGHT_POSITION * p_score
                + SCORE_WEIGHT_ACTIVITY * act_score
                + SCORE_WEIGHT_STAKING * st_score,
                1,
            )
            return ScoreResult(
                tier=WhaleTier.SKIP,
                whale_score=composite,
                account_score=a_score,
                position_score=p_score,
                activity_score=act_score,
                staking_score=st_score,
                staked_hype_tier=st_tier,
            )

        # Rule: $50M+ with no open positions AND no recent trades → DORMANT_WHALE
        is_dormant = (
            account_value >= DORMANT_WHALE_THRESHOLD
            and total_notional == 0.0
            and trade_count_30d == 0
        )

        # --- Layer 2: Compute sub-scores ---
        a_score = self.account_score(account_value)
        p_score = self.position_score(total_notional)
        act_score = self.activity_score(trade_count_30d, last_trade_time)

        composite = round(
            SCORE_WEIGHT_ACCOUNT * a_score
            + SCORE_WEIGHT_POSITION * p_score
            + SCORE_WEIGHT_ACTIVITY * act_score
            + SCORE_WEIGHT_STAKING * st_score,
            1,
        )

        # --- Tier assignment ---
        if is_dormant:
            tier = WhaleTier.DORMANT_WHALE
        elif composite >= TIER_CUTOFF_APEX:
            tier = WhaleTier.APEX
        elif composite >= TIER_CUTOFF_WHALE:
            tier = WhaleTier.WHALE
        elif composite >= TIER_CUTOFF_SHARK:
            tier = WhaleTier.SHARK
        elif composite >= TIER_CUTOFF_DOLPHIN:
            tier = WhaleTier.DOLPHIN
        else:
            tier = WhaleTier.SKIP

        return ScoreResult(
            tier=tier,
            whale_score=composite,
            account_score=a_score,
            position_score=p_score,
            activity_score=act_score,
            staking_score=st_score,
            staked_hype_tier=st_tier,
        )
