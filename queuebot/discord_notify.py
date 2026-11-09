"""Discord webhook embed builder and sender styled after CiroAIO 'Task Update'."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests


def format_duration(seconds: float) -> str:
    """Format elapsed seconds into a human-readable string like '12m 04s' or '45s'."""
    total_sec = max(0, int(round(seconds)))
    hours, rem = divmod(total_sec, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def build_pass_embed_payload(
    *,
    task_id: str,
    platform: str,
    task_label: str,
    queue_host: str,
    session_id: int | str,
    queue_number: int | str | None,
    best_ahead: int | str | None,
    time_in_queue: str | float,
    pass_link: str,
) -> dict[str, Any]:
    """Build a Discord webhook JSON payload styled like CiroAIO 'Task Update'.

    Specification:
      - title = task label + " Successfully passed Queue (<queue host>)!"
      - fields:
          Identifier (task UUID)
          Platform
          Mode: safe
          Session
          Queue Number
          Best Ahead
          Time In Queue
          Direct Pass Link (as a clickable link)
    """
    label_prefix = f"{task_label.strip()} " if task_label and task_label.strip() else ""
    title = f"{label_prefix}Successfully passed Queue ({queue_host})!"

    if isinstance(time_in_queue, (int, float)):
        time_str = format_duration(float(time_in_queue))
    else:
        time_str = str(time_in_queue)

    q_num_str = str(queue_number) if queue_number is not None else "N/A"
    ahead_str = str(best_ahead) if best_ahead is not None else "0"

    fields = [
        {"name": "Identifier", "value": f"`{task_id}`", "inline": False},
        {"name": "Platform", "value": str(platform or "PSV"), "inline": True},
        {"name": "Mode", "value": "safe", "inline": True},
        {"name": "Session", "value": f"#{session_id}", "inline": True},
        {"name": "Queue Number", "value": q_num_str, "inline": True},
        {"name": "Best Ahead", "value": ahead_str, "inline": True},
        {"name": "Time In Queue", "value": time_str, "inline": True},
        {
            "name": "Direct Pass Link",
            "value": f"[Click Here to Enter Shop]({pass_link})\n`{pass_link}`",
            "inline": False,
        },
    ]

    embed = {
        "author": {"name": "Task Update"},
        "title": title,
        "url": pass_link,
        "color": 0x2ECC71,
        "fields": fields,
        "footer": {"text": "QueuePass Bot • Real Browser Pass Capture"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "username": "QueuePass Bot",
        "embeds": [embed],
    }


def send_discord_pass_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    timeout: float = 10.0,
) -> bool:
    """Send the embed payload to the configured Discord webhook URL.

    Returns True on HTTP 2xx, False otherwise.
    """
    if not webhook_url or not webhook_url.strip():
        return False

    try:
        response = requests.post(
            webhook_url.strip(),
            json=payload,
            timeout=timeout,
        )
        return 200 <= response.status_code < 300
    except requests.RequestException:
        return False

