"""Entry point for QueuePass Bot: no args starts the Flask dashboard; CLI args run the engine."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Sequence

from queuebot.config import load_config, save_config
from queuebot.dashboard import create_app
from queuebot.engine import QueuePassEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="QueuePass Bot — Queue-it Multi-Session Monitor & Pass Link Capture",
    )
    parser.add_argument(
        "--link",
        type=str,
        default=None,
        help="Queue-it waiting room URL (e.g. https://psveindhoven.queue-it.net/?c=...)",
    )
    parser.add_argument(
        "--sessions",
        type=int,
        default=None,
        help="Number of isolated browser contexts to run in parallel",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        help="Platform name (default from config.json, e.g. PSV)",
    )
    parser.add_argument(
        "--label",
        type=str,
        default=None,
        help="Task label for console and Discord notifications",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        default=False,
        help="Run Chromium in visible (headed) mode instead of headless",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Force headless mode",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Dashboard port when starting in UI mode (default: 5055)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    cfg = load_config()

    # No CLI arguments -> launch the Flask dashboard on 127.0.0.1:5055
    if not raw_args:
        port = int(cfg.get("dashboard_port", 5055))
        flask_app = create_app()
        print(f"Starting QueuePass Bot Dashboard on http://127.0.0.1:{port}")
        flask_app.run(host="127.0.0.1", port=port, debug=False)
        return 0

    parser = build_parser()
    args = parser.parse_args(raw_args)

    if args.link is not None:
        cfg["waiting_link"] = args.link.strip()
    if args.sessions is not None:
        cfg["sessions"] = max(1, int(args.sessions))
    if args.platform is not None:
        cfg["platform"] = args.platform.strip()
    if args.label is not None:
        cfg["task_label"] = args.label.strip()
    if args.headed:
        cfg["headless"] = False
    elif args.headless:
        cfg["headless"] = True
    if args.port is not None:
        cfg["dashboard_port"] = int(args.port)

    # If --port was the only flag given without --link, launch dashboard
    if args.link is None and not cfg.get("waiting_link"):
        port = int(cfg.get("dashboard_port", 5055))
        flask_app = create_app()
        print(f"Starting QueuePass Bot Dashboard on http://127.0.0.1:{port}")
        flask_app.run(host="127.0.0.1", port=port, debug=False)
        return 0

    save_config(cfg)
    engine = QueuePassEngine(cfg)
    try:
        engine.validate_and_prepare()
        print(
            f"Launching QueuePass Bot with {cfg['sessions']} session(s) "
            f"(headless={cfg['headless']}) for {cfg['waiting_link']}"
        )
        asyncio.run(engine.run_async())
    except KeyboardInterrupt:
        print("\nStopping QueuePass Bot...")
        engine.stop()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

