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


def _clean_proxy_lines(lines: list[str] | str) -> list[str]:
    """Return proxy lines stripped of blanks and comments."""
    if isinstance(lines, str):
        lines = lines.splitlines()
    return [
        str(line).strip()
        for line in lines
        if str(line).strip() and not str(line).strip().startswith("#")
    ]


def _read_proxy_file_lines(proxies_path: Path) -> list[str]:
    """Read proxy lines from proxies.txt, ignoring blanks and comments."""
    try:
        return _clean_proxy_lines(
            proxies_path.read_text(encoding="utf-8").splitlines()
        )
    except OSError:
        return []


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
        file_proxies = _read_proxy_file_lines(DEFAULT_PROXIES_PATH)
        if file_proxies:
            cfg["proxies"] = file_proxies

    return cfg


def save_config(config: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    """Save configuration dictionary to JSON file and return normalized config.

    A save that omits the "proxies" key keeps the previously saved proxies
    (from the existing config file, or from proxies.txt when saving the main
    config). Saving must never silently destroy the on-disk proxy list: a
    partial save once wiped proxies.txt to a header-only file and every
    session then ran without a proxy. To clear proxies deliberately, save
    with an explicit empty "proxies" list (the dashboard Save button does
    this when its proxy textarea is empty).
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    proxies_provided = "proxies" in config
    merged = get_default_config()
    merged.update(config)

    if isinstance(merged.get("proxies"), str):
        merged["proxies"] = _clean_proxy_lines(merged["proxies"])
    elif isinstance(merged.get("proxies"), list):
        merged["proxies"] = _clean_proxy_lines(merged["proxies"])

    if not proxies_provided:
        preserved: list[str] = []
        if config_path.exists():
            try:
                raw_existing = json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                raw_existing = None
            if isinstance(raw_existing, dict):
                preserved = _clean_proxy_lines(raw_existing.get("proxies") or [])
        if not preserved and path is None:
            preserved = _read_proxy_file_lines(DEFAULT_PROXIES_PATH)
        merged["proxies"] = preserved

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

