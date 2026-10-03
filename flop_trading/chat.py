"""technocore.chat over plain HTTP: JSON room reads and signed writes, paced under the per-IP limits."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .keys import Key

log = logging.getLogger(__name__)
USER_AGENT = "flop-trading/0.1 (+https://technocore.chat)"


class Bucket:
    """Token bucket refilled continuously at `per_minute`; shared by every thread."""

    def __init__(self, per_minute: int):
        self.rate = per_minute / 60.0
        self.capacity = max(1.0, per_minute / 6.0)     # at most ten seconds of burst
        self.tokens = self.capacity
        self.stamp = time.monotonic()
        self.lock = threading.Lock()

    def take(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.stamp) * self.rate)
                self.stamp = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)

    def pause(self, seconds: float) -> None:
        """After a 429: hold the bucket empty for the server's Retry-After."""
        with self.lock:
            self.tokens = -seconds * self.rate


class Chat:
    def __init__(self, base: str, writes_per_minute: int, reads_per_minute: int):
        self.base = base.rstrip("/")
        self.writes = Bucket(writes_per_minute)
        self.reads = Bucket(reads_per_minute)

    def _fetch(self, url: str, bucket: Bucket, timeout: float = 30) -> tuple[int, str]:
        bucket.take()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as err:
            body = err.read().decode(errors="replace")
            if err.code == 429:
                retry = float(err.headers.get("Retry-After") or 10)
                log.warning("429 from technocore, pausing %.0fs: %s", retry, body[:200])
                bucket.pause(retry)
            return err.code, body
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as err:
            return 0, str(err)

    def read(self, room: str, since: int | None = None, limit: int = 200) -> dict | None:
        """The newest `limit` messages after `since` (the service returns the newest, not the oldest)."""
        query = {"format": "json", "limit": limit}
        if since is not None:
            query["since"] = since
        status, body = self._fetch(f"{self.base}/r/{room}?{urllib.parse.urlencode(query)}", self.reads)
        if status != 200:
            log.debug("read %s: %s %s", room, status, body[:200])
            return None
        try:
            return json.loads(body)
        except ValueError:
            return None

    def say(self, key: Key, room: str, text: str, nonce: int) -> tuple[int, str]:
        """Signed write on the GET lane. The signature covers `<room>|<nonce>|<text>`; texts here are ASCII JSON."""
        sig = key.sign(f"{room}|{nonce}|{text}")
        path = f"/r/{room}/say-signed/{key.did}/{sig}/{nonce}/{urllib.parse.quote(text, safe='')}"
        return self._fetch(self.base + path, self.writes)
