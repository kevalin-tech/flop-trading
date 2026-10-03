"""Where prices come from: Hyperliquid's xyz:NVDA mid, and the referee's posts in its d- rooms."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

from .chat import Chat

log = logging.getLogger(__name__)
HL_INFO = "https://api.hyperliquid.xyz/info"


def hl_mid(coin: str = "xyz:NVDA", dex: str = "xyz") -> Decimal | None:
    body = json.dumps({"type": "allMids", "dex": dex}).encode()
    req = urllib.request.Request(HL_INFO, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            mids = json.loads(resp.read())
        return Decimal(mids[coin])
    except Exception as err:          # network, JSON or a missing coin: the caller falls back to the reference
        log.warning("hyperliquid mid unavailable: %s", err)
        return None


@dataclass
class Referee:
    """The latest sweep as the referee posted it, and the outcomes it reported for trades we care about."""
    chat: Chat
    referee_did: str
    price_room: str = "d-close1-price"
    flow_room: str = "d-close1-flow"
    n: int = 0                          # last sweep posted
    ref: Decimal | None = None          # its closing price: sets the limits for sweep n + 1
    limits: tuple[Decimal, Decimal] | None = None
    updated: float = 0.0
    _price_since: int | None = None
    _flow_since: int | None = None

    def _poll(self, room: str, since: int | None):
        page = self.chat.read(room, since=since, limit=50)
        if not page:
            return since, []
        posts = []
        for m in page.get("messages", []):
            if m.get("from") != self.referee_did:
                continue
            try:
                posts.append(json.loads(m["text"]))
            except ValueError:
                continue
        return page.get("last_seq", since), posts

    def refresh(self) -> tuple[list[tuple[str, str]], set[str]]:
        """Read new referee posts. Returns the trade outcomes (id, "settled" or void reason) and minted keys that
        the flow posts listed; the posts cut long lists, so most of a busy sweep's ids never appear."""
        self._price_since, posts = self._poll(self.price_room, self._price_since)
        for post in posts:
            if post.get("t") == "price" and post.get("n", 0) >= self.n:
                self.n = post["n"]
                self.ref = Decimal(post["ref"]["px"])
                self.limits = (Decimal(post["limits"][0]), Decimal(post["limits"][1]))
                self.updated = time.time()
        outcomes, minted = [], set()
        self._flow_since, posts = self._poll(self.flow_room, self._flow_since)
        for post in posts:
            if post.get("t") != "flow":
                continue
            outcomes += [(tid, "settled") for tid in post.get("settled", []) if isinstance(tid, str)]
            outcomes += [(item[0], item[1]) for item in post.get("void", []) if isinstance(item, list) and len(item) == 2]
            minted.update(k for k in post.get("mints", []) if isinstance(k, str))
        return outcomes, minted
