"""Message formatter — converts PositionEvent + WhaleProfile into Telegram messages.

Each alert is plain HTML (Telegram parse_mode=HTML) so we can use
<b>, <i>, and <code> without needing to escape markdown characters.
"""

from __future__ import annotations

from hyperwhale.models import EventType, PositionEvent, WhaleTier
from hyperwhale.models import WhaleProfile


# Emoji map per event type
_EVENT_EMOJI = {
    EventType.POSITION_OPENED:    "🟢",
    EventType.POSITION_CLOSED:    "🔴",
    EventType.POSITION_INCREASED: "📈",
    EventType.POSITION_DECREASED: "📉",
    EventType.LEVERAGE_CHANGED:   "⚙️",
    EventType.NEW_COIN_ADDED:     "🆕",
}

# Emoji map per whale tier
_TIER_EMOJI = {
    WhaleTier.APEX:          "👑",
    WhaleTier.WHALE:         "🐋",
    WhaleTier.DORMANT_WHALE: "😴",
    WhaleTier.SHARK:         "🦈",
    WhaleTier.DOLPHIN:       "🐬",
    WhaleTier.SKIP:          "⬜",
}

# Staking tier badge
_STAKING_BADGE = {
    "elite": "💎 Elite",
    "high":  "🔷 High",
    "mid":   "🔹 Mid",
    "low":   "🔸 Low",
    "none":  "",
}

EXPLORER_URL = "https://app.hyperliquid.xyz/explorer/address/{address}"


def _fmt_usd(value: float) -> str:
    """Format USD value compactly: $4.85M, $320K, $850."""
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.2f}M"
    elif abs_val >= 1_000:
        return f"{sign}${abs_val / 1_000:.1f}K"
    else:
        return f"{sign}${abs_val:,.0f}"


def _fmt_price(value: float) -> str:
    """Format a price with appropriate decimal places."""
    if value >= 1000:
        return f"${value:,.0f}"
    elif value >= 1:
        return f"${value:,.2f}"
    else:
        return f"${value:.4f}"


def _conviction_pct(notional: float, account_value: float) -> str | None:
    """Return position size as % of account value, or None if unknown."""
    if account_value > 0 and notional > 0:
        pct = (notional / account_value) * 100
        return f"{pct:.0f}%"
    return None


def format_event(event: PositionEvent, whale: WhaleProfile | None = None) -> str:
    """Format a PositionEvent into an HTML Telegram message.

    Args:
        event: The position event to format.
        whale: Optional whale profile for richer context (tier, label, staking).

    Returns:
        HTML string ready to send via Telegram Bot API.
    """
    event_emoji = _EVENT_EMOJI.get(event.event_type, "❓")
    addr_short = f"{event.address[:8]}...{event.address[-6:]}"

    # --- Header line ---
    if whale:
        tier_emoji = _TIER_EMOJI.get(whale.tier, "�")
        label = whale.label or addr_short
        staking = _STAKING_BADGE.get(whale.staked_hype_tier, "")
        staking_str = f"  {staking}" if staking else ""
        header = f"{event_emoji} {tier_emoji} <b>{label}</b>{staking_str}"
    else:
        header = f"{event_emoji} <b>{addr_short}</b>"

    side_str = event.side.value.upper() if event.side else ""
    lines = [header]

    # --- Event-specific body ---
    match event.event_type:

        case EventType.POSITION_OPENED:
            lines.append(
                f"Opened <b>{side_str}</b> on <b>{event.coin}</b> @ "
                f"{_fmt_price(event.entry_price)}  ·  <b>{event.new_leverage:.0f}x</b>"
            )
            conviction = _conviction_pct(
                event.notional_value,
                event.account_value or (whale.account_value if whale else 0),
            )
            size_line = f"💰 Size: <b>{_fmt_usd(event.notional_value)}</b>"
            if conviction:
                size_line += f"  (<b>{conviction}</b> of AV)"
            lines.append(size_line)
            if event.unrealized_pnl != 0:
                pnl_str = _fmt_usd(event.unrealized_pnl)
                pnl_emoji = "🟢" if event.unrealized_pnl >= 0 else "🔴"
                lines.append(f"{pnl_emoji} uPnL: <b>{pnl_str}</b>")
            if event.liquidation_price:
                lines.append(f"💥 Liq: <b>{_fmt_price(event.liquidation_price)}</b>")

        case EventType.POSITION_CLOSED:
            lines.append(f"Closed <b>{event.coin}</b> {side_str}")
            lines.append(f"📦 Was: <b>{_fmt_usd(event.notional_value)}</b>  ·  entry {_fmt_price(event.entry_price)}")
            if event.unrealized_pnl != 0:
                pnl_str = _fmt_usd(event.unrealized_pnl)
                pnl_emoji = "🟢" if event.unrealized_pnl >= 0 else "🔴"
                lines.append(f"{pnl_emoji} Last uPnL: <b>{pnl_str}</b>")

        case EventType.POSITION_INCREASED:
            lines.append(
                f"Added to <b>{event.coin}</b> {side_str}  "
                f"<b>{event.size_change_pct:+.0f}%</b>"
            )
            conviction = _conviction_pct(
                event.notional_value,
                event.account_value or (whale.account_value if whale else 0),
            )
            size_line = f"💰 Now: <b>{_fmt_usd(event.notional_value)}</b>"
            if conviction:
                size_line += f"  (<b>{conviction}</b> of AV)"
            lines.append(size_line)
            lines.append(f"📍 Entry: <b>{_fmt_price(event.entry_price)}</b>  Mark: {_fmt_price(event.mark_price)}")
            if event.unrealized_pnl != 0:
                pnl_str = _fmt_usd(event.unrealized_pnl)
                pnl_emoji = "🟢" if event.unrealized_pnl >= 0 else "🔴"
                lines.append(f"{pnl_emoji} uPnL: <b>{pnl_str}</b>")

        case EventType.POSITION_DECREASED:
            lines.append(
                f"Trimmed <b>{event.coin}</b> {side_str}  "
                f"<b>{event.size_change_pct:+.0f}%</b>"
            )
            lines.append(f"💰 Now: <b>{_fmt_usd(event.notional_value)}</b>")
            lines.append(f"📍 Entry: <b>{_fmt_price(event.entry_price)}</b>  Mark: {_fmt_price(event.mark_price)}")
            if event.unrealized_pnl != 0:
                pnl_str = _fmt_usd(event.unrealized_pnl)
                pnl_emoji = "🟢" if event.unrealized_pnl >= 0 else "🔴"
                lines.append(f"{pnl_emoji} uPnL: <b>{pnl_str}</b>")

        case EventType.LEVERAGE_CHANGED:
            lines.append(
                f"Leverage on <b>{event.coin}</b> {side_str}:  "
                f"<b>{event.old_leverage:.0f}x → {event.new_leverage:.0f}x</b>"
            )
            lines.append(f"💰 Position: <b>{_fmt_usd(event.notional_value)}</b>")
            if event.liquidation_price:
                lines.append(f"💥 New Liq: <b>{_fmt_price(event.liquidation_price)}</b>")

        case _:
            lines.append(f"Unknown event on <b>{event.coin}</b>")

    # --- Footer: score + account value ---
    if whale:
        score_line = (
            f"📊 Score <b>{whale.whale_score:.0f}</b>  "
            f"({whale.tier.value.upper()})  "
            f"AV: <b>{_fmt_usd(whale.account_value)}</b>"
        )
        lines.append(score_line)

    # Explorer link + timestamp
    explorer = EXPLORER_URL.format(address=event.address)
    ts = event.timestamp.strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f'<a href="{explorer}">{addr_short}</a>  ·  <i>{ts}</i>')

    return "\n".join(lines)

    """Format a PositionEvent into an HTML Telegram message.

    Args:
        event: The position event to format.
        whale: Optional whale profile for richer context (tier, label, staking).

    Returns:
        HTML string ready to send via Telegram Bot API.
    """
    event_emoji = _EVENT_EMOJI.get(event.event_type, "❓")
    addr_short = f"{event.address[:8]}...{event.address[-6:]}"

    # --- Header line ---
    if whale:
        tier_emoji = _TIER_EMOJI.get(whale.tier, "🐋")
        label = whale.label or addr_short
        header = f"{event_emoji} {tier_emoji} <b>{label}</b>"
    else:
        header = f"{event_emoji} <b>{addr_short}</b>"

    # --- Event description line ---
    side_str = event.side.value.upper() if event.side else ""

    match event.event_type:
        case EventType.POSITION_OPENED:
            desc = (
                f"Opened <b>{side_str}</b> on <b>{event.coin}</b>\n"
                f"💰 <b>${event.notional_value:,.0f}</b> notional"
                + (f" @ <b>{event.new_leverage:.1f}x</b>" if event.new_leverage else "")
            )

        case EventType.POSITION_CLOSED:
            desc = (
                f"Closed <b>{event.coin}</b> {side_str}\n"
                f"📦 Was <b>${event.notional_value:,.0f}</b> notional"
            )

        case EventType.POSITION_INCREASED:
            desc = (
                f"Increased <b>{event.coin}</b> {side_str} "
                f"<b>{event.size_change_pct:+.1f}%</b>\n"
                f"💰 Now <b>${event.notional_value:,.0f}</b> notional"
            )

        case EventType.POSITION_DECREASED:
            desc = (
                f"Reduced <b>{event.coin}</b> {side_str} "
                f"<b>{event.size_change_pct:+.1f}%</b>\n"
                f"💰 Now <b>${event.notional_value:,.0f}</b> notional"
            )

        case EventType.LEVERAGE_CHANGED:
            desc = (
                f"Changed <b>{event.coin}</b> leverage\n"
                f"⚙️ <b>{event.old_leverage:.1f}x</b> → <b>{event.new_leverage:.1f}x</b>"
            )

        case EventType.NEW_COIN_ADDED:
            desc = f"Started trading <b>{event.coin}</b> for the first time"

        case _:
            desc = f"Unknown event on <b>{event.coin}</b>"

    # --- Footer: wallet context ---
    lines = [header, desc]

    if whale:
        # Score + staking badge
        score_line = f"📊 Score: <b>{whale.whale_score:.0f}</b> ({whale.tier.value.upper()})"
        staking_badge = _STAKING_BADGE.get(whale.staked_hype_tier, "")
        if staking_badge:
            score_line += f"  {staking_badge}"
        lines.append(score_line)

        # Account value
        if whale.account_value > 0:
            lines.append(f"💼 AV: <b>${whale.account_value:,.0f}</b>")

    # Address (always shown)
    lines.append(f"<code>{event.address}</code>")

    # Timestamp
    ts = event.timestamp.strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"<i>{ts}</i>")

    return "\n".join(lines)
