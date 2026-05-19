"""Discord webhook notifications for the Tesla order tracker.

Reads DISCORD_WEBHOOK_URL from the environment (loaded from .env in the
caller). Silent no-op if the webhook URL is not configured.
"""
from __future__ import annotations

import os

from discord_webhook import DiscordEmbed, DiscordWebhook

COLOR_OK = 0x1F8B4C       # green
COLOR_ERROR = 0xC0392B    # red
MAX_EMBED_FIELDS = 25
MAX_FIELD_VALUE = 1024


def _webhook_url() -> str | None:
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    return url or None


def _truncate(value: str, limit: int = MAX_FIELD_VALUE) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _format_change(old: str, new: str) -> str:
    old_disp = old if old else "(empty)"
    new_disp = new if new else "(empty)"
    return _truncate(f"`{old_disp}` -> `{new_disp}`")


def notify_changes(
    rn: str,
    timestamp: str,
    changes: list[tuple[str, str, str]],
) -> None:
    """Post a Discord embed for the given diff. No-op if webhook unconfigured."""
    url = _webhook_url()
    if not url:
        return

    webhook = DiscordWebhook(url=url, rate_limit_retry=True)
    embed = DiscordEmbed(
        title=f"Tesla order update — RN {rn}",
        description=f"{len(changes)} field(s) changed",
        color=COLOR_OK,
    )
    embed.set_timestamp()
    embed.add_embed_field(name="Timestamp (UTC)", value=timestamp, inline=False)

    for field, old, new in changes[:MAX_EMBED_FIELDS - 1]:
        embed.add_embed_field(
            name=_truncate(field, 256),
            value=_format_change(old, new),
            inline=False,
        )

    if len(changes) > MAX_EMBED_FIELDS - 1:
        remaining = len(changes) - (MAX_EMBED_FIELDS - 1)
        embed.add_embed_field(
            name="...and more",
            value=f"+{remaining} additional change(s) — see history.db",
            inline=False,
        )

    webhook.add_embed(embed)
    response = webhook.execute()
    if response is not None and getattr(response, "status_code", 0) >= 400:
        raise RuntimeError(f"Discord webhook returned {response.status_code}: {response.text[:200]}")


def notify_error(message: str) -> None:
    """Post a red error embed. No-op if webhook unconfigured."""
    url = _webhook_url()
    if not url:
        return

    webhook = DiscordWebhook(url=url, rate_limit_retry=True)
    embed = DiscordEmbed(
        title="Tesla tracker error",
        description=_truncate(message, 4000),
        color=COLOR_ERROR,
    )
    embed.set_timestamp()
    webhook.add_embed(embed)
    webhook.execute()
