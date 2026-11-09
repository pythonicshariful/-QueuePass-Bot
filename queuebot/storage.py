"""Persistent storage for captured pass links and run history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def record_pass_result(
    *,
    task_id: str,
    platform: str,
    label: str,
    session_id: int,
    queue_stats: dict[str, Any],
    link: str,
    timestamp: str | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Write the pass link to data/last_pass.txt and append a record to data/results.json."""
    target_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    last_pass_path = target_dir / "last_pass.txt"
    results_path = target_dir / "results.json"

    ts = timestamp or datetime.now(timezone.utc).isoformat()
    record: dict[str, Any] = {
        "task_id": task_id,
        "platform": platform,
        "label": label,
        "session": session_id,
        "queue_stats": queue_stats,
        "timestamp": ts,
        "link": link,
    }

    # Write last_pass.txt immediately
    last_pass_path.write_text(link.strip() + "\n", encoding="utf-8")

    # Append to results.json
    history: list[dict[str, Any]] = []
    if results_path.exists():
        try:
            existing = json.loads(results_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                history = existing
        except (json.JSONDecodeError, OSError):
            history = []

    history.append(record)
    results_path.write_text(
        json.dumps(history, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return record


def load_results_history(data_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Return the list of recorded pass results from data/results.json."""
    target_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    results_path = target_dir / "results.json"
    if not results_path.exists():
        return []
    try:
        data = json.loads(results_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def read_last_pass(data_dir: str | Path | None = None) -> str | None:
    """Read the most recent pass link from data/last_pass.txt, if present."""
    target_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    last_pass_path = target_dir / "last_pass.txt"
    if not last_pass_path.exists():
        return None
    try:
        content = last_pass_path.read_text(encoding="utf-8").strip()
        return content or None
    except OSError:
        return None

