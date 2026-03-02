"""Hyperliquid API data collector.

Pulls positions, trades, market data from the public Hyperliquid Info API.
No API key required for read-only access.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import httpx
from loguru import logger

from hyperwhale.constants import MAINNET_API_URL, INFO_ENDPOINT
from hyperwhale.models import (
    Position,
    PositionSide,
    PositionSnapshot,
    Trade,
    TradeDirection,
)


class HyperliquidCollector:
    """Collects data from the Hyperliquid public Info API."""

    def __init__(self, base_url: str = MAINNET_API_URL) -> None:
        self.base_url = base_url
        self.info_url = f"{base_url}{INFO_ENDPOINT}"
        self._client = httpx.Client(timeout=30.0)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ------------------------------------------------------------------
    # Low-level API call
    # ------------------------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> Any:
        """Send a POST request to the info endpoint with retry on 429."""
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                resp = self._client.post(
                    self.info_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 429:
                    if attempt < max_retries:
                        wait = 2 ** attempt  # 1s, 2s, 4s
                        logger.debug(f"Rate limited (429), retrying in {wait}s...")
                        import time
                        time.sleep(wait)
                        continue
                    else:
                        logger.error("Rate limited (429) after max retries")
                        resp.raise_for_status()
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 429:
                    logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
                raise
            except httpx.RequestError as e:
                logger.error(f"Request error: {e}")
                raise

    # ------------------------------------------------------------------
    # User Data
    # ------------------------------------------------------------------

    def get_user_state(self, address: str) -> dict[str, Any]:
        """Get a user's perpetual positions and margin summary (clearinghouseState)."""
        return self._post({"type": "clearinghouseState", "user": address})

    def get_user_fills(self, address: str, limit: int = 2000) -> list[dict]:
        """Get a user's recent fills (up to 2000)."""
        return self._post({"type": "userFills", "user": address})

    def get_user_fills_by_time(
        self,
        address: str,
        start_time: int,
        end_time: Optional[int] = None,
    ) -> list[dict]:
        """Get a user's fills within a time range.

        Args:
            address: Wallet address.
            start_time: Start timestamp in milliseconds.
            end_time: Optional end timestamp in milliseconds.
        """
        payload: dict[str, Any] = {
            "type": "userFillsByTime",
            "user": address,
            "startTime": start_time,
        }
        if end_time is not None:
            payload["endTime"] = end_time
        return self._post(payload)

    def get_open_orders(self, address: str) -> list[dict]:
        """Get a user's open orders."""
        return self._post({"type": "openOrders", "user": address})

    def get_historical_orders(self, address: str) -> list[dict]:
        """Get a user's historical orders (up to 2000)."""
        return self._post({"type": "historicalOrders", "user": address})

    def get_user_portfolio(self, address: str) -> list:
        """Get a user's portfolio (account value history, PnL)."""
        return self._post({"type": "portfolio", "user": address})

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------

    def get_all_mids(self) -> dict[str, str]:
        """Get mid prices for all coins."""
        return self._post({"type": "allMids"})

    def get_meta_and_asset_ctxs(self) -> list:
        """Get perpetuals metadata + asset contexts (mark price, funding, OI, etc)."""
        return self._post({"type": "metaAndAssetCtxs"})

    def get_l2_book(self, coin: str, n_levels: int = 20) -> dict:
        """Get L2 order book snapshot for a coin."""
        return self._post({"type": "l2Book", "coin": coin, "nSigFigs": 5})

    def get_candle_snapshot(
        self,
        coin: str,
        interval: str = "1h",
        start_time: int = 0,
        end_time: Optional[int] = None,
    ) -> list[dict]:
        """Get OHLCV candle data for a coin."""
        payload: dict[str, Any] = {
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval, "startTime": start_time},
        }
        if end_time is not None:
            payload["req"]["endTime"] = end_time
        return self._post(payload)

    def get_funding_history(
        self, coin: str, start_time: int, end_time: Optional[int] = None
    ) -> list[dict]:
        """Get historical funding rates for a coin."""
        payload: dict[str, Any] = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": start_time,
        }
        if end_time is not None:
            payload["endTime"] = end_time
        return self._post(payload)

    def get_predicted_funding(self) -> list:
        """Get predicted funding rates across venues."""
        return self._post({"type": "predictedFundings"})

    # ------------------------------------------------------------------
    # Vault Data
    # ------------------------------------------------------------------

    def get_vault_details(self, vault_address: str) -> dict:
        """Get details for a vault (AUM, followers, PnL)."""
        return self._post({"type": "vaultDetails", "vaultAddress": vault_address})

    def get_user_role(self, address: str) -> str:
        """Check if an address is a 'user', 'vault', 'subAccount', or 'missing'."""
        try:
            result = self._post({"type": "userRole", "user": address})
            return result.get("role", "missing") if isinstance(result, dict) else "missing"
        except Exception:
            return "missing"

    # ------------------------------------------------------------------
    # Leaderboard (stats API — separate from the info endpoint)
    # ------------------------------------------------------------------

    def get_leaderboard(self) -> list[dict]:
        """Fetch the full Hyperliquid leaderboard (~30K traders).

        Returns list of dicts with keys:
            ethAddress, accountValue, windowPerformances, prize, displayName
        """
        url = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
        try:
            resp = self._client.get(url, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            return data.get("leaderboardRows", [])
        except Exception as e:
            logger.error(f"Leaderboard fetch failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Parsing Helpers — Convert raw API responses into our models
    # ------------------------------------------------------------------

    def fetch_position_snapshot(self, address: str) -> PositionSnapshot:
        """Fetch and parse a whale's full position snapshot."""
        raw = self.get_user_state(address)
        now = datetime.utcnow()

        # Parse margin summary
        margin = raw.get("marginSummary", {})
        account_value = float(margin.get("accountValue", 0))
        total_margin = float(margin.get("totalMarginUsed", 0))
        total_notional = float(margin.get("totalNtlPos", 0))
        withdrawable = float(raw.get("withdrawable", 0))

        # Parse positions
        positions: list[Position] = []
        for ap in raw.get("assetPositions", []):
            pos = ap.get("position", {})
            if not pos:
                continue

            szi = float(pos.get("szi", 0))
            if szi == 0:
                continue  # no position

            side = PositionSide.LONG if szi > 0 else PositionSide.SHORT

            leverage_info = pos.get("leverage", {})
            leverage_val = float(leverage_info.get("value", 1))
            leverage_type = leverage_info.get("type", "cross")

            entry_px = float(pos.get("entryPx", 0))
            mark_px = float(pos.get("positionValue", 0)) / abs(szi) if szi != 0 else 0
            liq_px_raw = pos.get("liquidationPx")
            liq_px = float(liq_px_raw) if liq_px_raw and liq_px_raw != "null" else None

            positions.append(
                Position(
                    address=address,
                    coin=pos.get("coin", ""),
                    side=side,
                    size=abs(szi),
                    notional_value=abs(float(pos.get("positionValue", 0))),
                    entry_price=entry_px,
                    mark_price=mark_px,
                    liquidation_price=liq_px,
                    leverage=leverage_val,
                    leverage_type=leverage_type,
                    unrealized_pnl=float(pos.get("unrealizedPnl", 0)),
                    margin_used=float(pos.get("marginUsed", 0)),
                    timestamp=now,
                )
            )

        return PositionSnapshot(
            address=address,
            account_value=account_value,
            total_margin_used=total_margin,
            total_notional_position=total_notional,
            withdrawable=withdrawable,
            positions=positions,
            timestamp=now,
        )

    def fetch_recent_trades(
        self,
        address: str,
        since_ms: Optional[int] = None,
    ) -> list[Trade]:
        """Fetch and parse a whale's recent trades."""
        if since_ms is not None:
            raw_fills = self.get_user_fills_by_time(address, since_ms)
        else:
            raw_fills = self.get_user_fills(address)

        trades: list[Trade] = []
        for f in raw_fills:
            # Determine direction
            direction_str = f.get("dir", "")
            try:
                direction = TradeDirection(direction_str)
            except ValueError:
                # Handle non-standard directions like "Buy", "Sell"
                if f.get("side") == "B":
                    direction = TradeDirection.OPEN_LONG
                else:
                    direction = TradeDirection.CLOSE_LONG

            px = float(f.get("px", 0))
            sz = float(f.get("sz", 0))

            trades.append(
                Trade(
                    address=address,
                    coin=f.get("coin", ""),
                    side=f.get("side", ""),
                    direction=direction,
                    price=px,
                    size=sz,
                    notional_value=px * sz,
                    closed_pnl=float(f.get("closedPnl", 0)),
                    fee=float(f.get("fee", 0)),
                    is_crossed=f.get("crossed", False),
                    order_id=int(f.get("oid", 0)),
                    trade_id=int(f.get("tid", 0)),
                    tx_hash=f.get("hash", ""),
                    timestamp=datetime.utcfromtimestamp(f.get("time", 0) / 1000),
                )
            )

        return trades


# ---------------------------------------------------------------------------
# Module-level convenience — run directly to test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from rich import print as rprint

    collector = HyperliquidCollector()

    # Quick test — fetch mid prices
    mids = collector.get_all_mids()
    rprint(f"[green]✓ Connected to Hyperliquid API — {len(mids)} coins available[/green]")
    rprint(f"  BTC: ${mids.get('BTC', 'N/A')}")
    rprint(f"  ETH: ${mids.get('ETH', 'N/A')}")
    rprint(f"  HYPE: ${mids.get('HYPE', 'N/A')}")

    collector.close()
