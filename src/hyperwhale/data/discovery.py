"""Whale Discovery Engine — finds whale wallets from multiple on-chain sources.

Discovery channels:
  1. Leaderboard scan   — Hyperliquid stats API (~30K traders, filter $1M+)
  2. Vault depositors   — HLP vault + any other known vaults
  3. Role filtering      — skip vaults, sub-accounts, missing addresses

Pipeline:
  discover() → collect candidates → deduplicate → filter roles →
  fetch live data → score → add to registry → save
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from hyperwhale.constants import MIN_ACCOUNT_VALUE
from hyperwhale.data.collector import HyperliquidCollector
from hyperwhale.data.whale_registry import WhaleRegistry


# Default vault addresses to scan depositors from
KNOWN_VAULTS = [
    "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303",  # HLP Vault
]


@dataclass
class DiscoveryCandidate:
    """A wallet address discovered from some source, pre-scoring."""
    address: str
    source: str                     # "leaderboard", "vault:<addr>", "seed"
    account_value_hint: float = 0.0  # rough AV from leaderboard (not live)
    label: str = ""
    notes: str = ""


@dataclass
class DiscoveryResult:
    """Summary of a discovery run."""
    candidates_found: int = 0       # raw candidates before dedup
    duplicates_skipped: int = 0     # already in registry
    roles_filtered: int = 0         # vaults / sub-accounts / missing
    below_minimum: int = 0          # live AV below $1M
    api_errors: int = 0             # failed to fetch live data
    whales_added: int = 0           # successfully added + scored
    whales_updated: int = 0         # already existed, re-scored
    duration_seconds: float = 0.0


class WhaleDiscovery:
    """Discovers whale wallets from multiple sources and adds them to the registry.

    Usage:
        discovery = WhaleDiscovery(registry, collector)
        result = discovery.discover(
            min_account_value=1_000_000,
            leaderboard=True,
            vaults=True,
        )
    """

    def __init__(
        self,
        registry: WhaleRegistry,
        collector: HyperliquidCollector,
        on_progress: Optional[callable] = None,
    ) -> None:
        self.registry = registry
        self.collector = collector
        self.on_progress = on_progress or (lambda msg: None)

    # ------------------------------------------------------------------
    # Discovery channels
    # ------------------------------------------------------------------

    def _scan_leaderboard(self, min_av: float) -> list[DiscoveryCandidate]:
        """Channel 1: Scan the Hyperliquid leaderboard for large accounts."""
        self.on_progress("Fetching leaderboard (~30K traders)...")
        rows = self.collector.get_leaderboard()

        if not rows:
            logger.warning("Leaderboard returned empty — skipping channel")
            return []

        candidates = []
        for row in rows:
            av = float(row.get("accountValue", 0))
            if av < min_av:
                continue

            addr = row.get("ethAddress", "").lower()
            if not addr:
                continue

            # Extract display name and allTime PnL for labeling
            name = row.get("displayName") or ""
            all_time = {}
            for window_name, perf in row.get("windowPerformances", []):
                if window_name == "allTime":
                    all_time = perf
                    break

            pnl = float(all_time.get("pnl", 0))
            vlm = float(all_time.get("vlm", 0))

            notes_parts = [f"Leaderboard AV=${av:,.0f}"]
            if pnl != 0:
                notes_parts.append(f"allTime PnL=${pnl:,.0f}")
            if vlm > 0:
                notes_parts.append(f"VLM=${vlm:,.0f}")

            candidates.append(DiscoveryCandidate(
                address=addr,
                source="leaderboard",
                account_value_hint=av,
                label=name,
                notes=", ".join(notes_parts),
            ))

        logger.info(f"Leaderboard: {len(rows)} total, {len(candidates)} above ${min_av:,.0f}")
        self.on_progress(f"Leaderboard: {len(candidates)} candidates above ${min_av:,.0f}")
        return candidates

    def _scan_vault_depositors(
        self,
        vault_addresses: list[str],
        min_equity: float = 100_000,
    ) -> list[DiscoveryCandidate]:
        """Channel 2: Scan vault depositors for large depositors."""
        candidates = []

        for vault_addr in vault_addresses:
            self.on_progress(f"Scanning vault {vault_addr[:10]}...")
            try:
                vault = self.collector.get_vault_details(vault_addr)
                vault_name = vault.get("name", vault_addr[:10])
                followers = vault.get("followers", [])

                for f in followers:
                    equity = float(f.get("vaultEquity", 0))
                    if equity < min_equity:
                        continue

                    addr = f.get("user", "").lower()
                    if not addr:
                        continue

                    candidates.append(DiscoveryCandidate(
                        address=addr,
                        source=f"vault:{vault_name}",
                        account_value_hint=equity,  # vault equity, not total AV
                        label="",
                        notes=f"{vault_name} depositor, vault equity=${equity:,.0f}",
                    ))

                logger.info(f"Vault {vault_name}: {len(followers)} depositors, "
                            f"{sum(1 for f in followers if float(f.get('vaultEquity', 0)) >= min_equity)} above ${min_equity:,.0f}")
                time.sleep(0.3)

            except Exception as e:
                logger.error(f"Failed to scan vault {vault_addr[:10]}: {e}")

        self.on_progress(f"Vault scan: {len(candidates)} candidates from {len(vault_addresses)} vaults")
        return candidates

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _filter_roles(self, addresses: list[str]) -> tuple[set[str], int]:
        """Filter out vaults, sub-accounts, and missing addresses.

        Returns (valid_addresses, filtered_count).
        """
        valid = set()
        filtered = 0

        # Batch check roles — rate-limit friendly
        for i, addr in enumerate(addresses):
            if i > 0 and i % 20 == 0:
                self.on_progress(f"Role-checking... {i}/{len(addresses)}")
                time.sleep(1.0)  # pause every 20 to avoid 429s

            role = self.collector.get_user_role(addr)
            if role == "user":
                valid.add(addr)
            else:
                filtered += 1
                if role != "missing":
                    logger.debug(f"Filtered {addr[:10]}... (role={role})")

            time.sleep(0.15)  # 150ms between each call

        return valid, filtered

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def discover(
        self,
        min_account_value: float = 1_000_000,
        leaderboard: bool = True,
        vaults: bool = True,
        vault_addresses: Optional[list[str]] = None,
        skip_existing: bool = False,
        max_new: int = 200,
    ) -> DiscoveryResult:
        """Run the full discovery pipeline.

        Args:
            min_account_value: Minimum AV from leaderboard to consider.
            leaderboard: Whether to scan the leaderboard.
            vaults: Whether to scan vault depositors.
            vault_addresses: Custom vault list (defaults to KNOWN_VAULTS).
            skip_existing: If True, skip wallets already in registry.
            max_new: Maximum new wallets to add (rate-limit protection).

        Returns:
            DiscoveryResult with stats about the run.
        """
        start_time = time.time()
        result = DiscoveryResult()

        # --- Step 1: Collect candidates from all channels ---
        all_candidates: dict[str, DiscoveryCandidate] = {}

        if leaderboard:
            for c in self._scan_leaderboard(min_account_value):
                if c.address not in all_candidates:
                    all_candidates[c.address] = c
                result.candidates_found += 1

        if vaults:
            vault_list = vault_addresses or KNOWN_VAULTS
            for c in self._scan_vault_depositors(vault_list):
                if c.address not in all_candidates:
                    all_candidates[c.address] = c
                else:
                    # Merge: keep leaderboard data but add vault source to notes
                    existing = all_candidates[c.address]
                    existing.notes += f" | {c.notes}"
                result.candidates_found += 1

        unique_addresses = list(all_candidates.keys())
        self.on_progress(f"Collected {len(unique_addresses)} unique candidates")

        # --- Step 2: Separate existing vs new ---
        existing_addrs = []
        new_addrs = []
        for addr in unique_addresses:
            if self.registry.get(addr) is not None:
                if skip_existing:
                    result.duplicates_skipped += 1
                else:
                    existing_addrs.append(addr)
            else:
                new_addrs.append(addr)

        # Sort new candidates by AV hint (biggest first)
        new_addrs.sort(key=lambda a: all_candidates[a].account_value_hint, reverse=True)

        # Cap to max_new
        if len(new_addrs) > max_new:
            logger.info(f"Capping new wallets from {len(new_addrs)} to {max_new}")
            new_addrs = new_addrs[:max_new]

        self.on_progress(f"New: {len(new_addrs)}, Existing to refresh: {len(existing_addrs)}")

        # --- Step 3: Role-check new addresses (skip vaults/subAccounts) ---
        if new_addrs:
            self.on_progress(f"Role-checking {len(new_addrs)} new addresses...")
            valid_new, filtered = self._filter_roles(new_addrs)
            result.roles_filtered += filtered
            new_addrs = [a for a in new_addrs if a in valid_new]
            self.on_progress(f"After role filter: {len(new_addrs)} valid users")

            # Cooldown after heavy role-checking to let rate limits reset
            self.on_progress("Cooldown 5s before fetching live data...")
            time.sleep(5)

        # --- Step 4: Fetch live data + score for new wallets ---
        addresses_to_process = new_addrs + existing_addrs
        total = len(addresses_to_process)

        for i, addr in enumerate(addresses_to_process):
            is_new = addr in set(new_addrs)
            candidate = all_candidates.get(addr)

            if i > 0 and i % 10 == 0:
                self.on_progress(f"Processing {i}/{total}...")

            try:
                # Fetch live portfolio
                snapshot = self.collector.fetch_position_snapshot(addr)
                total_notional = sum(p.notional_value for p in snapshot.positions)

                # Check minimum AV with live data
                if snapshot.account_value < MIN_ACCOUNT_VALUE and is_new:
                    result.below_minimum += 1
                    time.sleep(0.15)
                    continue

                # Fetch 30-day trade count
                trade_count_30d = 0
                last_trade_time = None
                try:
                    start_ms = int(
                        (datetime.now(timezone.utc) - timedelta(days=30)).timestamp() * 1000
                    )
                    fills = self.collector.get_user_fills_by_time(addr, start_time=start_ms)
                    trade_count_30d = len(fills)
                    if fills:
                        latest = max(f.get("time", 0) for f in fills)
                        if latest > 0:
                            last_trade_time = datetime.fromtimestamp(
                                latest / 1000, tz=timezone.utc
                            )
                except Exception:
                    pass  # Non-critical

                # Add or update in registry
                if is_new:
                    label = candidate.label if candidate else ""
                    notes = candidate.notes if candidate else ""
                    self.registry.add(address=addr, label=label, notes=notes)
                    result.whales_added += 1
                else:
                    result.whales_updated += 1

                # Score with live data
                self.registry.rescore(
                    address=addr,
                    account_value=snapshot.account_value,
                    total_notional=total_notional,
                    trade_count_30d=trade_count_30d,
                    last_trade_time=last_trade_time,
                )

                tier = self.registry.get(addr).tier
                logger.debug(
                    f"{'NEW' if is_new else 'UPD'} {addr[:10]}... "
                    f"AV=${snapshot.account_value:,.0f} "
                    f"Score={self.registry.get(addr).whale_score:.0f} "
                    f"Tier={tier.value}"
                )

            except Exception as e:
                result.api_errors += 1
                logger.warning(f"Error processing {addr[:10]}...: {e}")

            time.sleep(0.5)  # Rate limiting — 2+ API calls per wallet

        # --- Step 5: Save ---
        self.registry.save()

        result.duration_seconds = round(time.time() - start_time, 1)

        self.on_progress(
            f"Done! +{result.whales_added} new, "
            f"{result.whales_updated} updated, "
            f"{result.roles_filtered} filtered, "
            f"{result.api_errors} errors "
            f"({result.duration_seconds}s)"
        )

        return result
