"""Adaptive crawl politeness controls."""
import email.utils
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit


class PolitenessController(object):
    """Coordinate host-level concurrency, delays, and adaptive backoff."""

    def __init__(self, base_delay=0.0, host_concurrency=4, robots_delay=0.0,
                 adaptive_backoff=True, max_backoff=30.0):
        self.base_delay = max(float(base_delay or 0.0), 0.0)
        self.host_concurrency = max(int(host_concurrency or 1), 1)
        self.robots_delay = max(float(robots_delay or 0.0), 0.0)
        self.adaptive_backoff = bool(adaptive_backoff)
        self.max_backoff = max(float(max_backoff or 30.0), 1.0)
        self._lock = threading.Lock()
        self._hosts = {}

    def update_robots_delay(self, robots_delay):
        """Raise the active robots delay if *robots_delay* is more restrictive."""
        delay = max(float(robots_delay or 0.0), 0.0)
        with self._lock:
            if delay > self.robots_delay:
                self.robots_delay = delay

    def _host_state(self, host):
        with self._lock:
            state = self._hosts.get(host)
            if state is None:
                state = {
                    'semaphore': threading.BoundedSemaphore(self.host_concurrency),
                    'lock': threading.Lock(),
                    'last_request': 0.0,
                    'next_allowed': 0.0,
                    'backoff': 0.0,
                }
                self._hosts[host] = state
            return state

    def acquire(self, url):
        """Wait until *url* may be requested and return the host token."""
        host = (urlsplit(url).netloc or '').lower()
        state = self._host_state(host)
        state['semaphore'].acquire()
        minimum_gap = max(self.base_delay, self.robots_delay)

        while True:
            with state['lock']:
                now = time.time()
                ready_at = max(state['next_allowed'], state['last_request'] + minimum_gap)
                wait_for = ready_at - now
                if wait_for <= 0:
                    state['last_request'] = now
                    return host
            time.sleep(min(wait_for, 0.25))

    def release(self, host):
        """Release a host token acquired via :meth:`acquire`."""
        state = self._host_state(host)
        state['semaphore'].release()

    def record_response(self, url, status_code=None, headers=None):
        """Adjust host backoff based on a response outcome."""
        if not self.adaptive_backoff:
            return
        host = (urlsplit(url).netloc or '').lower()
        state = self._host_state(host)
        retry_after = _parse_retry_after((headers or {}).get('Retry-After'))
        now = time.time()
        with state['lock']:
            if status_code in (429, 503):
                previous = state['backoff'] or 0.0
                state['backoff'] = min(self.max_backoff, max(previous * 2.0, 1.0))
                penalty = retry_after if retry_after is not None else state['backoff']
                state['next_allowed'] = max(state['next_allowed'], now + penalty)
            elif status_code is not None and 200 <= int(status_code) < 400:
                state['backoff'] = 0.0


def _parse_retry_after(value):
    """Return Retry-After seconds as float, or None."""
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max((parsed - datetime.now(timezone.utc)).total_seconds(), 0.0)
