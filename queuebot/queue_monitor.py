"""Queue-it page parser (Dutch + English) and pass link detector."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse


@dataclass
class QueueStats:
    """Parsed telemetry from a Queue-it waiting room page."""

    state: str = "waiting"  # waiting, in-queue, passed, challenge, error
    queue_number: int | None = None
    people_ahead: int | None = None
    estimated_wait: str | None = None
    progress: int | None = None
    tickets_available: int | None = None
    max_per_transaction: int | None = None
    is_challenge: bool = False
    pass_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Patterns that describe the 10-minute admission/entry window (NOT estimated wait time)
_ENTRY_WINDOW_PATTERNS = [
    re.compile(
        r"you\s+have\s+\d+\s+minutes?\s+to\s+enter(?:\s+the\s+(?:website|site|shop|store))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:when\s+it\s+is\s+your\s+turn[,\s]+)?you\s+will\s+have\s+\d+\s+minutes?\s+to\s+enter",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:u\s+hebt|u\s+heeft|je\s+hebt)\s+\d+\s+minuten\s+om\s+(?:de\s+(?:website|site|winkel|ticketshop)\s+)?te\s+betreden",
        re.IGNORECASE,
    ),
    re.compile(
        r"\d+[\s-]minute\s+entry\s+window",
        re.IGNORECASE,
    ),
    re.compile(
        r"within\s+\d+\s+minutes?\s+of\s+your\s+turn",
        re.IGNORECASE,
    ),
]

_QUEUE_NUMBER_PATTERNS = [
    re.compile(
        r"(?:your\s+queue\s+number(?:\s+is)?|queue\s+number|queue\s+id|"
        r"uw\s+(?:wacht)?rijnummer(?:\s+is)?|je\s+(?:wacht)?rijnummer(?:\s+is)?|"
        r"wachtrijnummer|rijnummer)\s*[:#-]?\s*([0-9][0-9.,]*)",
        re.IGNORECASE,
    ),
]

_PEOPLE_AHEAD_PATTERNS = [
    re.compile(
        r"(?:number\s+of\s+users\s+in\s+line\s+ahead\s+of\s+you|"
        r"users\s+(?:in\s+line\s+)?ahead\s+of\s+you|"
        r"people\s+ahead\s+of\s+you|"
        r"aantal\s+(?:gebruikers|mensen|personen|bezoekers)\s+(?:in\s+de\s+rij\s+)?voor\s+(?:u|je)|"
        r"gebruikers\s+voor\s+(?:u|je))\s*[:#-]?\s*([0-9][0-9.,]*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b([0-9][0-9.,]*)\s+(?:people|users)\s+(?:in\s+line\s+)?ahead(?:\s+of\s+you)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b([0-9][0-9.,]*)\s+(?:gebruikers|mensen|personen|wachtenden)\s+voor\s+(?:u|je)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bahead\s*[:#-]?\s*([0-9][0-9.,]*)\b",
        re.IGNORECASE,
    ),
]

_LABELED_WAIT_PATTERNS = [
    re.compile(
        r"(?:estimated\s+wait(?:ing)?\s+time|expected\s+wait(?:ing)?\s+time|"
        r"verwachte\s+wachttijd|geschatte\s+wachttijd|wachttijd)\s*[:#-]?\s*"
        r"(meer\s+dan\s+een\s+uur|more\s+than\s+an\s+hour|"
        r"minder\s+dan\s+een\s+minuut|less\s+than\s+a\s+minute|"
        r"(?:ongeveer\s+|circa\s+|about\s+|approx\.?\s+|~\s*)?\d+\s*(?:uur|uren|minuten|minuut|minutes?|mins?|hours?|hrs?)(?:\s+(?:en|and)\s+\d+\s*(?:minuten|minutes?|mins?))?)",
        re.IGNORECASE,
    ),
]

_STANDALONE_WAIT_PATTERNS = [
    re.compile(r"\b(meer\s+dan\s+een\s+uur)\b", re.IGNORECASE),
    re.compile(r"\b(more\s+than\s+an\s+hour)\b", re.IGNORECASE),
    re.compile(r"\b(minder\s+dan\s+een\s+minuut)\b", re.IGNORECASE),
    re.compile(r"\b(less\s+than\s+a\s+minute)\b", re.IGNORECASE),
    re.compile(
        r"((?:~\s*|ongeveer\s+|about\s+|approx\.?\s+)\d+\s*(?:minuten|minuut|minutes?|mins?|uur|hours?))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d+\s*(?:minuten|minuut|minutes?|mins?))\s+(?:remaining|left|resterend|wachttijd)\b",
        re.IGNORECASE,
    ),
]

_PROGRESS_PATTERNS = [
    re.compile(
        r"(?:progress|voortgang)\s*[:#-]?\s*(\d{1,3})\s*%?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(\d{1,3})\s*%\s*(?:voltooid|completed|progress|voortgang)?",
        re.IGNORECASE,
    ),
]

_TICKETS_AVAILABLE_PATTERNS = [
    re.compile(
        r"\b([0-9][0-9.,]*)\s+(?:tickets?|kaarten|plaatsen)\s+(?:available|beschikbaar)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:tickets?\s+available|beschikbare\s+(?:tickets?|kaarten))\s*[:#-]?\s*([0-9][0-9.,]*)",
        re.IGNORECASE,
    ),
]

_MAX_PER_TX_PATTERNS = [
    re.compile(
        r"\b(?:max(?:imum|imaal)?\.?)\s+(\d+)\s+(?:tickets?\s+|kaarten\s+)?per\s+(?:transaction|transactie|order|bestelling)\b",
        re.IGNORECASE,
    ),
]

# Manual captcha indicators (explicitly excluding automatic Botdeflector PoW)
_MANUAL_CHALLENGE_PATTERNS = [
    re.compile(r"verify\s+you\s+are\s+human", re.IGNORECASE),
    re.compile(r"select\s+all\s+(?:images|squares)\s+with", re.IGNORECASE),
    re.compile(r"please\s+solve\s+the\s+captcha", re.IGNORECASE),
    re.compile(r"prove\s+you\s+are\s+not\s+a\s+robot", re.IGNORECASE),
    re.compile(r"los\s+de\s+captcha\s+op", re.IGNORECASE),
]


def _parse_int(raw: str | None) -> int | None:
    """Parse an integer string that may contain '.' or ',' thousands separators."""
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def is_queueit_host(host: str) -> bool:
    """Return True if the hostname belongs to *.queue-it.net."""
    if not host:
        return False
    clean = host.split(":")[0].strip().lower()
    return clean == "queue-it.net" or clean.endswith(".queue-it.net")


def extract_queueit_token(url: str) -> str | None:
    """Extract the queueittoken query parameter from a URL, if present."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        tokens = qs.get("queueittoken")
        if tokens and tokens[0].strip():
            return tokens[0].strip()
    except Exception:
        return None
    return None


def is_pass_url(url: str) -> bool:
    """Check if a URL represents a completed Queue-it pass.

    A session has passed when:
      1. Its URL host is non-empty and is NOT *.queue-it.net
      2. The URL query string contains a non-empty 'queueittoken' parameter.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False

    if is_queueit_host(parsed.hostname):
        return False

    token = extract_queueit_token(url)
    return bool(token)


def strip_entry_window_phrases(text: str) -> str:
    """Remove 10-minute entry window phrases so they are never mistaken for wait times."""
    cleaned = text
    for pattern in _ENTRY_WINDOW_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return cleaned


def parse_queue_page(text: str, current_url: str = "") -> QueueStats:
    """Parse visible text and URL from a Queue-it page into QueueStats."""
    stats = QueueStats()

    if current_url and is_pass_url(current_url):
        stats.state = "passed"
        stats.pass_url = current_url.strip()
        stats.progress = 100
        stats.people_ahead = 0
        return stats

    if not text:
        return stats

    # Check for manual CAPTCHA challenge (note: Botdeflector PoW is automatic and NOT a manual challenge)
    for pattern in _MANUAL_CHALLENGE_PATTERNS:
        if pattern.search(text):
            stats.is_challenge = True
            stats.state = "challenge"
            break

    # Extract queue number
    for pattern in _QUEUE_NUMBER_PATTERNS:
        match = pattern.search(text)
        if match:
            stats.queue_number = _parse_int(match.group(1))
            if stats.queue_number is not None:
                break

    # Extract people ahead
    for pattern in _PEOPLE_AHEAD_PATTERNS:
        match = pattern.search(text)
        if match:
            stats.people_ahead = _parse_int(match.group(1))
            if stats.people_ahead is not None:
                break

    # Strip the 10-minute entry window phrase BEFORE parsing estimated wait time
    sanitized_for_wait = strip_entry_window_phrases(text)

    for pattern in _LABELED_WAIT_PATTERNS:
        match = pattern.search(sanitized_for_wait)
        if match:
            stats.estimated_wait = re.sub(r"\s+", " ", match.group(1)).strip()
            break

    if stats.estimated_wait is None:
        for pattern in _STANDALONE_WAIT_PATTERNS:
            match = pattern.search(sanitized_for_wait)
            if match:
                stats.estimated_wait = re.sub(r"\s+", " ", match.group(1)).strip()
                break

    # Extract progress percentage
    for pattern in _PROGRESS_PATTERNS:
        match = pattern.search(text)
        if match:
            val = _parse_int(match.group(1))
            if val is not None and 0 <= val <= 100:
                stats.progress = val
                break

    # Extract tickets available
    for pattern in _TICKETS_AVAILABLE_PATTERNS:
        match = pattern.search(text)
        if match:
            stats.tickets_available = _parse_int(match.group(1))
            if stats.tickets_available is not None:
                break

    # Extract max tickets per transaction
    for pattern in _MAX_PER_TX_PATTERNS:
        match = pattern.search(text)
        if match:
            stats.max_per_transaction = _parse_int(match.group(1))
            if stats.max_per_transaction is not None:
                break

    # Determine state if not already challenge/passed
    if stats.state not in ("passed", "challenge"):
        if (
            stats.queue_number is not None
            or stats.people_ahead is not None
            or stats.estimated_wait is not None
            or stats.progress is not None
        ):
            stats.state = "in-queue"
        else:
            stats.state = "waiting"

    return stats


def select_best_session(sessions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the session dict with the best position (passed first, then lowest people_ahead, then lowest queue_number)."""
    if not sessions:
        return None

    passed = [s for s in sessions if s.get("state") == "passed"]
    if passed:
        return passed[0]

    with_ahead = [
        s for s in sessions if s.get("people_ahead") is not None and s.get("state") != "error"
    ]
    if with_ahead:
        return min(with_ahead, key=lambda s: int(s["people_ahead"]))

    with_qnum = [
        s for s in sessions if s.get("queue_number") is not None and s.get("state") != "error"
    ]
    if with_qnum:
        return min(with_qnum, key=lambda s: int(s["queue_number"]))

    return sessions[0]

