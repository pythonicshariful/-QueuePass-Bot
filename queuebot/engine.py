"""Playwright multi-session engine for Queue-it monitoring and pass capture."""

from __future__ import annotations

import asyncio
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .discord_notify import (
    build_pass_embed_payload,
    format_duration,
    send_discord_pass_webhook,
)
from .linkparse import ParsedWaitingLink, parse_waiting_link
from .proxies import ProxyConfig, assign_proxies_for_sessions, parse_proxy_list
from .queue_monitor import is_pass_url, parse_queue_page, select_best_session
from .storage import record_pass_result

DESKTOP_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

DESKTOP_VIEWPORTS: list[dict[str, int]] = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1600, "height": 900},
    {"width": 1280, "height": 800},
]

STEALTH_INIT_SCRIPT = """
(() => {
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });
    if (!window.chrome) {
        window.chrome = { runtime: {} };
    }
    const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (originalQuery) {
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters)
        );
    }
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });
    Object.defineProperty(navigator, 'languages', {
        get: () => ['nl-NL', 'nl', 'en-US', 'en'],
    });
})();
"""


@dataclass
class SessionStatus:
    """Live state of a single browser context session."""

    session_id: int
    proxy_masked: str = "Direct (No Proxy)"
    state: str = "waiting"  # waiting, in-queue, passed, challenge, error, closed
    queue_number: int | None = None
    people_ahead: int | None = None
    estimated_wait: str | None = None
    progress: int | None = None
    tickets_available: int | None = None
    max_per_transaction: int | None = None
    current_url: str = ""
    pass_url: str | None = None
    error_message: str | None = None
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "proxy": self.proxy_masked,
            "state": self.state,
            "queue_number": self.queue_number,
            "people_ahead": self.people_ahead,
            "estimated_wait": self.estimated_wait,
            "progress": self.progress,
            "tickets_available": self.tickets_available,
            "max_per_transaction": self.max_per_transaction,
            "current_url": self.current_url,
            "pass_url": self.pass_url,
            "error_message": self.error_message,
            "updated_at": self.updated_at,
        }


class QueuePassEngine:
    """Manages one Chromium browser with N isolated contexts for Queue-it monitoring."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        data_dir: str | Path | None = None,
        allow_local: bool = False,
    ) -> None:
        self.config = dict(config)
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self.allow_local = allow_local

        self.task_id: str = str(uuid.uuid4())
        self.running: bool = False
        self.started_at: float | None = None
        self.first_pass_at: float | None = None
        self.winning_session_id: int | None = None
        self.pass_link: str | None = None
        self.last_discord_payload: dict[str, Any] | None = None
        self.last_error: str | None = None

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self.parsed_link: ParsedWaitingLink | None = None
        self.session_assignments: list[ProxyConfig | None] = []
        self.sessions: dict[int, SessionStatus] = {}
        self._contexts: dict[int, BrowserContext] = {}
        self._pages: dict[int, Page] = {}

    def validate_and_prepare(self) -> None:
        """Validate waiting link and proxy configuration before launching Chromium."""
        waiting_link = str(self.config.get("waiting_link") or "").strip()
        if not waiting_link:
            raise ValueError("Waiting link is required.")

        parsed_url = urlparse(waiting_link)
        is_local = (parsed_url.hostname or "").lower() in ("127.0.0.1", "localhost")
        effective_allow_local = self.allow_local or is_local

        try:
            self.parsed_link = parse_waiting_link(
                waiting_link, allow_local=effective_allow_local
            )
        except ValueError:
            if effective_allow_local and is_local:
                self.parsed_link = ParsedWaitingLink(
                    original_url=waiting_link,
                    host=parsed_url.netloc.lower(),
                    c="localtest",
                    e="simulated",
                    t="",
                    cid="nl-NL",
                )
            else:
                raise

        num_sessions = max(1, int(self.config.get("sessions", 5)))
        allow_no_proxy = bool(self.config.get("allow_no_proxy", True))
        raw_proxies = self.config.get("proxies") or []
        parsed_proxies = parse_proxy_list(raw_proxies)

        self.session_assignments = assign_proxies_for_sessions(
            parsed_proxies,
            num_sessions=num_sessions,
            allow_no_proxy=allow_no_proxy,
        )

        with self._lock:
            self.sessions.clear()
            for idx, proxy_cfg in enumerate(self.session_assignments, start=1):
                self.sessions[idx] = SessionStatus(
                    session_id=idx,
                    proxy_masked=proxy_cfg.masked if proxy_cfg else "Direct (No Proxy)",
                    state="waiting",
                )

    def start_in_background(self) -> None:
        """Validate configuration and start the engine in a background daemon thread."""
        if self.running:
            raise RuntimeError("Engine is already running.")

        self.validate_and_prepare()
        self._stop_event.clear()
        self.running = True
        self.last_error = None
        self.pass_link = None
        self.winning_session_id = None
        self.first_pass_at = None
        self.task_id = str(uuid.uuid4())

        self._thread = threading.Thread(
            target=self._run_thread_entry,
            name="QueuePassEngineThread",
            daemon=True,
        )
        self._thread.start()

    def _run_thread_entry(self) -> None:
        try:
            asyncio.run(self.run_async())
        except Exception as exc:
            with self._lock:
                self.last_error = str(exc)
        finally:
            with self._lock:
                self.running = False

    def stop(self) -> None:
        """Signal the engine loop to stop and close all sessions cleanly."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=10.0)
        with self._lock:
            self.running = False

    def get_status(self) -> dict[str, Any]:
        """Return a thread-safe snapshot of engine and session states for the dashboard."""
        with self._lock:
            session_list = [
                self.sessions[k].to_dict() for k in sorted(self.sessions.keys())
            ]
            best = select_best_session(session_list)
            best_ahead = best.get("people_ahead") if best else None
            elapsed = (
                round(time.time() - self.started_at, 1)
                if self.started_at is not None
                else 0.0
            )
            return {
                "task_id": self.task_id,
                "running": self.running,
                "platform": self.config.get("platform", "PSV"),
                "task_label": self.config.get("task_label", ""),
                "waiting_link": self.config.get("waiting_link", ""),
                "queue_host": self.parsed_link.host if self.parsed_link else "",
                "elapsed_sec": elapsed,
                "elapsed_formatted": format_duration(elapsed),
                "pass_link": self.pass_link,
                "winning_session_id": self.winning_session_id,
                "best_session": best,
                "best_ahead": best_ahead,
                "last_error": self.last_error,
                "sessions": session_list,
            }

    async def run_async(self) -> None:
        """Main async lifecycle: launch one Chromium browser, N contexts, poll & hold."""
        if not self.parsed_link or not self.session_assignments:
            self.validate_and_prepare()

        assert self.parsed_link is not None
        self.running = True
        self.started_at = time.time()
        self._stop_event.clear()

        headless = bool(self.config.get("headless", True))
        poll_interval = max(0.2, float(self.config.get("poll_interval_sec", 5)))
        hold_seconds = max(0.0, float(self.config.get("hold_minutes_after_pass", 10)) * 60.0)
        stop_others_seconds = max(
            0.0, float(self.config.get("stop_others_minutes_after_pass", 2)) * 60.0
        )

        others_closed = False

        try:
            async with async_playwright() as pw:
                browser: Browser = await pw.chromium.launch(
                    headless=headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )

                try:
                    # Launch all contexts concurrently, isolating per-session errors
                    launch_tasks = [
                        self._start_single_session(
                            browser=browser,
                            session_id=idx,
                            proxy_cfg=proxy_cfg,
                            parsed_link=self.parsed_link,
                        )
                        for idx, proxy_cfg in enumerate(self.session_assignments, start=1)
                    ]
                    await asyncio.gather(*launch_tasks, return_exceptions=True)

                    # Main monitoring loop
                    while not self._stop_event.is_set():
                        poll_tasks = [
                            self._poll_single_session(session_id)
                            for session_id in list(self._pages.keys())
                        ]
                        if poll_tasks:
                            await asyncio.gather(*poll_tasks, return_exceptions=True)

                        # Check hold / stop-others timers after first pass
                        if self.first_pass_at is not None:
                            since_pass = time.time() - self.first_pass_at

                            if not others_closed and since_pass >= stop_others_seconds:
                                await self._close_non_winning_sessions()
                                others_closed = True

                            if since_pass >= hold_seconds:
                                break

                        # Wait for poll_interval in small increments to stay responsive
                        wait_deadline = time.time() + poll_interval
                        while time.time() < wait_deadline and not self._stop_event.is_set():
                            # Also check if a pass happened mid-sleep via navigation
                            for sid, page in list(self._pages.items()):
                                try:
                                    if is_pass_url(page.url):
                                        await self._poll_single_session(sid)
                                except Exception:
                                    pass
                            if self.first_pass_at is not None:
                                since_pass = time.time() - self.first_pass_at
                                if since_pass >= hold_seconds:
                                    break
                            await asyncio.sleep(min(0.25, max(0.05, wait_deadline - time.time())))

                finally:
                    await self._close_all_sessions()
                    await browser.close()
        finally:
            with self._lock:
                self.running = False

    async def _start_single_session(
        self,
        *,
        browser: Browser,
        session_id: int,
        proxy_cfg: ProxyConfig | None,
        parsed_link: ParsedWaitingLink,
    ) -> None:
        """Create an isolated browser context and open the Queue-it waiting link."""
        try:
            ua = random.choice(DESKTOP_USER_AGENTS)
            viewport = random.choice(DESKTOP_VIEWPORTS)

            context_kwargs: dict[str, Any] = {
                "user_agent": ua,
                "viewport": viewport,
                "locale": parsed_link.locale,
                "timezone_id": parsed_link.timezone_id,
            }
            if proxy_cfg is not None:
                context_kwargs["proxy"] = proxy_cfg.to_playwright()

            context = await browser.new_context(**context_kwargs)
            await context.add_init_script(STEALTH_INIT_SCRIPT)
            page = await context.new_page()

            self._contexts[session_id] = context
            self._pages[session_id] = page

            await page.goto(
                parsed_link.original_url,
                wait_until="domcontentloaded",
                timeout=45000,
            )
            await self._poll_single_session(session_id)
        except Exception as exc:
            with self._lock:
                status = self.sessions.get(session_id)
                if status:
                    status.state = "error"
                    status.error_message = str(exc)
                    status.updated_at = datetime.now(timezone.utc).isoformat()

    async def _poll_single_session(self, session_id: int) -> None:
        """Read a session's current URL and visible text, update status, and handle passes."""
        page = self._pages.get(session_id)
        if page is None or page.is_closed():
            return

        try:
            current_url = page.url or ""
            try:
                body_text = await page.inner_text("body", timeout=4000)
            except Exception:
                body_text = ""

            stats = parse_queue_page(body_text, current_url=current_url)

            should_trigger_first_pass = False
            with self._lock:
                status = self.sessions.get(session_id)
                if status is None:
                    return

                prev_qnum = status.queue_number
                prev_ahead = status.people_ahead

                status.current_url = current_url
                status.state = stats.state
                status.queue_number = (
                    stats.queue_number if stats.queue_number is not None else prev_qnum
                )
                status.people_ahead = (
                    stats.people_ahead if stats.people_ahead is not None else prev_ahead
                )
                if stats.state == "passed":
                    status.people_ahead = 0
                    status.progress = 100
                    status.pass_url = stats.pass_url or current_url
                else:
                    if stats.estimated_wait is not None:
                        status.estimated_wait = stats.estimated_wait
                    if stats.progress is not None:
                        status.progress = stats.progress
                    if stats.tickets_available is not None:
                        status.tickets_available = stats.tickets_available
                    if stats.max_per_transaction is not None:
                        status.max_per_transaction = stats.max_per_transaction

                status.updated_at = datetime.now(timezone.utc).isoformat()

                if stats.state == "passed" and self.first_pass_at is None:
                    self.first_pass_at = time.time()
                    self.winning_session_id = session_id
                    self.pass_link = status.pass_url or current_url
                    should_trigger_first_pass = True
                    winning_qnum = status.queue_number
                    winning_prev_ahead = prev_ahead

            if should_trigger_first_pass and self.pass_link:
                self._on_first_pass(
                    session_id=session_id,
                    pass_link=self.pass_link,
                    queue_number=winning_qnum,
                    previous_ahead=winning_prev_ahead,
                )

        except Exception as exc:
            with self._lock:
                status = self.sessions.get(session_id)
                if status and status.state != "passed":
                    status.state = "error"
                    status.error_message = str(exc)
                    status.updated_at = datetime.now(timezone.utc).isoformat()

    def _on_first_pass(
        self,
        *,
        session_id: int,
        pass_link: str,
        queue_number: int | None,
        previous_ahead: int | None,
    ) -> None:
        """Immediately persist, print, and notify Discord when the first session passes."""
        elapsed = (
            time.time() - self.started_at if self.started_at is not None else 0.0
        )
        platform = str(self.config.get("platform") or "PSV")
        label = str(self.config.get("task_label") or "Ticket Drop")
        queue_host = self.parsed_link.host if self.parsed_link else "queue-it.net"

        # Compute best ahead across all sessions (or 0 since passed)
        with self._lock:
            ahead_candidates = [
                s.people_ahead
                for s in self.sessions.values()
                if s.people_ahead is not None and s.session_id != session_id
            ]
        best_ahead = (
            previous_ahead
            if previous_ahead is not None
            else (min(ahead_candidates) if ahead_candidates else 0)
        )

        queue_stats_snapshot = {
            "queue_number": queue_number,
            "best_ahead": best_ahead,
            "time_in_queue_sec": round(elapsed, 2),
            "time_in_queue": format_duration(elapsed),
            "queue_host": queue_host,
        }

        # 1. Save to data/last_pass.txt and append to data/results.json
        record_pass_result(
            task_id=self.task_id,
            platform=platform,
            label=label,
            session_id=session_id,
            queue_stats=queue_stats_snapshot,
            link=pass_link,
            data_dir=self.data_dir,
        )

        # 2. Print clearly to console
        print("\n" + "=" * 72)
        print(f"[PASS DETECTED] Session #{session_id} passed Queue ({queue_host})!")
        print(f"Task Label    : {label} ({platform})")
        print(f"Queue Number  : {queue_number if queue_number is not None else 'N/A'}")
        print(f"Time In Queue : {format_duration(elapsed)}")
        print(f"Direct Link   : {pass_link}")
        print("=" * 72 + "\n", flush=True)

        # 3. Build and send Discord webhook embed
        payload = build_pass_embed_payload(
            task_id=self.task_id,
            platform=platform,
            task_label=label,
            queue_host=queue_host,
            session_id=session_id,
            queue_number=queue_number,
            best_ahead=best_ahead,
            time_in_queue=elapsed,
            pass_link=pass_link,
        )
        self.last_discord_payload = payload

        webhook_url = str(self.config.get("discord_webhook_url") or "").strip()
        if webhook_url:
            send_discord_pass_webhook(webhook_url, payload)

    async def _close_non_winning_sessions(self) -> None:
        """Close all browser contexts except the winning session."""
        for sid in list(self._contexts.keys()):
            if sid == self.winning_session_id:
                continue
            ctx = self._contexts.pop(sid, None)
            self._pages.pop(sid, None)
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass
            with self._lock:
                status = self.sessions.get(sid)
                if status and status.state != "passed":
                    status.state = "closed"
                    status.updated_at = datetime.now(timezone.utc).isoformat()

    async def _close_all_sessions(self) -> None:
        """Close all remaining browser contexts cleanly."""
        for sid in list(self._contexts.keys()):
            ctx = self._contexts.pop(sid, None)
            self._pages.pop(sid, None)
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass

