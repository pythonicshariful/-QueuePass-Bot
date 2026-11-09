"""Parse and validate Queue-it waiting room links."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

LOCALE_TIMEZONE_MAP: dict[str, str] = {
    "nl-nl": "Europe/Amsterdam",
    "nl-be": "Europe/Brussels",
    "en-gb": "Europe/London",
    "en-us": "America/New_York",
    "de-de": "Europe/Berlin",
    "fr-fr": "Europe/Paris",
    "es-es": "Europe/Madrid",
    "it-it": "Europe/Rome",
    "pt-pt": "Europe/Lisbon",
}


@dataclass(frozen=True)
class ParsedWaitingLink:
    """Structured information extracted from a Queue-it waiting room URL."""

    original_url: str
    host: str
    c: str  # Customer ID (e.g. psveindhoven, liverpoolfc)
    e: str  # Event ID (e.g. psveventq261026, allticketssafetynet)
    t: str  # URL-decoded target URL (e.g. https://ticketshop.psv.nl/)
    cid: str  # Culture/locale ID (e.g. nl-NL, en-GB)

    @property
    def customer(self) -> str:
        return self.c

    @property
    def event(self) -> str:
        return self.e

    @property
    def target_url(self) -> str:
        return self.t

    @property
    def locale(self) -> str:
        return self.cid or "en-GB"

    @property
    def timezone_id(self) -> str:
        key = (self.cid or "").lower()
        return LOCALE_TIMEZONE_MAP.get(key, "Europe/Amsterdam")


def validate_queue_host(host: str, allow_local: bool = False) -> bool:
    """Validate that a hostname is a legitimate Queue-it host (or local test host)."""
    if not host:
        return False
    clean_host = host.split(":")[0].strip().lower()
    if clean_host == "queue-it.net" or clean_host.endswith(".queue-it.net"):
        return True
    if allow_local and clean_host in ("localhost", "127.0.0.1"):
        return True
    return False


def parse_waiting_link(url: str, allow_local: bool = False) -> ParsedWaitingLink:
    """Parse a Queue-it waiting link and extract c, e, t (decoded), and cid.

    Raises ValueError if the URL or Queue-it host is invalid or required parameters
    are missing.
    """
    if not url or not isinstance(url, str):
        raise ValueError("Waiting link must be a non-empty string.")

    cleaned_url = url.strip()
    parsed = urlparse(cleaned_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid URL format: {url!r}")

    hostname = (parsed.hostname or "").lower()
    if not validate_queue_host(hostname, allow_local=allow_local):
        raise ValueError(
            f"Invalid Queue-it host {hostname!r}. Expected '*.queue-it.net'."
        )

    qs = parse_qs(parsed.query, keep_blank_values=True)

    c_val = (qs.get("c", [""])[0] or "").strip()
    e_val = (qs.get("e", [""])[0] or "").strip()
    t_raw = (qs.get("t", [""])[0] or "").strip()
    cid_val = (qs.get("cid", [""])[0] or "").strip()

    # Fallback: extract customer/event fromsubdomain or path if not in query string
    if not c_val and hostname.endswith(".queue-it.net"):
        subdomain = hostname[: -len(".queue-it.net")]
        if subdomain and "." not in subdomain:
            c_val = subdomain

    if not c_val:
        raise ValueError("Missing customer parameter 'c' in Queue-it link.")
    if not e_val:
        raise ValueError("Missing event parameter 'e' in Queue-it link.")

    t_decoded = unquote(t_raw) if t_raw else ""

    if not cid_val:
        cid_val = "nl-NL" if "psv" in c_val.lower() else "en-GB"

    return ParsedWaitingLink(
        original_url=cleaned_url,
        host=parsed.netloc.lower(),
        c=c_val,
        e=e_val,
        t=t_decoded,
        cid=cid_val,
    )

