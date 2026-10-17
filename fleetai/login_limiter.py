"""Simple in-process login throttling.

This protects a single-process deployment only. Multi-worker or multi-instance
production must use a shared rate limiter (Redis or edge/WAF).
"""
import time
from collections import defaultdict, deque
from threading import Lock

_WINDOW = 15 * 60
_MAX_FAILURES = 5
_lock = Lock()
_attempts = defaultdict(deque)


def login_blocked(client_ip, now=None):
    now = time.monotonic() if now is None else now
    with _lock:
        attempts = _attempts[client_ip]
        while attempts and attempts[0] <= now - _WINDOW:
            attempts.popleft()
        return len(attempts) >= _MAX_FAILURES


def record_login_failure(client_ip, now=None):
    now = time.monotonic() if now is None else now
    with _lock:
        attempts = _attempts[client_ip]
        while attempts and attempts[0] <= now - _WINDOW:
            attempts.popleft()
        attempts.append(now)


def clear_login_failures(client_ip):
    with _lock:
        _attempts.pop(client_ip, None)
