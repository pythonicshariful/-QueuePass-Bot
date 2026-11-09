"""Configuration management for QueuePass Bot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
DEFAULT_PROXIES_PATH = Path(__file__).resolve().parent.parent / "proxies.txt"

DEFAULT_CONFIG: dict[str, Any] = {
    "waiting_link": "",
    "platform": "PSV",
    "task_label": "PSV Ticket Drop",
    "sessions": 5,
    "proxies": [],
    "discord_webhook_url": "",
    "headless": True,
    "allow_no_proxy": True,
    "poll_interval_sec": 5,
    "hold_minutes_after_pass": 10,
    "stop_others_minutes_after_pass": 2,
    "dashboard_port": 5055,
}


def get_default_config() -> dict[str, Any]:
    """Return a fresh copy of the default configuration."""
    cfg = dict(DEFAULT_CONFIG)
    cfg["proxies"] = list(DEFAULT_CONFIG["proxies"])
    return cfg


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load configuration from JSON file, merging with defaults."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    cfg = get_default_config()

    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key, default_val in DEFAULT_CONFIG.items():
                    if key in raw and raw[key] is not None:
                        cfg[key] = raw[key]
                # Preserve any extra keys
                for key, val in raw.items():
                    if key not in cfg:
                        cfg[key] = val
        except (json.JSONDecodeError, OSError):
            pass

    # Normalize types
    cfg["sessions"] = max(1, int(cfg.get("sessions", 5)))
    cfg["headless"] = bool(cfg.get("headless", True))
    cfg["allow_no_proxy"] = bool(cfg.get("allow_no_proxy", True))
    cfg["poll_interval_sec"] = max(0.2, float(cfg.get("poll_interval_sec", 5)))
    cfg["hold_minutes_after_pass"] = max(0.0, float(cfg.get("hold_minutes_after_pass", 10)))
    cfg["stop_others_minutes_after_pass"] = max(0.0, float(cfg.get("stop_others_minutes_after_pass", 2)))
    cfg["dashboard_port"] = int(cfg.get("dashboard_port", 5055))

    if isinstance(cfg.get("proxies"), str):
        cfg["proxies"] = [
            line.strip()
            for line in cfg["proxies"].splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    elif not isinstance(cfg.get("proxies"), list):
        cfg["proxies"] = []
    else:
        cfg["proxies"] = [
            str(p).strip()
            for p in cfg["proxies"]
            if str(p).strip() and not str(p).strip().startswith("#")
        ]

    # Fallback to proxies.txt if config proxies list is empty and proxies.txt has entries
    if not cfg["proxies"] and path is None and DEFAULT_PROXIES_PATH.exists():
        try:
            file_proxies = [
                line.strip()
                for line in DEFAULT_PROXIES_PATH.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if file_proxies:
                cfg["proxies"] = file_proxies
        except OSError:
            pass

    return cfg


def save_config(config: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    """Save configuration dictionary to JSON file and return normalized config."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    merged = get_default_config()
    merged.update(config)

    if isinstance(merged.get("proxies"), str):
        merged["proxies"] = [
            line.strip()
            for line in merged["proxies"].splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    merged["sessions"] = max(1, int(merged.get("sessions", 5)))
    merged["headless"] = bool(merged.get("headless", True))
    merged["allow_no_proxy"] = bool(merged.get("allow_no_proxy", True))
    merged["poll_interval_sec"] = float(merged.get("poll_interval_sec", 5))
    merged["hold_minutes_after_pass"] = float(merged.get("hold_minutes_after_pass", 10))
    merged["stop_others_minutes_after_pass"] = float(merged.get("stop_others_minutes_after_pass", 2))
    merged["dashboard_port"] = int(merged.get("dashboard_port", 5055))

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Also keep proxies.txt in sync when saving the main config.json
    if path is None:
        try:
            header = (
                "# Proxies managed via QueuePass Bot Dashboard (one per line)\n"
                "# Formats: host:port | host:port:user:pass | user:pass@host:port | http://user:pass@host:port\n"
            )
            body = "\n".join(merged["proxies"])
            DEFAULT_PROXIES_PATH.write_text(
                header + (body + "\n" if body else ""),
                encoding="utf-8",
            )
        except OSError:
            pass

    return merged

