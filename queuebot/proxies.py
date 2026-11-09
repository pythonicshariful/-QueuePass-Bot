"""Proxy parsing, masking, and round-robin rotation for Playwright sessions."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProxyConfig:
    """Normalized proxy configuration compatible with Playwright."""

    server: str  # e.g. "http://host:port"
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    raw: str = ""

    def to_playwright(self) -> dict[str, str]:
        """Return dict formatted for Playwright browser.new_context(proxy=...)."""
        cfg: dict[str, str] = {"server": self.server}
        if self.username is not None:
            cfg["username"] = self.username
        if self.password is not None:
            cfg["password"] = self.password
        return cfg

    @property
    def masked(self) -> str:
        """Return human-readable proxy string with password masked."""
        if self.username:
            return f"{self.username}:***@{self.host}:{self.port}"
        return f"{self.host}:{self.port}"


def parse_proxy(raw_proxy: str) -> ProxyConfig:
    """Parse a single proxy string into a ProxyConfig.

    Supported formats:
      1. host:port
      2. host:port:user:pass
      3. user:pass@host:port
      4. http://user:pass@host:port (or https:// / socks5://, plus http://host:port)
    """
    if not raw_proxy or not isinstance(raw_proxy, str):
        raise ValueError("Proxy string must be non-empty.")

    line = raw_proxy.strip()
    if not line:
        raise ValueError("Proxy string must be non-empty.")

    # Format 4: scheme://...
    if "://" in line:
        parsed = urlparse(line)
        scheme = parsed.scheme or "http"
        host = parsed.hostname
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError(f"Invalid port in proxy: {raw_proxy!r}") from exc

        if not host or not port:
            raise ValueError(f"Missing host or port in URL proxy: {raw_proxy!r}")

        username = parsed.username if parsed.username else None
        password = parsed.password if parsed.password else None
        return ProxyConfig(
            server=f"{scheme}://{host}:{port}",
            host=host,
            port=int(port),
            username=username,
            password=password,
            raw=line,
        )

    # Format 3: user:pass@host:port
    if "@" in line:
        auth_part, host_part = line.rsplit("@", 1)
        if ":" not in auth_part or ":" not in host_part:
            raise ValueError(f"Invalid user:pass@host:port proxy format: {raw_proxy!r}")
        username, password = auth_part.split(":", 1)
        host, port_str = host_part.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError as exc:
            raise ValueError(f"Invalid port in proxy: {raw_proxy!r}") from exc
        if not host or not (1 <= port <= 65535):
            raise ValueError(f"Invalid host or port in proxy: {raw_proxy!r}")
        return ProxyConfig(
            server=f"http://{host}:{port}",
            host=host,
            port=port,
            username=username,
            password=password,
            raw=line,
        )

    # Formats 1 & 2: host:port or host:port:user:pass
    parts = line.split(":")
    if len(parts) == 2:
        host, port_str = parts
        try:
            port = int(port_str)
        except ValueError as exc:
            raise ValueError(f"Invalid port in proxy: {raw_proxy!r}") from exc
        if not host or not (1 <= port <= 65535):
            raise ValueError(f"Invalid host or port in proxy: {raw_proxy!r}")
        return ProxyConfig(
            server=f"http://{host}:{port}",
            host=host,
            port=port,
            username=None,
            password=None,
            raw=line,
        )

    if len(parts) >= 4:
        host = parts[0]
        port_str = parts[1]
        username = parts[2]
        password = ":".join(parts[3:])
        try:
            port = int(port_str)
        except ValueError as exc:
            raise ValueError(f"Invalid port in proxy: {raw_proxy!r}") from exc
        if not host or not (1 <= port <= 65535):
            raise ValueError(f"Invalid host or port in proxy: {raw_proxy!r}")
        return ProxyConfig(
            server=f"http://{host}:{port}",
            host=host,
            port=port,
            username=username,
            password=password,
            raw=line,
        )

    raise ValueError(f"Unsupported proxy format: {raw_proxy!r}")


def parse_proxy_list(raw_proxies: list[str] | str) -> list[ProxyConfig]:
    """Parse a list or multiline string of proxies, ignoring comments and blank lines."""
    if isinstance(raw_proxies, str):
        lines = raw_proxies.splitlines()
    else:
        lines = list(raw_proxies)

    result: list[ProxyConfig] = []
    for line in lines:
        cleaned = str(line).strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        result.append(parse_proxy(cleaned))
    return result


def assign_proxies_for_sessions(
    proxies: list[ProxyConfig],
    num_sessions: int,
    allow_no_proxy: bool = True,
) -> list[ProxyConfig | None]:
    """Assign proxies to sessions in round-robin order (session 1 -> proxy 1, wrap around).

    If proxies is empty:
      - returns [None] * num_sessions if allow_no_proxy is True
      - raises ValueError if allow_no_proxy is False
    """
    if num_sessions < 1:
        raise ValueError("num_sessions must be at least 1.")

    if not proxies:
        if not allow_no_proxy:
            raise ValueError(
                "No proxies configured and 'allow_no_proxy' is disabled. "
                "Please add proxies or enable 'Allow sessions without proxy'."
            )
        return [None] * num_sessions

    return [proxies[i % len(proxies)] for i in range(num_sessions)]

