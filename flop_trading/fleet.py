"""The fleet loop: register every agent, then keep small two-sided offers in close1 for other agents to take,
and accept other agents' offers when they are priced near the market.

Threads: one reader polls close1 (it moves ~60 messages a second and a read returns only the newest 200, so it
polls every couple of seconds) and queues the close-1 messages it finds. The main thread does everything else.
"""

from __future__ import annotations

import collections
import hashlib
import json
import logging
import queue
import random
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from . import protocol as p
from .chat import Chat
from .config import Config
from .keys import Key
from .market import Referee, hl_mid
from .store import Store

log = logging.getLogger(__name__)
LOCK_TIME = datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc)
TIER_WEIGHT = {"strong": 2.0, "medium": 1.5, "weak": 1.0}


@dataclass
class Agent:
    did: str
    nick: str
    tier: str
    key: Key
    lean: float                  # fixed from the DID: some agents lean long, some short
    registered_sweep: int | None
    minted: bool
    owner_posts: int
    position: Decimal
    target: Decimal
    target_until: float
    next_action: float


def load_roster(cfg: Config) -> list[tuple[dict, Key]]:
    """Roster entries whose key file is present and matches the DID. Never logs key material."""
    entries = json.loads(cfg.roster.read_text())
    if cfg.max_agents:
        entries = entries[: cfg.max_agents]
    loaded = []
    for entry in entries:
        path = cfg.keys_dir / f"{entry['nick']}.pem"
        if not path.exists():
            log.error("%s: no key file at %s, skipping", entry["nick"], path)
            continue
        key = Key.load(path)
        if key.did != entry["did"]:
            log.error("%s: key file does not match the roster DID, skipping", entry["nick"])
            continue
        loaded.append((entry, key))
    return loaded


class StreamReader(threading.Thread):
    def __init__(self, chat: Chat, room: str, poll: float, out: queue.Queue):
        super().__init__(daemon=True, name="close1-reader")
        self.chat, self.room, self.poll, self.out = chat, room, poll, out
        self.cursor: int | None = None
        self.read = self.missed = 0
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            started = time.monotonic()
            page = self.chat.read(self.room, since=self.cursor, limit=200)
            if page and page.get("messages"):
                msgs = page["messages"]
                if self.cursor is not None and msgs[0]["seq"] > self.cursor + 1:
                    self.missed += msgs[0]["seq"] - self.cursor - 1
                self.cursor = msgs[-1]["seq"]
                self.read += len(msgs)
                for m in msgs:
                    seen = p.parse(m.get("text"), m.get("from"))
                    if seen:
                        self.out.put(seen)
            self.stop.wait(max(0.0, self.poll - (time.monotonic() - started)))


class Fleet:
    def __init__(self, cfg: Config, roster: list[tuple[dict, Key]], dry_run: bool = False):
        self.cfg, self.dry_run = cfg, dry_run
        self.store = Store(cfg.state_dir / ("dry-run.sqlite" if dry_run else "fleet.sqlite"))
        self.chat = Chat(cfg.base_url, cfg.writes_per_minute, cfg.reads_per_minute)
        self.referee = Referee(self.chat, cfg.referee_did)
        self.events: queue.Queue = queue.Queue(maxsize=100_000)
        self.reader = StreamReader(self.chat, cfg.room, cfg.stream_poll_seconds, self.events)
        self.rng = random.Random()
        self.agents: dict[str, Agent] = {}
        for entry, key in roster:
            self.store.add_agent(entry["did"], entry["nick"])
        rows = {r["did"]: r for r in self.store.agents()}
        for entry, key in roster:
            row = rows[entry["did"]]
            digest = int(hashlib.sha256(entry["did"].encode()).hexdigest()[:8], 16)
            self.agents[entry["did"]] = Agent(
                did=entry["did"], nick=entry["nick"], tier=entry.get("tier", "weak"), key=key,
                lean=(digest % 2001 - 1000) / 1000, registered_sweep=row["registered_sweep"],
                minted=bool(row["minted"]), owner_posts=row["owner_posts"],
                position=Decimal(row["position"]), target=Decimal(row["target"]), target_until=row["target_until"],
                next_action=row["next_action"])
        self.mid: Decimal | None = None
        self.mid_at = 0.0
        self.ref_at = 0.0
        self.considered: collections.OrderedDict[str, None] = collections.OrderedDict()
        self.takes: collections.deque[float] = collections.deque()
        self.stats = collections.Counter()

    # -- posting -----------------------------------------------------------------------------------------

    def post(self, agent: Agent, text: str, what: str) -> bool:
        if self.dry_run:
            self.stats[f"dry_{what}"] += 1
            log.info("dry-run %s %s: %s", what, agent.nick, text[:160])
            return True
        status, body = self.chat.say(agent.key, self.cfg.room, text, self.store.next_nonce(agent.did))
        if status == 200:
            self.stats[f"posted_{what}"] += 1
            return True
        self.stats[f"failed_{what}_{status}"] += 1
        log.warning("%s by %s refused: %s %s", what, agent.nick, status, body[:200])
        return False

    # -- prices --------------------------------------------------------------------------------------------

    def price(self) -> Decimal | None:
        """Hyperliquid's mid if fresh, else the referee's last reference; None if both are stale."""
        if self.mid is not None and time.time() - self.mid_at < 60:
            return self.mid
        if self.referee.ref is not None and time.time() - self.referee.updated < 600:
            return self.referee.ref
        return None

    def in_limits(self, px: Decimal) -> bool:
        """Inside the next sweep's limits, with 0.5% to spare for the reference moving at the sweep."""
        if not self.referee.limits:
            return False
        lo, hi = self.referee.limits
        return lo * Decimal("1.005") <= px <= hi * Decimal("0.995")

    def eligible(self, agent: Agent) -> bool:
        """Minted: the sweep after registration has run, so trades from the next one on can settle."""
        return agent.registered_sweep is not None and self.referee.n > agent.registered_sweep

    def move(self, agent: Agent, side: str, qty: Decimal, sign: int = 1) -> None:
        agent.position += sign * (qty if side == "buy" else -qty)
        self.store.set_agent(agent.did, position=agent.position)

    # -- registration --------------------------------------------------------------------------------------

    def register_some(self, limit: int) -> None:
        """Post each agent's owner message; post it once more an hour later if no flow post showed the mint,
        since close1 keeps only minutes of history and the referee may have missed the first copy."""
        n = self.referee.n
        if not n:
            return
        pending = [a for a in self.agents.values() if a.registered_sweep is None
                   or (not a.minted and a.owner_posts < 2 and n >= a.registered_sweep + 12)][:limit]
        for agent in pending:
            if self.post(agent, p.owner_text(agent.did), "owner"):
                first = agent.registered_sweep is None
                agent.owner_posts += 1
                if first:
                    agent.registered_sweep = n
                    agent.next_action = time.time() + self.rng.uniform(0, 60 * self.cfg.agent_interval_minutes)
                self.store.set_agent(agent.did, registered_sweep=agent.registered_sweep, owner_posts=agent.owner_posts,
                                     next_action=agent.next_action)

    def on_minted(self, keys: set[str]) -> None:
        for did in keys & self.agents.keys():
            if not self.agents[did].minted:
                self.agents[did].minted = True
                self.store.set_agent(did, minted=1)

    # -- making offers -------------------------------------------------------------------------------------

    def retarget(self, agent: Agent, now: float) -> None:
        cap = float(self.cfg.max_position)
        t = max(-cap, min(cap, agent.lean * cap * 0.6 + self.rng.gauss(0, cap * 0.4)))
        agent.target = Decimal(str(round(t, 2)))
        agent.target_until = now + self.rng.uniform(2, 6) * 3600
        self.store.set_agent(agent.did, target=agent.target, target_until=agent.target_until)

    def pick_order(self, agent: Agent) -> tuple[str, Decimal] | None:
        cfg = self.cfg
        gap = agent.target - agent.position
        if abs(gap) >= cfg.qty_min:
            side = ("buy" if gap > 0 else "sell") if self.rng.random() < 0.8 else ("sell" if gap > 0 else "buy")
        else:
            side = self.rng.choice(("buy", "sell"))
        qty = Decimal(str(round(self.rng.uniform(float(cfg.qty_min), float(cfg.qty_max)), 2)))
        for side in (side, "sell" if side == "buy" else "buy"):
            room = cfg.max_position - agent.position if side == "buy" else cfg.max_position + agent.position
            size = min(qty, room)
            if size >= cfg.qty_min:
                return side, size.quantize(p.CENT)
        return None

    def make_offer(self, agent: Agent, mid: Decimal) -> None:
        order = self.pick_order(agent)
        if order is None:
            return
        side, qty = order
        edge = self.cfg.offer_edge
        px = p.cents(mid * (1 + edge)) if side == "buy" else p.cents(mid * (1 - edge), up=True)
        if not self.in_limits(Decimal(px)):
            return
        until = min(self.referee.n + 1 + self.cfg.offer_sweeps, self.cfg.lock_sweep)
        terms = p.make_terms(agent.did, side, qty, px, until)
        if self.post(agent, p.offer_text(terms, p.maker_sig(agent.key, terms)), "offer"):
            self.store.add_trade(terms["id"], agent.did, "maker", side, qty, px, until, "open")

    def act(self, now: float, mid: Decimal) -> None:
        open_by = {r["did"] for r in self.store.open_offers()}
        due = [a for a in self.agents.values() if self.eligible(a) and a.next_action <= now and a.did not in open_by]
        self.rng.shuffle(due)
        for agent in due[:20]:
            if agent.target_until <= now:
                self.retarget(agent, now)
            self.make_offer(agent, mid)
            weight = TIER_WEIGHT.get(agent.tier, 1.0)
            agent.next_action = now + 60 * self.cfg.agent_interval_minutes / weight * self.rng.uniform(0.6, 1.4)
            self.store.set_agent(agent.did, next_action=agent.next_action)

    # -- reading close1 ------------------------------------------------------------------------------------

    def on_trade(self, seen: p.Seen) -> None:
        """A countersigned trade. If it fills one of our offers, record the counterparty."""
        row = self.store.trade(seen.terms["id"])
        if row is None or row["role"] != "maker" or seen.terms["maker"] != row["did"] or row["counterparty"]:
            return
        if seen.taker in self.agents or not p.taker_sig_ok(seen.terms, seen.taker, seen.taker_sig):
            return                                    # our own agents never take our offers; forgeries don't count
        self.store.set_trade(row["id"], counterparty=seen.taker, status="taken")
        self.move(self.agents[row["did"]], row["side"], Decimal(row["qty"]))
        self.stats["offers_taken"] += 1
        log.info("offer %s by %s taken by %s", row["id"], self.agents[row["did"]].nick, seen.taker[-8:])

    def on_offer(self, seen: p.Seen, mid: Decimal | None, now: float) -> None:
        """Someone else's open offer: accept it if it is near the market and one of our agents has room."""
        terms, cfg = seen.terms, self.cfg
        if mid is None or terms["maker"] in self.agents or terms["id"] in self.considered:
            return
        self.considered[terms["id"]] = None
        while len(self.considered) > 50_000:
            self.considered.popitem(last=False)
        our_side = "buy" if terms["side"] == "sell" else "sell"
        px, qty = Decimal(terms["px"]), Decimal(terms["qty"])
        if (qty > cfg.max_take_qty or terms["until"] < self.referee.n + 1 or not self.in_limits(px)
                or (our_side == "buy" and px > mid * (1 + cfg.take_slip))
                or (our_side == "sell" and px < mid * (1 - cfg.take_slip))):
            return
        while self.takes and self.takes[0] < now - 60:
            self.takes.popleft()
        if len(self.takes) >= cfg.takes_per_minute or not p.maker_sig_ok(terms, seen.maker_sig):
            return
        sign = 1 if our_side == "buy" else -1
        fits = [a for a in self.agents.values() if self.eligible(a)
                and abs(a.position + sign * qty) <= cfg.max_position
                and (terms["taker"] == "any" or terms["taker"] == a.did)]
        if not fits:
            return
        keen = [a for a in fits if (a.target - a.position) * sign > 0]
        agent = self.rng.choice(keen or fits)
        text = p.trade_text(terms, agent.did, seen.maker_sig, p.taker_sig(agent.key, terms))
        self.takes.append(now)
        if self.post(agent, text, "take"):
            self.store.add_trade(terms["id"], agent.did, "taker", our_side, qty, terms["px"], terms["until"], "taken",
                                 counterparty=terms["maker"])
            self.move(agent, our_side, qty)
            log.info("%s accepted %s %s @ %s from %s", agent.nick, our_side, qty, terms["px"], terms["maker"][-8:])

    def drain(self, mid: Decimal | None, now: float) -> None:
        for _ in range(5000):
            try:
                seen = self.events.get_nowait()
            except queue.Empty:
                return
            if seen.kind == "trade":
                self.on_trade(seen)
            elif seen.terms["taker"] == "any" or seen.terms["taker"] in self.agents:
                self.on_offer(seen, mid, now)

    # -- referee -------------------------------------------------------------------------------------------

    def apply_outcomes(self, outcomes: list[tuple[str, str]]) -> None:
        for tid, outcome in outcomes:
            row = self.store.trade(tid)
            if row is None or row["status"] in ("settled",) or row["status"].startswith("void"):
                continue
            if outcome == "settled":
                self.store.set_trade(tid, status="settled")
                self.stats["confirmed_settled"] += 1
            else:
                if row["status"] == "taken":           # we had counted it: take it back out
                    self.move(self.agents[row["did"]], row["side"], Decimal(row["qty"]), sign=-1)
                self.store.set_trade(tid, status=f"void:{outcome}")
                self.stats[f"void_{outcome}"] += 1

    # -- main loop -----------------------------------------------------------------------------------------

    def finished(self) -> bool:
        return self.referee.n >= self.cfg.lock_sweep or datetime.now(timezone.utc) >= LOCK_TIME

    def run(self) -> None:
        log.info("fleet of %d agents, room %s, %s", len(self.agents), self.cfg.room, "DRY RUN" if self.dry_run else "LIVE")
        self.reader.start()
        last_report = time.time()
        while True:
            now = time.time()
            if now - self.mid_at > 15:
                self.mid = hl_mid() or self.mid
                self.mid_at = now if self.mid is not None else self.mid_at
            if now - self.ref_at > 20:
                outcomes, minted = self.referee.refresh()
                self.apply_outcomes(outcomes)
                self.on_minted(minted)
                self.store.expire_offers(self.referee.n)
                self.ref_at = now
            if self.finished():
                log.info("trading is locked (sweep %s): stopping", self.referee.n)
                (self.cfg.state_dir / "DONE").write_text(f"locked at sweep {self.referee.n}\n")
                self.reader.stop.set()
                return
            mid = self.price()
            self.drain(mid, now)
            self.register_some(limit=10)
            if mid is not None:
                self.act(now, mid)
            if now - last_report > 300:
                log.info("sweep %s mid %s | stream read %d missed %d | %s | %s", self.referee.n, mid,
                         self.reader.read, self.reader.missed, dict(self.stats), self.store.summary())
                last_report = now
            time.sleep(0.5)


def setup_logging(state_dir: Path, verbose: bool = False) -> None:
    from logging.handlers import RotatingFileHandler
    state_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    handlers = [RotatingFileHandler(state_dir / "flop-trading.log", maxBytes=20_000_000, backupCount=3)]
    if sys.stderr.isatty():
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(fmt)
        root.addHandler(handler)
