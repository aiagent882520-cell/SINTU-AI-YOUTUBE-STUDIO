"""Application-layer firewall primitives for SINTU AI YOUTUBE STUDIO.

This is a lightweight in-process control, not a replacement for an OS firewall,
reverse-proxy WAF, TLS termination, or network segmentation.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit


def client_address_allowed(address: str, rules: str) -> bool:
    """Match a socket peer address against comma-separated IP/CIDR rules.

    An empty rules string disables the allowlist. Invalid rules fail closed.
    Forwarded headers are intentionally not trusted here.
    """
    if not rules.strip():
        return True
    try:
        client = ipaddress.ip_address(address)
        networks = [ipaddress.ip_network(item.strip(), strict=False)
                    for item in rules.split(",") if item.strip()]
        return bool(networks) and any(client in network for network in networks)
    except ValueError:
        return False


def same_origin_request(origin: str, host: str) -> bool:
    """Compare browser Origin to the request Host without trusting forwarded headers."""
    try:
        parsed_origin = urlsplit(origin)
        parsed_host = urlsplit("//" + host)
        if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.hostname or not parsed_host.hostname:
            return False
        origin_port = parsed_origin.port or (443 if parsed_origin.scheme == "https" else 80)
        host_port = parsed_host.port or (443 if parsed_origin.scheme == "https" else 80)
        return parsed_origin.hostname.lower() == parsed_host.hostname.lower() and origin_port == host_port
    except ValueError:
        return False


class RequestRateLimiter:
    """Thread-safe, bounded-memory sliding-window limiter for a single process."""

    def __init__(self, max_clients: int = 10000):
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_clients = max_clients

    def check(self, key: str, limit: int, window_seconds: int = 60, now: float | None = None) -> tuple[bool, int]:
        if limit <= 0:
            return True, 0
        current = time.monotonic() if now is None else now
        with self._lock:
            events = self._events[key]
            cutoff = current - window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry = max(1, int(window_seconds - (current - events[0]) + 0.999))
                return False, retry
            events.append(current)
            if len(self._events) > self._max_clients:
                stale = [client for client, stamps in self._events.items()
                         if not stamps or stamps[-1] <= cutoff]
                for client in stale:
                    self._events.pop(client, None)
                while len(self._events) > self._max_clients:
                    self._events.pop(next(iter(self._events)))
            return True, 0

    def reset(self, key: str | None = None) -> None:
        """Clear one client's window, or all windows when no key is supplied."""
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)
