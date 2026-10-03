"""SQLite state: per-agent nonce, registration and position; every offer and trade we posted."""

from __future__ import annotations

import sqlite3
import time
from decimal import Decimal
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    did TEXT PRIMARY KEY,
    nick TEXT NOT NULL,
    nonce INTEGER NOT NULL DEFAULT 0,
    registered_sweep INTEGER,          -- last sweep posted when our owner message landed
    minted INTEGER NOT NULL DEFAULT 0, -- 1 once a flow post listed the mint (the posts cut long lists)
    owner_posts INTEGER NOT NULL DEFAULT 0,
    position TEXT NOT NULL DEFAULT '0',-- contracts, long > 0; optimistic: counts trades we saw posted
    target TEXT NOT NULL DEFAULT '0',
    target_until REAL NOT NULL DEFAULT 0,
    next_action REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    did TEXT NOT NULL,                 -- our agent
    role TEXT NOT NULL,                -- 'maker' (our offer) or 'taker' (we accepted theirs)
    side TEXT NOT NULL,                -- our side: buy or sell
    qty TEXT NOT NULL,
    px TEXT NOT NULL,
    until INTEGER NOT NULL,
    counterparty TEXT,                 -- set when we see the countersigned trade
    status TEXT NOT NULL,              -- open, taken, expired, settled, void:<reason>
    posted REAL NOT NULL,
    updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS trades_open ON trades(status, did);
CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    # agents
    def add_agent(self, did: str, nick: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO agents(did, nick) VALUES (?, ?)", (did, nick))

    def agents(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM agents").fetchall()

    def next_nonce(self, did: str) -> int:
        """Epoch milliseconds, kept strictly increasing per key across restarts."""
        last = self.db.execute("SELECT nonce FROM agents WHERE did = ?", (did,)).fetchone()[0]
        nonce = max(int(time.time() * 1000), last + 1)
        self.db.execute("UPDATE agents SET nonce = ? WHERE did = ?", (nonce, did))
        return nonce

    def set_agent(self, did: str, **fields) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE agents SET {cols} WHERE did = ?",
                        [str(v) if isinstance(v, Decimal) else v for v in fields.values()] + [did])

    # trades
    def add_trade(self, tid: str, did: str, role: str, side: str, qty: Decimal, px: str, until: int,
                  status: str, counterparty: str | None = None) -> None:
        now = time.time()
        self.db.execute("INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (tid, did, role, side, str(qty), px, until, counterparty, status, now, now))

    def trade(self, tid: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone()

    def set_trade(self, tid: str, **fields) -> None:
        fields["updated"] = time.time()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE trades SET {cols} WHERE id = ?", list(fields.values()) + [tid])

    def open_offers(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM trades WHERE status = 'open'").fetchall()

    def expire_offers(self, last_sweep: int) -> int:
        """Offers whose last valid sweep has passed without us seeing them taken."""
        cur = self.db.execute("UPDATE trades SET status = 'expired', updated = ? WHERE status = 'open' AND until <= ?",
                              (time.time(), last_sweep))
        return cur.rowcount

    # meta
    def get(self, name: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE name = ?", (name,)).fetchone()
        return row[0] if row else default

    def put(self, name: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (name, str(value)))

    def summary(self) -> dict:
        q = lambda sql: self.db.execute(sql).fetchone()[0]
        return {
            "agents": q("SELECT COUNT(*) FROM agents"),
            "registered": q("SELECT COUNT(*) FROM agents WHERE registered_sweep IS NOT NULL"),
            "mint_seen": q("SELECT COUNT(*) FROM agents WHERE minted = 1"),
            "offers_posted": q("SELECT COUNT(*) FROM trades WHERE role = 'maker'"),
            "offers_open": q("SELECT COUNT(*) FROM trades WHERE status = 'open'"),
            "offers_taken_by_others": q("SELECT COUNT(*) FROM trades WHERE role = 'maker' AND counterparty IS NOT NULL"),
            "offers_we_accepted": q("SELECT COUNT(*) FROM trades WHERE role = 'taker'"),
            "confirmed_settled": q("SELECT COUNT(*) FROM trades WHERE status = 'settled'"),
            "confirmed_void": q("SELECT COUNT(*) FROM trades WHERE status LIKE 'void:%'"),
            "counterparties": q("SELECT COUNT(DISTINCT counterparty) FROM trades WHERE counterparty IS NOT NULL"),
            "agents_with_a_trade": q("SELECT COUNT(DISTINCT did) FROM trades WHERE counterparty IS NOT NULL"),
        }
